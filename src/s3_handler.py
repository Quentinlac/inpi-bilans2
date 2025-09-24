#!/usr/bin/env python3
"""S3 Handler for OCR service"""

import os
import json
import logging
import tempfile
import boto3
from botocore.exceptions import ClientError
from src.config import Config

logger = logging.getLogger('S3Handler')

class S3Handler:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=Config.S3_ACCESS_KEY,
            aws_secret_access_key=Config.S3_SECRET_KEY,
            region_name=Config.S3_REGION
        )
        self.bucket = Config.S3_BUCKET

    def download_pdf(self, s3_key):
        """Download PDF from S3 to temporary file"""
        try:
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            temp_path = temp_file.name
            temp_file.close()

            # Download from S3
            logger.info(f"Downloading {s3_key} from S3...")
            self.s3_client.download_file(self.bucket, s3_key, temp_path)
            logger.info(f"Downloaded {s3_key} successfully")

            return temp_path

        except ClientError as e:
            logger.error(f"Failed to download {s3_key}: {e}")
            raise

    def upload_json(self, json_data, output_key):
        """Upload JSON data to S3"""
        try:
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=output_key,
                Body=json_data,
                ContentType='application/json'
            )

            logger.info(f"Uploaded to {output_key}")
            return True

        except ClientError as e:
            logger.error(f"Failed to upload {output_key}: {e}")
            return False

    def upload_text(self, text_data, output_key):
        """Upload text file to S3"""
        try:
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=output_key,
                Body=text_data,
                ContentType='text/plain; charset=utf-8'
            )

            logger.info(f"Uploaded text file to {output_key}")
            return True

        except ClientError as e:
            logger.error(f"Failed to upload text file {output_key}: {e}")
            return False