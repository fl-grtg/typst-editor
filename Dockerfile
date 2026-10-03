# Digest pin: check `docker buildx imagetools inspect python:3.11-slim` before release,
# Dependabot (docker ecosystem) bumps the pin automatically.
FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Only what the server really serves: backend/ + index.html + FRONT_FILES from backend/main.py
COPY backend/ ./backend/
COPY scripts/backup.py ./scripts/backup.py
COPY index.html vendor-cm.js manifest.json icon.svg icon-192.png icon-512.png docker-entrypoint.sh ./
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
# FORWARDED_ALLOW_IPS (default loopback) must cover the proxy IP, else X-Forwarded-For/Proto is ignored
# (e.g. FORWARDED_ALLOW_IPS=172.16.0.0/12 behind compose/Caddy on a bridge network).
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8978} --workers 1 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1,::1}\""]
