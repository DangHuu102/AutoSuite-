FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OFFICEFLOW_ALLOWED_HOSTS="*"

# Cài đặt LibreOffice và Tesseract OCR (Tiếng Việt + Tiếng Anh) trên Server Linux
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    tesseract-ocr \
    tesseract-ocr-vie \
    tesseract-ocr-eng \
    tesseract-ocr-osd \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/api/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "officeflow.webapp:app", \
     "--host", "0.0.0.0", \
     "--port", "8501", \
     "--workers", "1", \
     "--timeout-keep-alive", "5", \
     "--timeout-graceful-shutdown", "10", \
     "--limit-concurrency", "32", \
     "--no-access-log"]
