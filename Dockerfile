FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY package*.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig.json ./
COPY src/ ./src/
COPY public/ ./public/
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INVOICE_DATA_DIR=/app/data \
    INVOICE_WORKERS=4

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend/ ./backend/
COPY --from=frontend-build /build/dist ./frontend/dist

RUN useradd --create-home --uid 10001 invoice \
    && mkdir -p /app/data/sources /app/data/exports \
    && chown -R invoice:invoice /app
USER invoice

ENV OMP_THREAD_LIMIT=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3))['status'] == 'ok'"

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
