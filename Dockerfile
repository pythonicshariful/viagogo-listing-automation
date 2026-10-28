# Viagogo Listing Automation — production image
# Build:  docker build -t viagogo-listing .
# Run:    docker compose up -d   (see docker-compose.yml)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DRY_RUN=True \
    LIVE_MODE=False \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5002

WORKDIR /app

# Playwright Chromium needs system libs even in slim images.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && python -m playwright install chromium --with-deps || python -m playwright install chromium

COPY . .

RUN useradd -m appuser && mkdir -p data logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5002
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5002/api/health', timeout=4).status==200 else 1)"

CMD ["python", "app.py"]
