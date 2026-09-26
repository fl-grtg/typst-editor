#!/bin/sh
# data-Dir beschreibbar machen (Bind-Mount kommt oft als root), dann als app laufen
mkdir -p "${DATA_DIR:-/app/data}"
chown -R app "${DATA_DIR:-/app/data}" 2>/dev/null || true
exec su app -s /bin/sh -c 'exec "$@"' -- "$@"
