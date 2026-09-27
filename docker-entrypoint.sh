#!/bin/sh
# Make the data dir writable (bind mounts often arrive as root), then run as app.
# Runs as USER app: the chown branch only applies to root starts. Exit loudly without write access.
mkdir -p "${DATA_DIR:-/app/data}"
if [ "$(id -u)" = "0" ]; then chown app "${DATA_DIR:-/app/data}" || echo "warn: chown failed" >&2; fi # no -R: slow on large volumes
touch "${DATA_DIR:-/app/data}/.writetest" 2>/dev/null || { echo "data dir not writable, fix with: mkdir -p data; chown -R 999:999 data" >&2; exit 1; }
rm -f "${DATA_DIR:-/app/data}/.writetest"
if [ "$(id -u)" = "0" ] && command -v setpriv >/dev/null 2>&1; then exec setpriv --reuid app --regid app --clear-groups "$@"; fi
if [ "$(id -u)" = "0" ]; then echo "refusing to run as root (no setpriv)" >&2; exit 1; fi
exec "$@"
