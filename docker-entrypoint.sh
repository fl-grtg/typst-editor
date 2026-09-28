#!/bin/sh
# Make the data dir writable (bind mounts often arrive as root), then run as app.
# Compose runs as USER app already: the chown branch only applies to root starts
# (plain docker run). Token block runs in both cases (needs only a writable dir).
# Exit loudly without write access.
mkdir -p "${DATA_DIR:-/app/data}"
if [ "$(id -u)" = "0" ]; then chown app "${DATA_DIR:-/app/data}" || echo "warn: chown failed" >&2; fi # no -R: slow on large volumes
touch "${DATA_DIR:-/app/data}/.writetest" 2>/dev/null || {
  echo "top-level not writable, trying recursive chown (root-owned subdirs)" >&2
  if [ "$(id -u)" = "0" ]; then chown -R app "${DATA_DIR:-/app/data}" || echo "warn: chown -R failed" >&2; fi
  touch "${DATA_DIR:-/app/data}/.writetest" 2>/dev/null || { echo "data dir not writable (uid $(id -u)). Fix: unset COMPOSE_DATA_PATH to use the managed volume, or host-side: mkdir -p data && chown -R 999:999 data" >&2; exit 1; }
}
rm -f "${DATA_DIR:-/app/data}/.writetest"
if [ -z "${REGISTRATION_INVITE_TOKEN:-}" ] && [ ! -f "${DATA_DIR:-/app/data}/app.db" ]; then
  _tok_file="${DATA_DIR:-/app/data}/.invite_token"
  if [ -f "$_tok_file" ]; then
    REGISTRATION_INVITE_TOKEN="$(cat "$_tok_file")"
  else
    REGISTRATION_INVITE_TOKEN="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
    printf '%s' "$REGISTRATION_INVITE_TOKEN" > "$_tok_file"
    chmod 600 "$_tok_file"
    # Logged only when generated (first start on a fresh DATA_DIR). Rotation: stop, delete DATA_DIR/.invite_token (and unset REGISTRATION_INVITE_TOKEN), start.
    echo "fresh install: generated REGISTRATION_INVITE_TOKEN, invite code: $REGISTRATION_INVITE_TOKEN" >&2
  fi
  export REGISTRATION_INVITE_TOKEN
fi
if [ "$(id -u)" = "0" ] && command -v setpriv >/dev/null 2>&1; then exec setpriv --reuid app --regid app --clear-groups "$@"; fi
if [ "$(id -u)" = "0" ]; then echo "refusing to run as root (no setpriv)" >&2; exit 1; fi
exec "$@"
