#!/usr/bin/env python3
"""Table extraction module for OCR results"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger('TableExtractor')


class TableExtractor:
    """Extract tables from OCR text blocks using coordinate analysis"""

    def __init__(self, worker_id: str = ""):
        self.worker_id = worker_id

    def _find_matching_header(self, header_rows: List[List[Dict]], table: List[List[Dict]],
                             column_boundaries: List[float], all_rows: List[List[Dict]]) -> List[Dict]:
        """
        Find a header row that matches the column structure of the given table.
        Headers should appear before the table (lower Y coordinate) and have similar column alignment.
        If no explicit header is found, create one from aligned text above columns.
        """
        if not table:
            return None

        # Get Y position of first table row
        table_y = (table[0][0]['bbox'][0][1] + table[0][0]['bbox'][2][1]) / 2 if table[0] else float('inf')

        best_header = None
        best_score = 0

        # First try to find explicit header rows
        for header in header_rows:
            if not header:
                continue

            # Header should be above the table
            header_y = (header[0]['bbox'][0][1] + header[0]['bbox'][2][1]) / 2
            if header_y >= table_y:
                continue

            # Check if header aligns with column boundaries
            alignment_score = 0
            for block in header:
                block_x = block['bbox'][0][0]
                # Check if block aligns with any column boundary
                for boundary in column_boundaries:
                    if abs(block_x - boundary) < 40:  # 40px tolerance for alignment
                        alignment_score += 1
                        break

            # Normalize score by number of blocks
            if len(header) > 0:
                alignment_score = alignment_score / len(header)

            # Also consider proximity (closer headers are better)
            proximity_bonus = 1.0 / (1 + (table_y - header_y) / 100)  # Decay with distance

            total_score = alignment_score * proximity_bonus

            if total_score > best_score:
                best_score = total_score
                best_header = header

        # If we found a good header, return it
        if best_header and best_score > 0.3:
            return best_header

        # Otherwise, try to construct a header from text/dates aligned with columns
        constructed_header = self._construct_header_from_aligned_text(
            all_rows, table, column_boundaries, table_y
        )

        return constructed_header

    def _construct_header_from_aligned_text(self, all_rows: List[List[Dict]], table: List[List[Dict]],
                                           column_boundaries: List[float], table_y: float) -> List[Dict]:
        """
        Construct a header row from text/dates that align with column positions.
        Look for text or date patterns above the table that align with columns.
        """
        import re

        # Date patterns to look for
        date_patterns = [
            r'\d{1,2}/\d{1,2}/\d{4}',  # DD/MM/YYYY or MM/DD/YYYY
            r'\d{1,2}/\d{1,2}/\d{2}',   # DD/MM/YY
            r'\d{1,2}/\d{4}',            # MM/YYYY
            r'\d{1,2}-\d{1,2}-\d{4}',   # DD-MM-YYYY
            r'\d{1,2}-\d{1,2}-\d{2}',    # DD-MM-YY
            r'\d{4}',                    # YYYY (year only)
            r'exercice\s+n(?:-\d)?',    # Exercice N, Exercice N-1
            r'n-\d',                     # N-1, N-2 etc
        ]

        # Common header keywords
        header_keywords = ['brut', 'net', 'amortissement', 'depreciation', 'total', 'montant']

        header_blocks = []

        # Look through rows above the table
        for row in all_rows:
            if not row:
                continue

            row_y = (row[0]['bbox'][0][1] + row[0]['bbox'][2][1]) / 2

            # Skip if row is below or part of the table
            if row_y >= table_y:
                continue

            # Skip if too far above (more than 200px)
            if table_y - row_y > 200:
                continue

            # Check each block in the row
            for block in row:
                text = block['text'].strip().lower()
                block_x = block['bbox'][0][0]

                # Check if this text is a date, year, or header keyword
                is_header_text = False

                # Check date patterns
                for pattern in date_patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        is_header_text = True
                        break

                # Check keywords
                if not is_header_text:
                    for keyword in header_keywords:
                        if keyword in text:
                            is_header_text = True
                            break

                # Check if it aligns with a column
                if is_header_text:
                    for boundary in column_boundaries:
                        if abs(block_x - boundary) < 50:  # 50px tolerance
                            # Check if we already have text for this column
                            existing = False
                            for hb in header_blocks:
                                if abs(hb['bbox'][0][0] - block_x) < 30:
                                    existing = True
                                    break

                            if not existing:
                                header_blocks.append(block)
                            break

        # Return constructed header if we found aligned text/dates
        return header_blocks if len(header_blocks) >= 2 else None

    def extract_tables_from_page(self, text_blocks: List[Dict], page_num: int) -> List[Dict]:
        """
        Extract tables from text blocks for a single page.
        Returns list of detected tables with HTML structure.
        """
        if not text_blocks:
            return []

        return self._detect_tables_from_coordinates(text_blocks, page_num)

    def _detect_tables_from_coordinates(self, text_blocks: List[Dict], page_num: int) -> List[Dict]:
        """
        Detect tables by analyzing text block coordinates.
        Identifies headers and data rows, then merges them into complete tables.
        """
        if not text_blocks:
            return []

        tables_data = []

        try:
            # Step 1: Group blocks into rows by Y coordinates
            rows = self._group_into_rows(text_blocks)

            # Step 2: Identify potential header rows and data rows
            header_rows = []
            data_rows = []

            for row in rows:
                if self._is_header_row(row):
                    header_rows.append(row)
                elif self._is_financial_row(row):
                    data_rows.append(row)

            if not data_rows:
                return []

            logger.info(f"Worker {self.worker_id}: Page {page_num} - Found {len(header_rows)} headers, {len(data_rows)} data rows")

            # Step 3: Group data rows into logical tables
            data_tables = self._group_rows_into_tables(data_rows)

            # Step 4: Match headers with tables and create HTML
            for table in data_tables:
                # Detect column structure from this table
                column_boundaries = self._detect_column_boundaries(table)

                # Find matching header for this table (pass all rows for header construction)
                matched_header = self._find_matching_header(header_rows, table, column_boundaries, rows)

                # Combine header with table if found
                if matched_header:
                    complete_table = [matched_header] + table
                else:
                    complete_table = table

                # Create HTML table
                html_table = self._create_aligned_html_table(complete_table, column_boundaries)

                tables_data.append({
                    "html_structure": html_table
                })

                logger.info(f"Worker {self.worker_id}: Page {page_num} - Created table with {len(complete_table)} rows, {len(column_boundaries)} columns")

        except Exception as e:
            logger.warning(f"Worker {self.worker_id}: Page {page_num} - Table detection error: {e}")

        return tables_data

    def _group_into_rows(self, text_blocks: List[Dict]) -> List[List[Dict]]:
        """Group text blocks into rows based on Y coordinates."""
        if not text_blocks:
            return []

        # Sort by Y coordinate
        sorted_blocks = sorted(text_blocks, key=lambda b: (b['bbox'][0][1] + b['bbox'][2][1]) / 2)

        rows = []
        current_row = [sorted_blocks[0]]
        row_threshold = 10  # Tighter threshold to avoid merging different rows

        for block in sorted_blocks[1:]:
            current_y = (block['bbox'][0][1] + block['bbox'][2][1]) / 2
            prev_y = (current_row[-1]['bbox'][0][1] + current_row[-1]['bbox'][2][1]) / 2

            if abs(current_y - prev_y) <= row_threshold:
                current_row.append(block)
            else:
                # Sort row by X coordinate before adding
                rows.append(sorted(current_row, key=lambda b: b['bbox'][0][0]))
                current_row = [block]

        # Add last row
        if current_row:
            rows.append(sorted(current_row, key=lambda b: b['bbox'][0][0]))

        return rows

    def _is_financial_row(self, row: List[Dict]) -> bool:
        """Check if a row contains financial data (text + numbers or multiple numbers)."""
        if len(row) < 1:  # Allow single-block rows if they're part of a table
            return False

        has_text = False
        has_number = False
        num_count = 0
        total_blocks = len(row)

        for block in row:
            text = block['text']
            # Check if it's a number (including French format with spaces)
            if any(char.isdigit() for char in text):
                has_number = True
                # Count if this is primarily numeric
                clean_text = text.replace(' ', '').replace(',', '')
                if sum(1 for c in clean_text if c.isdigit() or c in '-.') / max(len(clean_text), 1) > 0.5:
                    num_count += 1
            # Check if it's text (not just numbers or symbols)
            elif any(char.isalpha() for char in text) and len(text) > 2:
                has_text = True

        # Financial row = has meaningful content and structure
        # More permissive: any row with text or numbers that's part of table structure
        return (has_text or has_number) and total_blocks >= 1

    def _detect_column_boundaries(self, table_rows: List[List[Dict]]) -> List[float]:
        """
        Detect column boundaries by analyzing X positions across all rows.
        Returns list of X coordinates that represent column starts.
        """
        if not table_rows:
            return []

        # Find the leftmost position across all rows (for row labels)
        min_x = float('inf')
        for row in table_rows:
            for block in row:
                min_x = min(min_x, block['bbox'][0][0])

        # Collect all unique X positions with their frequency
        x_position_counts = {}
        for row in table_rows:
            for block in row:
                x = block['bbox'][0][0]  # Left edge X
                # Round to nearest 10px to group similar positions
                x_rounded = round(x / 10) * 10
                x_position_counts[x_rounded] = x_position_counts.get(x_rounded, 0) + 1

        # Sort X positions
        x_positions = sorted(x_position_counts.keys())

        if not x_positions:
            return []

        # Always include the leftmost position as first column
        # This ensures row labels are captured
        leftmost = round(min_x / 10) * 10

        # Adaptive clustering - detect natural gaps in X positions
        clusters = [leftmost]  # Start with leftmost position

        # Calculate gaps between consecutive X positions to find natural column boundaries
        gaps = []
        for i in range(1, len(x_positions)):
            gap = x_positions[i] - x_positions[i-1]
            if gap > 20:  # Ignore tiny gaps
                gaps.append(gap)

        # Determine clustering threshold based on gap distribution
        if gaps:
            avg_gap = sum(gaps) / len(gaps)
            # Use a threshold that's 60% of average gap, min 50px, max 200px
            cluster_threshold = max(50, min(200, int(avg_gap * 0.6)))
        else:
            cluster_threshold = 50  # Default

        logger.debug(f"Worker {self.worker_id}: Using cluster threshold {cluster_threshold}px based on gap analysis")

        current_cluster = []
        for x in x_positions:
            # Skip if too close to leftmost (already included)
            if abs(x - leftmost) < cluster_threshold:
                continue

            if not current_cluster or x - current_cluster[-1] < cluster_threshold:
                current_cluster.append(x)
            else:
                # Use the most frequent position in cluster
                if current_cluster:
                    cluster_representative = min(current_cluster,
                        key=lambda p: -x_position_counts.get(p, 0))
                    clusters.append(cluster_representative)
                current_cluster = [x]

        # Add last cluster
        if current_cluster:
            cluster_representative = min(current_cluster,
                key=lambda p: -x_position_counts.get(p, 0))
            clusters.append(cluster_representative)

        # Ensure clusters are unique and sorted
        clusters = sorted(set(clusters))

        # Limit to reasonable number of columns for financial tables
        if len(clusters) > 8:  # Most financial tables have <= 8 columns
            # Keep first column (labels) and most significant others
            first_col = clusters[0]
            other_cols = clusters[1:]

            # Sort other columns by frequency
            cols_with_freq = [(c, sum(x_position_counts.get(p, 0)
                for p in x_position_counts if abs(p - c) < cluster_threshold))
                for c in other_cols]
            cols_with_freq.sort(key=lambda x: -x[1])

            # Keep first column and top 7 others
            clusters = [first_col] + sorted([c for c, _ in cols_with_freq[:7]])

        return clusters

    def _group_rows_into_tables(self, rows: List[List[Dict]]) -> List[List[List[Dict]]]:
        """
        Group rows into logical tables based on vertical proximity AND column consistency.
        Rows that are far apart or have different column structures likely belong to different tables.
        """
        if not rows:
            return []

        tables = []
        current_table = [rows[0]]
        table_gap_threshold = 60  # Increased to 60px - more tolerant of spacing

        for i in range(1, len(rows)):
            current_row = rows[i]
            prev_row = rows[i-1]

            # Compare Y positions
            current_y = (current_row[0]['bbox'][0][1] + current_row[0]['bbox'][2][1]) / 2
            prev_y = (prev_row[0]['bbox'][0][1] + prev_row[0]['bbox'][2][1]) / 2

            # Check if rows have similar column structure (similar number of blocks)
            similar_structure = abs(len(current_row) - len(prev_row)) <= 2

            if current_y - prev_y <= table_gap_threshold and similar_structure:
                current_table.append(current_row)
            else:
                # Start new table
                if len(current_table) >= 3:  # Require at least 3 rows for a valid table
                    # Validate it's actually a table (has some multi-column rows)
                    if self._validate_table_structure(current_table):
                        tables.append(current_table)
                current_table = [current_row]

        # Add last table
        if len(current_table) >= 3 and self._validate_table_structure(current_table):
            tables.append(current_table)

        return tables

    def _validate_table_structure(self, table_rows: List[List[Dict]]) -> bool:
        """
        Validate that rows actually form a table structure.
        A valid table should have:
        - At least some rows with multiple columns OR
        - Numeric content indicating financial data
        """
        # Count rows with multiple blocks
        multi_column_rows = sum(1 for row in table_rows if len(row) >= 2)

        # More lenient: at least 20% of rows should have multiple columns
        # This allows for financial statements where many rows are just labels
        if multi_column_rows < len(table_rows) * 0.2:
            # But if it has strong numeric content, still accept it
            num_rows_with_numbers = 0
            for row in table_rows:
                for block in row:
                    if any(c.isdigit() for c in block['text']):
                        num_rows_with_numbers += 1
                        break

            # If at least 30% of rows have numbers, it's likely a financial table
            if num_rows_with_numbers < len(table_rows) * 0.3:
                return False

        return True

    def _create_aligned_html_table(self, table_rows: List[List[Dict]], column_boundaries: List[float]) -> str:
        """
        Create an HTML table with proper column alignment based on detected boundaries.
        First row is header if it contains header-like content.
        """
        if not table_rows or not column_boundaries:
            return "<table></table>"

        html = ["<table>"]

        for row_idx, row in enumerate(table_rows):
            # First row is header if it looks like a header
            is_header = row_idx == 0 and self._is_header_row(row)
            tag = "th" if is_header else "td"

            html.append("<tr>")

            # Create cells based on column boundaries
            cells = [""] * len(column_boundaries)

            # Sort blocks by X position for proper column assignment
            sorted_blocks = sorted(row, key=lambda b: b['bbox'][0][0])

            for block in sorted_blocks:
                # Find which column this block belongs to
                block_x = block['bbox'][0][0]
                col_idx = 0  # Default to first column

                # Find the closest column boundary
                min_distance = float('inf')
                for i, boundary in enumerate(column_boundaries):
                    distance = abs(block_x - boundary)
                    if distance < min_distance:
                        min_distance = distance
                        col_idx = i

                # Ensure we don't go out of bounds
                col_idx = min(col_idx, len(cells) - 1)

                # Add text to the appropriate cell
                if cells[col_idx]:
                    cells[col_idx] += " " + block['text']
                else:
                    cells[col_idx] = block['text']

            # Add cells to HTML without any styling
            for cell in cells:
                html.append(f"<{tag}>{cell}</{tag}>")

            html.append("</tr>")

        html.append("</table>")
        return "".join(html)

    def _is_header_row(self, row: List[Dict]) -> bool:
        """
        Determine if a row is likely a header based on content.
        Headers typically have more text and common keywords.
        """
        header_keywords = [
            'actif', 'passif', 'total', 'brut', 'amortissement', 'amort',
            'net', 'exercice', 'capital', 'reserves', 'resultat',
            'charges', 'produits', 'exploitation', 'financier',
            'montant', 'date', 'libelle', 'compte', 'deprec',
            'n-1', 'n+1', '2023', '2022', '2024', '2021'
        ]

        text_content = " ".join([block['text'].lower() for block in row])

        # Check for year patterns (common in headers)
        import re
        has_year = bool(re.search(r'\b(19|20)\d{2}\b', text_content))

        # Check for date patterns like 31/12/2023
        has_date = bool(re.search(r'\d{1,2}/\d{1,2}/\d{4}', text_content))

        # Check for header keywords
        has_keyword = any(keyword in text_content for keyword in header_keywords)

        # Check if mostly text (not numbers) - but dates are OK
        # Remove dates and years before counting
        clean_text = re.sub(r'\d{1,2}/\d{1,2}/\d{4}', '', text_content)
        clean_text = re.sub(r'\b(19|20)\d{2}\b', '', clean_text)

        num_chars = sum(1 for c in clean_text if c.isdigit())
        text_chars = sum(1 for c in clean_text if c.isalpha())
        is_mostly_text = text_chars > num_chars * 1.5  # Slightly less strict

        # Row is header if it has keywords, dates/years, or is mostly text
        return (has_keyword or has_year or has_date) and (is_mostly_text or len(row) <= 4)