import os
from dataclasses import dataclass

@dataclass
class Config:
    # Database
    DB_HOST = os.getenv('DB_HOST')
    DB_PORT = int(os.getenv('DB_PORT', 5432))
    DB_NAME = os.getenv('DB_NAME')
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')

    # S3
    S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY')
    S3_SECRET_KEY = os.getenv('S3_SECRET_KEY')
    S3_REGION = os.getenv('S3_REGION', 'eu-west-1')
    S3_BUCKET = os.getenv('S3_BUCKET', 'my-invoice-files')

    # Worker
    WORKERS_PER_CONTAINER = int(os.getenv('WORKERS_PER_CONTAINER', 5))
    GPU_DEVICE = os.getenv('GPU_DEVICE', 'cpu')  # Use 'cpu' or 'gpu' (no number needed for PPStructureV3)

    # Output format
    OUTPUT_FORMAT = os.getenv('OUTPUT_FORMAT', 'clean')  # 'clean' or 'verbose'