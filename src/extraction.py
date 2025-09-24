#!/usr/bin/env python3
"""Table extraction module for OCR results"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger('TableExtractor')


class TableExtractor:
    """Extract tables from OCR text blocks using coordinate analysis"""

    def __init__(self, worker_id: str = ""):
        self.worker_id = worker_id

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
        New approach: Any row with text + numbers is a table row.
        Detect columns by clustering X positions.
        """
        if not text_blocks:
            return []

        tables_data = []

        try:
            # Step 1: Group blocks into rows by Y coordinates
            rows = self._group_into_rows(text_blocks)

            # Step 2: Find all rows that have text + numbers (financial data rows)
            table_rows = []
            for row in rows:
                if self._is_financial_row(row):
                    table_rows.append(row)

            if not table_rows:
                return []

            logger.info(f"Worker {self.worker_id}: Page {page_num} - Found {len(table_rows)} financial data rows")

            # Step 3: Detect column structure from the data
            column_boundaries = self._detect_column_boundaries(table_rows)

            # Step 4: Group table rows into logical tables (by proximity)
            tables = self._group_rows_into_tables(table_rows)

            # Step 5: Create HTML tables with proper column alignment
            for table in tables:
                html_table = self._create_aligned_html_table(table, column_boundaries)

                tables_data.append({
                    "html_structure": html_table
                })

                logger.info(f"Worker {self.worker_id}: Page {page_num} - Created table with {len(table)} rows, {len(column_boundaries)} columns")

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
        row_threshold = 20  # Slightly more tolerant than before

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
        if len(row) < 2:
            return False

        has_text = False
        has_number = False
        num_count = 0

        for block in row:
            text = block['text']
            # Check if it's a number (including French format with spaces)
            if any(char.isdigit() for char in text):
                has_number = True
                # Count if this is primarily numeric
                if sum(1 for c in text if c.isdigit() or c in '-, ') / max(len(text), 1) > 0.5:
                    num_count += 1
            # Check if it's text (not just numbers or symbols)
            elif any(char.isalpha() for char in text):
                has_text = True

        # Financial row = text + numbers OR multiple numeric columns
        return (has_text and has_number) or num_count >= 2

    def _detect_column_boundaries(self, table_rows: List[List[Dict]]) -> List[float]:
        """
        Detect column boundaries by analyzing X positions across all rows.
        Returns list of X coordinates that represent column starts.
        """
        if not table_rows:
            return []

        # Collect all unique X positions
        x_positions = []
        for row in table_rows:
            for block in row:
                x_positions.append(block['bbox'][0][0])  # Left edge X

        # Sort and cluster X positions
        x_positions = sorted(set(x_positions))

        # Group nearby X positions (within 30px tolerance)
        clusters = []
        current_cluster = [x_positions[0]]

        for x in x_positions[1:]:
            if x - current_cluster[-1] < 30:
                current_cluster.append(x)
            else:
                clusters.append(sum(current_cluster) / len(current_cluster))  # Use average
                current_cluster = [x]

        # Add last cluster
        if current_cluster:
            clusters.append(sum(current_cluster) / len(current_cluster))

        return clusters

    def _group_rows_into_tables(self, rows: List[List[Dict]]) -> List[List[List[Dict]]]:
        """
        Group rows into logical tables based on vertical proximity.
        Rows that are far apart likely belong to different tables.
        """
        if not rows:
            return []

        tables = []
        current_table = [rows[0]]
        table_gap_threshold = 50  # Rows more than 50px apart are different tables

        for i in range(1, len(rows)):
            current_row = rows[i]
            prev_row = rows[i-1]

            # Compare Y positions
            current_y = (current_row[0]['bbox'][0][1] + current_row[0]['bbox'][2][1]) / 2
            prev_y = (prev_row[0]['bbox'][0][1] + prev_row[0]['bbox'][2][1]) / 2

            if current_y - prev_y <= table_gap_threshold:
                current_table.append(current_row)
            else:
                # Start new table
                if len(current_table) >= 3:  # Only keep tables with 3+ rows
                    tables.append(current_table)
                current_table = [current_row]

        # Add last table
        if len(current_table) >= 3:
            tables.append(current_table)

        return tables

    def _create_aligned_html_table(self, table_rows: List[List[Dict]], column_boundaries: List[float]) -> str:
        """
        Create an HTML table with proper column alignment based on detected boundaries.
        """
        if not table_rows or not column_boundaries:
            return "<table></table>"

        html = ["<table border='1' style='border-collapse: collapse; width: 100%;'>"]

        for row_idx, row in enumerate(table_rows):
            # Check if this might be a header row
            is_header = row_idx == 0 and self._is_header_row(row)
            tag = "th" if is_header else "td"

            html.append("<tr>")

            # Create cells based on column boundaries
            cells = [""] * len(column_boundaries)

            for block in row:
                # Find which column this block belongs to
                block_x = block['bbox'][0][0]
                col_idx = 0

                for i, boundary in enumerate(column_boundaries):
                    if block_x >= boundary - 10:  # 10px tolerance
                        col_idx = i

                # Avoid index out of bounds
                if col_idx < len(cells):
                    if cells[col_idx]:
                        cells[col_idx] += " " + block['text']
                    else:
                        cells[col_idx] = block['text']

            # Add cells to HTML
            for cell in cells:
                style = "padding: 5px; text-align: left;"
                # Right-align numeric cells
                if cell and sum(1 for c in cell if c.isdigit()) / max(len(cell), 1) > 0.5:
                    style = "padding: 5px; text-align: right;"

                html.append(f"<{tag} style='{style}'>{cell}</{tag}>")

            html.append("</tr>")

        html.append("</table>")
        return "".join(html)

    def _is_header_row(self, row: List[Dict]) -> bool:
        """
        Determine if a row is likely a header based on content.
        Headers typically have more text and common keywords.
        """
        header_keywords = [
            'actif', 'passif', 'total', 'brut', 'amortissement',
            'net', 'exercice', 'capital', 'reserves', 'resultat',
            'charges', 'produits', 'exploitation', 'financier',
            'montant', 'date', 'libelle', 'compte'
        ]

        text_content = " ".join([block['text'].lower() for block in row])

        # Check for header keywords
        has_keyword = any(keyword in text_content for keyword in header_keywords)

        # Check if mostly text (not numbers)
        num_chars = sum(1 for c in text_content if c.isdigit())
        text_chars = sum(1 for c in text_content if c.isalpha())
        is_mostly_text = text_chars > num_chars * 2

        return has_keyword or is_mostly_text