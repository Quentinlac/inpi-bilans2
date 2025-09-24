import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from datetime import datetime
from config import Config

class DatabaseHandler:
    def __init__(self):
        self.conn = None
        self.connect()

    def connect(self):
        self.conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        self.conn.autocommit = False

    def get_next_document(self, worker_id):
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, siren, s3_key
                    FROM download_status
                    WHERE download_status = 'success'
                    AND (ocr_status = 'pending' OR ocr_status IS NULL)
                    AND s3_key IS NOT NULL
                    AND LENGTH(s3_key) > 0
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                """)
                doc = cur.fetchone()

                if doc:
                    cur.execute("""
                        UPDATE download_status
                        SET ocr_status = 'processing',
                            ocr_worker_id = %s,
                            ocr_started_at = NOW()
                        WHERE id = %s
                    """, (worker_id, doc['id']))
                    self.conn.commit()

                return doc
        except Exception as e:
            self.conn.rollback()
            logging.error(f"Database error: {e}")
            return None

    def mark_completed(self, doc_id, text_s3_url, json_s3_url, processing_time_ms, num_pages, text_length):
        """Mark completed with text file in ocr_s3_path and JSON in ocr_text_file_path"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE download_status
                    SET ocr_status = 'completed',
                        ocr_completed_at = NOW(),
                        ocr_processing_time_ms = %s,
                        ocr_s3_path = %s,
                        ocr_text_file_path = %s,
                        ocr_text_length = %s,
                        ocr_engine = 'PaddleOCR-v2'
                    WHERE id = %s
                """, (processing_time_ms, text_s3_url, json_s3_url, text_length, doc_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            import traceback
            logging.error(f"Database update error for doc_id {doc_id}: {e}")
            logging.error(f"Full traceback: {traceback.format_exc()}")
            raise

    # REMOVED - Using single mark_completed method that stores JSON in ocr_text_file_path

    def mark_failed(self, doc_id, error_message):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE download_status
                    SET ocr_status = 'failed',
                        ocr_completed_at = NOW(),
                        ocr_processing_time_ms = EXTRACT(EPOCH FROM (NOW() - ocr_started_at)) * 1000,
                        ocr_error = %s
                    WHERE id = %s
                """, (error_message[:500], doc_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            import traceback
            logging.error(f"Database error marking failed for doc_id {doc_id}: {e}")
            logging.error(f"Full traceback: {traceback.format_exc()}")