#!/usr/bin/env python3
"""Simplified Lightweight OCR Worker - Optimized version"""

import os
import sys
import time
import json
import logging
import tempfile
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2image import convert_from_path
from paddleocr import PaddleOCR
from src.config import Config
from src.database import DatabaseHandler
from src.s3_handler import S3Handler
from src.extraction import TableExtractor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('LightweightOCRWorker')

class LightweightOCRWorker:
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.db = DatabaseHandler()
        self.s3 = S3Handler()
        # Re-enabled: TableExtractor now works with PaddleOCR v2 format
        self.table_extractor = TableExtractor(worker_id)

        # Initialize OCR with PaddleOCR 2.8 - simpler and more stable
        # Uses mobile models by default for CPU performance
        self.ocr = PaddleOCR(
            use_angle_cls=False,  # Disable angle classification for speed
            lang='en',  # English model is more stable with v2
            use_gpu=False,  # Explicitly use CPU
            enable_mkldnn=True,  # Enable Intel MKL-DNN optimization
            cpu_threads=4,  # Limit CPU threads per worker
            use_tensorrt=False,  # Disable TensorRT (GPU only)
            det_db_score_mode='fast',  # Fast detection mode
            show_log=False  # Reduce logging noise
        )
        logger.info(f"Worker {worker_id}: OCR initialized")

    def process_documents(self):
        """Main processing loop"""
        while True:
            try:
                # Get next document
                doc = self.db.get_next_document(self.worker_id)
                if not doc:
                    time.sleep(5)
                    continue

                self.process_single_document(doc)

            except Exception as e:
                logger.error(f"Worker {self.worker_id}: Error: {e}")
                if doc:
                    self.db.mark_failed(doc['id'], str(e))

    def process_single_document(self, doc):
        """Process a single document"""
        start_time = datetime.now()
        siren = doc['siren']
        s3_key = doc['s3_key']

        logger.info(f"Worker {self.worker_id}: Processing {siren}")

        # Download PDF
        download_start = datetime.now()
        pdf_path = self.s3.download_pdf(s3_key)
        download_time = (datetime.now() - download_start).total_seconds()
        logger.info(f"Worker {self.worker_id}: PDF download took {download_time:.2f}s")

        try:
            # Convert PDF to images
            convert_start = datetime.now()
            images = convert_from_path(pdf_path, dpi=150, thread_count=4)
            num_pages = len(images)
            convert_time = (datetime.now() - convert_start).total_seconds()
            logger.info(f"Worker {self.worker_id}: PDF conversion took {convert_time:.2f}s for {num_pages} pages")

            # Collect ALL results first
            ocr_start = datetime.now()
            all_pages_data = []
            all_ocr_raw_results = []  # Store raw OCR results for JSON file
            batch_size = 30  # Large batch size with 40GB memory available

            import gc  # Import gc at the beginning

            # Track timing for OCR vs extraction
            total_ocr_time = 0
            total_extraction_time = 0

            # Process in batches
            for batch_start in range(0, num_pages, batch_size):
                batch_end = min(batch_start + batch_size, num_pages)
                batch_results, batch_ocr_time, batch_extraction_time = self.process_batch(images[batch_start:batch_end], batch_start)

                total_ocr_time += batch_ocr_time
                total_extraction_time += batch_extraction_time

                # Store results
                for page_num, (page_data, raw_result) in enumerate(batch_results, batch_start + 1):
                    all_pages_data.append(page_data)
                    if raw_result:
                        # Convert numpy arrays to lists for JSON serialization
                        serializable_result = self._make_json_serializable(raw_result)
                        all_ocr_raw_results.append({
                            "page": page_num,
                            "ocr_result": serializable_result
                        })

                # Free memory after each batch
                gc.collect()

                logger.info(f"Worker {self.worker_id}: Processed pages {batch_start+1}-{batch_end}")

            # Clear images from memory
            del images
            gc.collect()

            total_processing_time = (datetime.now() - ocr_start).total_seconds()
            logger.info(f"Worker {self.worker_id}: Total processing took {total_processing_time:.2f}s (OCR: {total_ocr_time:.2f}s, Extraction: {total_extraction_time:.2f}s)")

            # Create initial timing info
            timing_info = {
                'download': f"{download_time:.2f}",
                'conversion': f"{convert_time:.2f}",
                'ocr': f"{total_ocr_time:.2f}",
                'extraction': f"{total_extraction_time:.2f}",
                'total_processing': f"{total_processing_time:.2f}",
                'output_generation': 'pending',
                'upload': 'pending',
                'total': 'pending'
            }

            # Generate production output with initial timing
            output_gen_start = datetime.now()
            txt_filename = self.save_raw_text_output(siren, all_pages_data, num_pages, timing_info)
            output_gen_time = (datetime.now() - output_gen_start).total_seconds()
            timing_info['output_generation'] = f"{output_gen_time:.2f}"

            # Prepare S3 keys for both text and JSON outputs
            text_output_key = f"structured_output/{siren[:3]}/{siren}.txt"
            json_output_key = f"structured_output/{siren[:3]}/{siren}_raw_ocr.json"
            text_s3_url = f"https://{Config.S3_BUCKET}.s3.{Config.S3_REGION}.amazonaws.com/{text_output_key}"
            json_s3_url = f"https://{Config.S3_BUCKET}.s3.{Config.S3_REGION}.amazonaws.com/{json_output_key}"

            try:
                # First, update the local file with output generation time
                timing_info['output_generation'] = f"{output_gen_time:.2f}"
                self.update_timing_in_file(txt_filename, timing_info)

                # Read the updated file for upload
                with open(txt_filename, 'r', encoding='utf-8') as f:
                    txt_content = f.read()

                # Upload both text and JSON files
                upload_start = datetime.now()

                # Upload text file
                text_uploaded = self.s3.upload_text(txt_content, text_output_key)

                # Create JSON with raw OCR data
                raw_ocr_data = {
                    "siren": siren,
                    "num_pages": num_pages,
                    "processing_timestamp": datetime.now().isoformat(),
                    "timing_info": timing_info,
                    "raw_ocr_results": all_ocr_raw_results  # Raw OCR results only
                }

                json_content = json.dumps(raw_ocr_data, indent=2, ensure_ascii=False)
                json_uploaded = self.s3.upload_text(json_content, json_output_key)

                if text_uploaded and json_uploaded:
                    upload_time = (datetime.now() - upload_start).total_seconds()
                    total_time = (datetime.now() - start_time).total_seconds()

                    # Final timing info
                    timing_info['upload'] = f"{upload_time:.2f}"
                    timing_info['total'] = f"{total_time:.2f}"

                    # Update text file with final timing
                    self.update_timing_in_file(txt_filename, timing_info)
                    with open(txt_filename, 'r', encoding='utf-8') as f:
                        final_txt_content = f.read()
                    self.s3.upload_text(final_txt_content, text_output_key)

                    # Update JSON with final timing
                    raw_ocr_data['timing_info'] = timing_info
                    json_content = json.dumps(raw_ocr_data, indent=2, ensure_ascii=False)
                    self.s3.upload_text(json_content, json_output_key)

                    processing_time_ms = int(total_time * 1000)
                    # Update database with text URL in ocr_s3_path and JSON URL in ocr_text_file_path
                    self.db.mark_completed(doc['id'], text_s3_url, json_s3_url, processing_time_ms, num_pages, len(final_txt_content))
                    logger.info(f"Worker {self.worker_id}: Completed {siren} - {num_pages} pages - Text in ocr_s3_path, JSON in ocr_text_file_path - Total: {total_time:.2f}s (Download: {download_time:.2f}s, Convert: {convert_time:.2f}s, OCR: {total_ocr_time:.2f}s, Extract: {total_extraction_time:.2f}s, Upload: {upload_time:.2f}s)")
                else:
                    self.db.mark_failed(doc['id'], "Failed to upload JSON file")
            except Exception as e:
                logger.error(f"Worker {self.worker_id}: Failed to upload text file: {e}")
                self.db.mark_failed(doc['id'], f"Upload error: {str(e)}")

        finally:
            # Clean up
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    def process_batch(self, images, batch_start_idx):
        """Process a batch of images"""
        batch_results = []
        batch_ocr_time = 0
        batch_extraction_time = 0

        for i, image in enumerate(images):
            page_num = batch_start_idx + i + 1

            # Save image temporarily
            tmp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
            image.convert('L').save(tmp_file.name, 'JPEG', quality=95)
            tmp_file.close()

            try:
                # Run OCR
                ocr_start = datetime.now()
                ocr_result = self.ocr.ocr(tmp_file.name)
                ocr_end = datetime.now()
                page_ocr_time = (ocr_end - ocr_start).total_seconds()
                batch_ocr_time += page_ocr_time

                # Parse result
                page_text = []
                text_blocks = []
                raw_result = None

                if ocr_result and len(ocr_result) > 0:
                    result = ocr_result[0]
                    raw_result = result  # Store for debug file

                    # Extract text based on format
                    if 'rec_texts' in result:
                        # New format
                        texts = result['rec_texts']
                        boxes = result.get('dt_polys', [])
                        scores = result.get('rec_scores', [])

                        for idx, text in enumerate(texts):
                            if text and text.strip():
                                page_text.append(text)
                                if idx < len(boxes):
                                    text_blocks.append({
                                        'text': text,
                                        'bbox': boxes[idx].tolist() if hasattr(boxes[idx], 'tolist') else boxes[idx],
                                        'confidence': scores[idx] if idx < len(scores) else 0.0
                                    })
                    else:
                        # Old format
                        for item in result:
                            if isinstance(item, (list, tuple)) and len(item) >= 2:
                                box, text_data = item[0], item[1]
                                if isinstance(text_data, (list, tuple)) and len(text_data) >= 2:
                                    text, confidence = text_data[0], text_data[1]
                                    if text and text.strip():
                                        page_text.append(text)
                                        text_blocks.append({
                                            'text': text,
                                            'bbox': box,
                                            'confidence': confidence
                                        })

                # Table extraction - works with PaddleOCR v2 format conversion
                extraction_start = datetime.now()
                tables = self.table_extractor.extract_tables_from_page(text_blocks, page_num)
                extraction_end = datetime.now()
                page_extraction_time = (extraction_end - extraction_start).total_seconds()
                batch_extraction_time += page_extraction_time

                page_data = {
                    "page": page_num,
                    "text": " ".join(page_text),
                    "text_blocks": text_blocks,
                    "tables": tables  # Add extracted tables
                }

                batch_results.append((page_data, raw_result))

            finally:
                # Clean up temp file
                if os.path.exists(tmp_file.name):
                    os.unlink(tmp_file.name)

        return batch_results, batch_ocr_time, batch_extraction_time

    def save_raw_text_output(self, siren, all_pages_data, num_pages, timing_info=None):
        """Generate OCR output for ALL pages - text and tables only"""
        try:
            filename = f'/tmp/ocr_{siren}.txt'
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"=== RAW OCR OUTPUT FOR {siren} ===\n")
                f.write(f"Total Pages: {num_pages}\n")

                # Add timing breakdown if available
                if timing_info:
                    f.write("\n=== TIMING BREAKDOWN ===\n")
                    f.write(f"1. PDF Download from S3: {timing_info.get('download', 'N/A')} seconds\n")
                    f.write(f"2. PDF to Image Conversion: {timing_info.get('conversion', 'N/A')} seconds\n")
                    f.write(f"3. OCR Processing (text recognition): {timing_info.get('ocr', 'N/A')} seconds\n")
                    f.write(f"4. Table Extraction (structure analysis): {timing_info.get('extraction', 'N/A')} seconds\n")
                    f.write(f"5. Output File Generation: {timing_info.get('output_generation', 'N/A')} seconds\n")
                    f.write(f"6. S3 Upload: {timing_info.get('upload', 'N/A')} seconds\n")
                    f.write(f"\n--- SUBTOTALS ---\n")
                    f.write(f"Total Processing (OCR + Extraction): {timing_info.get('total_processing', 'N/A')} seconds\n")
                    f.write(f"Total Time (entire pipeline): {timing_info.get('total', 'N/A')} seconds\n")

                f.write("="*80 + "\n\n")

                # Write all pages' data
                for page_data in all_pages_data:
                    page_num = page_data.get('page', '?')
                    f.write(f"\n{'='*40} PAGE {page_num} {'='*40}\n\n")

                    # Write the full combined text first
                    page_text = page_data.get('text', '')
                    f.write("=== FULL TEXT ===\n")
                    f.write(page_text)
                    f.write("\n\n")

                    # Extract non-table text
                    text_blocks = page_data.get('text_blocks', [])
                    tables = page_data.get('tables', [])

                    # Get text that's in tables (to exclude from non-table text)
                    table_text = set()
                    if tables:
                        for table in tables:
                            # Parse HTML to extract text from tables
                            html = table.get('html_structure', '')
                            # Simple extraction - find text between tags
                            import re
                            table_contents = re.findall(r'>([^<]+)<', html)
                            for content in table_contents:
                                if content.strip():
                                    table_text.add(content.strip())

                    # Write non-table text
                    f.write("=== TEXT OUTSIDE TABLES ===\n")
                    non_table_text = []
                    for block in text_blocks:
                        block_text = block.get('text', '').strip()
                        if block_text and block_text not in table_text:
                            non_table_text.append(block_text)

                    if non_table_text:
                        f.write("\n".join(non_table_text))
                    else:
                        f.write("(All text is contained in tables)")
                    f.write("\n\n")

                    # Write extracted tables if any
                    if tables:
                        f.write(f"=== EXTRACTED TABLES (Page {page_num}) ===\n")
                        for i, table in enumerate(tables, 1):
                            f.write(f"\nTable {i}:\n")
                            f.write(table.get('html_structure', '<no table>'))
                            f.write("\n")
                    else:
                        f.write("=== NO TABLES DETECTED ===\n")

                f.write("\n" + "="*80 + "\n")
                f.write("=== END OF DOCUMENT ===\n")

            logger.info(f"Worker {self.worker_id}: Raw OCR output saved to {filename}")
            return filename
        except Exception as e:
            logger.warning(f"Worker {self.worker_id}: Could not save raw output file: {e}")
            return None

    def save_debug_file(self, siren, s3_key, num_pages, ocr_results):
        """Save OCR debug file with ALL pages - called ONCE after all processing"""
        if not ocr_results:
            return

        try:
            filename = f'/app/src/ocr_{siren}_all_pages.txt'
            with open(filename, 'w') as f:
                # Write header
                f.write(f"=== COMPLETE OCR RESULTS FOR ALL PAGES ===\n")
                f.write(f"PDF Source: {s3_key}\n")
                f.write(f"S3 URL: https://{Config.S3_BUCKET}.s3.{Config.S3_REGION}.amazonaws.com/{s3_key}\n")
                f.write(f"SIREN: {siren}\n")
                f.write(f"Total Pages: {num_pages}\n")
                f.write(f"Actual Pages Processed: {len(ocr_results)}\n")
                f.write("="*80 + "\n\n")

                # Write each page
                for page_num, result in ocr_results:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"=== PAGE {page_num} of {num_pages} ===\n")

                    if result and 'rec_texts' in result:
                        texts = result['rec_texts']
                        f.write(f"Text blocks detected: {len(texts)}\n")
                        f.write(f"{'='*80}\n\n")

                        # Text content
                        f.write("=== TEXT CONTENT ===\n")
                        f.write(f"Number of text blocks: {len(texts)}\n\n")
                        for i, text in enumerate(texts[:100], 1):  # Limit to first 100
                            f.write(f"{i:3d}. {text}\n")
                        if len(texts) > 100:
                            f.write(f"... and {len(texts)-100} more text blocks\n")

                        # Confidence summary
                        if 'rec_scores' in result:
                            scores = result['rec_scores']
                            if scores:
                                f.write(f"\n=== CONFIDENCE ===\n")
                                f.write(f"Average: {sum(scores)/len(scores):.4f}\n")
                                f.write(f"Min: {min(scores):.4f}, Max: {max(scores):.4f}\n")
                    else:
                        f.write("No OCR results for this page\n")

                    f.write("\n")

            logger.info(f"Worker {self.worker_id}: Debug file saved to {filename}")
        except Exception as e:
            logger.warning(f"Worker {self.worker_id}: Could not save debug file: {e}")

    def _make_json_serializable(self, obj):
        """Convert numpy arrays and other non-serializable objects to JSON-serializable format"""
        import numpy as np

        if isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, tuple):
            return [self._make_json_serializable(item) for item in obj]
        else:
            return obj

    def update_timing_in_file(self, filename, timing_info):
        """Update the timing section in an already written file"""
        try:
            # Read the existing file
            with open(filename, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Find and replace the timing section
            timing_section_start = -1
            timing_section_end = -1
            for i, line in enumerate(lines):
                if '=== TIMING BREAKDOWN ===' in line:
                    timing_section_start = i
                elif timing_section_start > -1 and '===' in line and i > timing_section_start:
                    timing_section_end = i
                    break

            if timing_section_start > -1:
                # Create new timing section
                new_timing_lines = [
                    "\n=== TIMING BREAKDOWN ===\n",
                    f"1. PDF Download from S3: {timing_info.get('download', 'N/A')} seconds\n",
                    f"2. PDF to Image Conversion: {timing_info.get('conversion', 'N/A')} seconds\n",
                    f"3. OCR Processing (text recognition): {timing_info.get('ocr', 'N/A')} seconds\n",
                    f"4. Table Extraction (structure analysis): {timing_info.get('extraction', 'N/A')} seconds\n",
                    f"5. Output File Generation: {timing_info.get('output_generation', 'N/A')} seconds\n",
                    f"6. S3 Upload: {timing_info.get('upload', 'N/A')} seconds\n",
                    f"\n--- SUBTOTALS ---\n",
                    f"Total Processing (OCR + Extraction): {timing_info.get('total_processing', 'N/A')} seconds\n",
                    f"Total Time (entire pipeline): {timing_info.get('total', 'N/A')} seconds\n",
                    "\n"
                ]

                # Replace the old timing section
                if timing_section_end > -1:
                    lines[timing_section_start:timing_section_end] = new_timing_lines
                else:
                    # If we didn't find the end, just replace from start to next section
                    lines[timing_section_start:timing_section_start+10] = new_timing_lines

                # Write back to file
                with open(filename, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
        except Exception as e:
            logger.warning(f"Could not update timing in file: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python worker_lightweight.py <worker_id>")
        sys.exit(1)

    worker_id = sys.argv[1]
    worker = LightweightOCRWorker(worker_id)

    try:
        worker.process_documents()
    except KeyboardInterrupt:
        logger.info(f"Worker {worker_id} shutting down...")
    except Exception as e:
        logger.error(f"Worker {worker_id} crashed: {e}")
        sys.exit(1)