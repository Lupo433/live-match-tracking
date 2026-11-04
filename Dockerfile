# Live Match Tracking - demo image (bundled 2-minute Metrica sample + synthetic match).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    LIVEMATCH_DATA_DIR=/app/data \
    LIVEMATCH_CACHE_DIR=/tmp/livematch-cache

WORKDIR /app

# install dependencies first for better layer caching
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install . && rm -rf /root/.cache

# only the small committed sample: full Metrica games are not baked into the image
COPY data/sample ./data/sample

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)" || exit 1

CMD ["python", "-m", "livematch"]
