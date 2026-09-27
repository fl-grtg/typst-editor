# 📝 Typst Editor

[![ci](https://github.com/fl-grtg/typst-editor/actions/workflows/ci.yml/badge.svg)](https://github.com/fl-grtg/typst-editor/actions/workflows/ci.yml) [![docker](https://github.com/fl-grtg/typst-editor/actions/workflows/docker.yml/badge.svg)](https://github.com/fl-grtg/typst-editor/actions/workflows/docker.yml) [![license](https://img.shields.io/github/license/fl-grtg/typst-editor)](./LICENSE)

Collaborative Typst editor in the browser: code on the left, live PDF on the right.

One process, clean API, boring on purpose. FastAPI serves the API, Yjs syncs the edits, and SQLite stores everything. No Node needed at runtime.

<img width="1280" height="688" alt="editor" src="./screenshot.png" />

## ✨ Features

- Live PDF preview, compiled in the browser via Typst WASM
- Realtime collaboration with presence over a cookie-only WebSocket
- Owner/editor/reviewer roles with share links and doc invites
- Comment threads with anchors, @-mentions, replies, resolve
- Outline, symbol picker, autocomplete, find/replace
- File uploads for `#image` and `#include` (10 MB per file, 200 per doc)
- Templates per account with folders, reused via `#include`
- History with snapshots, diff view, one-click restore
- Folders, trash, duplicate, global search
- Export as `.typ`, PDF, SVG, first-page PNG, or all docs as one `.zip`
- Autosave + 24 h local stash, offline app shell, font/zoom settings
- Per-user quotas and per-endpoint rate limits, enforced server-side

## 🚀 Get Started

With Docker (under 5 minutes):

```bash
cp .env.example .env
mkdir -p data # Linux: chown 999:999 data
docker compose pull && docker compose up -d
```
Lokal bauen statt ziehen: `docker compose up --build`.

Open `http://127.0.0.1:8978` and create the first account (no invite needed).

Or locally with Python 3.11:

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows (source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8978 --workers 1
```

Registration defaults to `invite-only`. The first account registers freely (bootstrap) unless `REGISTRATION_INVITE_TOKEN` is already set — then even the first account needs it. Set the token before first start on public servers (`openssl rand -hex 32`). Use `open` for local tests only, never on the public internet.

## ⚙️ Configuration

File plus env overrides; env wins. Full list with defaults in `.env.example` (or `config.example.toml`); parsed and validated in `backend/config.py`.

| ENV | Default | Notes |
| --- | --- | --- |
| `DATA_DIR` | `./data` | SQLite plus uploads; `/app/data` in the container. Needs restart when changed. |
| `COMPOSE_DATA_PATH` | `./data` | Compose-only host path, e.g. `/srv/typst-data`. |
| `TRUST_PROXY` | `false` | Required `true` behind a proxy, else cookies break. Set only in `.env`. |
| `REGISTRATION` | `invite-only` | `closed`, `invite-only`, or `open`. |
| `REGISTRATION_INVITE_TOKEN` | empty | `openssl rand -hex 32`. |
| `SESSION_SECONDS` | `1209600` | 14 days. |
| `MAX_DOCS_PER_USER` | `100` | Plus 500 MB and 200 files per doc (see `backend/constants.py`). |

Never commit local `config.toml` or `.env`; only the `.example` files are tracked.

## 📡 API

```bash
curl -s http://127.0.0.1:8978/healthz
```

Live sync runs over `WS /ws/{doc_id}`. Auth is cookie-only (`typst_session`, HttpOnly, SameSite=lax): API clients must store cookies, there is no token in body or URL.

## 💾 Backup

```bash
python scripts/backup.py --include-files
```

Writes `DATA_DIR/backup/app-YYYYMMDD-HHMMSS.db` via `VACUUM INTO` plus a `files/` archive, keeps the newest 7 (`--keep N`, `--dry-run`). Run hourly via cron or `docker compose exec app python scripts/backup.py --include-files`. Backups are unencrypted: `gpg -c DATA_DIR/backup/app-*.db`.

Restore: stop the server, copy the backup over `app.db`, delete `app.db-wal`/`app.db-shm`, unpack files, start. Verify with `PRAGMA integrity_check;`.

## 🔌 Reverse proxy

`TRUST_PROXY=true` is required; never expose the app directly, TLS is your responsibility. Caddy:

```
typst.example.com {
    reverse_proxy 127.0.0.1:8978
}
```

nginx needs the same headers (`Host`, `Upgrade`, `X-Forwarded-Proto`, overwrite `X-Forwarded-For`, `proxy_read_timeout 86400`, `proxy_buffering off`, `client_max_body_size 12M`).

Always one worker (`--workers 1`) and one replica: rooms live in process memory. 512 MB RAM minimum, 1 GB recommended. No public demo instance; self-host.

Limits, openly: docs 200 KB each; uploads 10 MB per file; 50 snapshots per doc, auto at most every 15 min; doc invites valid 7 days, shown once; search needs 2 chars, max 20 hits; quotas 100 docs and 500 MB per user, 200 files per doc; reads share the `files_list` bucket (120/min), writes have their own.

### 🔒 Security Contact

Report vulnerabilities via GitHub Private Vulnerability Reporting.
Do not open public issues for security problems.
Allow time for a fix before any disclosure.

Unshare wipes all pending invite links for the doc (they carry no username). Preview needs internet on first load (CDN: cdnjs/esm.sh/jsdelivr); afterwards the shell works offline, saving needs network (24 h local stash). CSP allows `unsafe-inline`/`unsafe-eval`/`wasm-unsafe-eval` plus pinned CDN origins — Typst WASM cannot run without them; user content is rendered via `textContent` only.

### 🛠 Troubleshooting

- First load needs internet (CDN), then shell offline. Check `#cdnLine` / console.
- Single worker only (`--workers 1`, also as CLI flag). Multi-worker exits on purpose.
- Behind proxy set `TRUST_PROXY=true`, overwrite `X-Forwarded-For`, never append.
- Port `8978` loopback-only; TLS via proxy.
- Root-owned volume: `chown -R 999:999 data`.
- `429` on reads: the shared `files_list` bucket (120/min) — slow down polling.

### 📦 Changelog

See GitHub Releases (no CHANGELOG file, single README on purpose).

## 💡 Why

Most collaborative editors either need heavy infrastructure or lock you into a cloud. This sits in the middle: one container you can self-host, enough collaboration to work together, little enough surface area to understand in one sitting.

If this saves you time, please ⭐ the repo! Thanks! ♥️

## 📜 License

Apache-2.0, see `LICENSE`. Third-party versions and licenses in `NOTICE` (pins match the CDN imports and CSP entries).
