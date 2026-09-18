# Podman / Docker compatible. Build from repo root:  podman build -f Containerfile -t ipmat-stage .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IPMAT_HOST=0.0.0.0 \
    IPMAT_PORT=5057

WORKDIR /app

# Deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + content (data/ and secrets excluded via .dockerignore)
COPY app/ ./app/
COPY bank/ ./bank/
COPY blueprints/ ./blueprints/
COPY config/ ./config/
COPY papers/ ./papers/
COPY prompts/ ./prompts/
COPY public/ ./public/
COPY schemas/ ./schemas/
COPY scripts/ ./scripts/
COPY sections/ ./sections/

# Runtime state dir (students.json lives here; mount a volume over it)
RUN mkdir -p data && \
    useradd -r -m -d /home/appuser -s /usr/sbin/nologin appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 5057
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5057/api/health', timeout=5)"

CMD ["python", "app/server.py"]
