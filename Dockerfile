FROM python:3.9-slim

# Install system dependencies (lighter than PPStructure version)
RUN apt-get update && apt-get install -y \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    wget \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python packages
# Install PaddlePaddle from official repository (same as original service)
RUN pip install --no-cache-dir paddlepaddle==3.1.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

# Install PaddleOCR with document parsing dependencies for table structure recognition
RUN pip install --no-cache-dir "paddleocr[document_parsing]==3.2.0"
RUN pip install --no-cache-dir psycopg2-binary==2.9.9 boto3==1.34.0 python-dotenv==1.0.0
RUN pip install --no-cache-dir pdf2image==1.17.0 pillow==10.3.0
RUN pip install --no-cache-dir opencv-python-headless==4.9.0.80 numpy==1.24.3
RUN pip install --no-cache-dir requests psutil==5.9.8  # Required dependencies for CPU optimization

# Install High Performance Inference dependencies for CPU optimization
RUN paddleocr install_hpi_deps cpu || echo "HPI installation failed, continuing without HPI optimization"

# Download OCR models during build to cache them (PaddleOCR 3.2.0)
RUN python -c "from paddleocr import PaddleOCR; ocr = PaddleOCR(lang='fr', enable_mkldnn=True); print('Models downloaded')"

# Copy application code
COPY src/ ./src/

# Set environment for production
ENV PYTHONUNBUFFERED=1
ENV WORKERS_PER_CONTAINER=2

CMD ["python", "-u", "src/main.py"]