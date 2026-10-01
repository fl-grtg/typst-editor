# Digest pin: check `docker buildx imagetools inspect python:3.11-slim` before release,
# Dependabot (docker ecosystem) bumps the pin automatically.
FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Only what the server really serves: backend/ + index.html + FRONT_FILES from backend/main.py
COPY backend/ ./backend/
COPY scripts/backup.py ./scripts/backup.py
COPY index.html vendor-cm.js manifest.json sw.js icon.svg icon-192.png icon-512.png screenshot.png docker-entrypoint.sh ./
ENV DATA_DIR=/app/data
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
EXPOSE 8978
RUN groupadd -r -g 999 app && useradd -r -u 999 -g 999 app && mkdir -p /app/data && chown app /app/data
RUN chmod +x ./docker-entrypoint.sh
USER 999:999
ENTRYPOINT ["sh", "./docker-entrypoint.sh"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8978')+'/healthz', timeout=4)"
# --workers 1 is required: sync.py keeps rooms in memory (rooms dict), more workers would split sessions.
# --proxy-headers: behind Caddy/nginx scheme/client IP stay correct (TRUST_PROXY, COOKIE_SECURE=auto, rate limit)
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8978} --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1,::1"]
