FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Nur was der Server wirklich serviert: backend/ + index.html + FRONT_FILES aus backend/main.py
COPY backend/ ./backend/
COPY index.html vendor-cm.js manifest.json sw.js icon.svg icon-192.png icon-512.png docker-entrypoint.sh ./
ENV DATA_DIR=/app/data
EXPOSE 8978
RUN useradd -r app && chown -R app /app
RUN chmod +x ./docker-entrypoint.sh
ENTRYPOINT ["sh", "./docker-entrypoint.sh"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8978')+'/healthz')"
# --workers 1 ist Pflicht: sync.py haelt Rooms in-memory (rooms-Dict), mehrere Worker wuerden Sessions spalten.
# --proxy-headers: hinter Caddy/nginx stimmen scheme/client-IP (TRUST_PROXY, COOKIE_SECURE=auto, Rate-Limit)
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8978} --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1,::1"]
