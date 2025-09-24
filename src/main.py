import logging
import multiprocessing
import signal
import sys
import os
import socket
from worker_lightweight import LightweightOCRWorker
from config import Config

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Enable debug logs to see OCR structure issues
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)

# Reduce PaddleOCR logging noise
logging.getLogger('ppocr').setLevel(logging.WARNING)
logging.getLogger('paddle').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)
logging.getLogger('botocore').setLevel(logging.WARNING)
logging.getLogger('s3transfer').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

def run_worker(worker_id):
    """Run a single lightweight OCR worker process"""
    # Generate worker ID
    hostname = socket.gethostname()

    if os.environ.get('ACI_NAME'):
        # Running in Azure Container Instance
        actual_worker_id = f"{os.environ.get('ACI_NAME')}-{worker_id}"
    else:
        # Local Docker or testing
        actual_worker_id = f"{hostname}-lightweight-{worker_id}"

    logging.info(f"Starting lightweight worker: {actual_worker_id}")
    worker = LightweightOCRWorker(actual_worker_id)
    worker.process_documents()

def signal_handler(sig, frame):
    """Handle shutdown signals gracefully"""
    logging.info('Shutting down lightweight OCR workers...')
    sys.exit(0)

def main():
    """Main entry point for lightweight OCR service"""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Get worker configuration
    num_workers = Config.WORKERS_PER_CONTAINER
    logging.info(f"Starting {num_workers} lightweight OCR workers...")
    logging.info("Configuration:")
    logging.info(f"  - OCR Engine: PaddleOCR 3.2.0")
    logging.info(f"  - Processing Mode: Lightweight (no PPStructure)")
    logging.info(f"  - Workers per container: {num_workers}")
    logging.info(f"  - CPU threads per worker: 4")
    logging.info(f"  - Memory limit per worker: ~2GB")

    # Start worker processes
    processes = []
    for i in range(num_workers):
        p = multiprocessing.Process(
            target=run_worker,
            args=(i,),
            name=f"OCRWorker-{i}"
        )
        p.start()
        processes.append(p)
        logging.info(f"Started worker process {i} (PID: {p.pid})")

    # Monitor worker processes
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        logging.info("Received interrupt, shutting down...")
        for p in processes:
            p.terminate()
            p.join(timeout=5)

    logging.info("All workers shut down successfully")

if __name__ == "__main__":
    main()