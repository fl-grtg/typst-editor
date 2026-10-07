# 📝 Typst Editor

[![ci](https://github.com/fl-grtg/typst-editor/actions/workflows/ci.yml/badge.svg)](https://github.com/fl-grtg/typst-editor/actions/workflows/ci.yml) [![docker](https://github.com/fl-grtg/typst-editor/actions/workflows/docker.yml/badge.svg)](https://github.com/fl-grtg/typst-editor/actions/workflows/docker.yml) [![license](https://img.shields.io/github/license/fl-grtg/typst-editor)](./LICENSE)

Collaborative Typst editor in the browser: code left, live PDF right.

One process: FastAPI serves the API, Yjs syncs edits, SQLite stores all. No Node at runtime.

<img width="1920" height="1080" alt="editor" src="./docs/screenshot.png" />

## ✨ Features

- Live PDF preview, compiled in browser (Typst 0.15.1 via typst.ts 0.8.0-rc3 WASM, pdf.js render)
- Realtime collab via Yjs over `WS /ws/{doc_id}`, presence included, cookie-only auth
- Owner/editor/reviewer roles (reviewer = Reader: comment only), share links, doc invites
- Comment threads with line anchors, @-mentions, one-level replies, resolve, edit
- Outline from `=` headings, symbol picker, autocomplete (`#image`/`#include`), find/replace
- Uploads (`.png/.jpg/.jpeg/.svg/.gif/.webp/.pdf/.typ/.bib/.csv`) via button, drag & drop, paste
- Templates per account with folders, reused via `#include`
- History: manual + auto snapshots, line diff, one-click restore (saves `Before restore` first)
- Folders, two-stage trash, duplicate (owner/editor, copies files), search over titles + content
- Export `.typ`, PDF, SVG, PNG of current page, or all docs as `.zip` (`GET /api/export.zip`)
- Autosave (~2.5 s), 24 h local stash, offline shell, font/zoom/theme settings
- Account settings: avatar (PNG/JPEG/WebP, 200 KB), rename, password change, delete
- Per-user quotas + per-endpoint rate limits, enforced server-side

## 🚀 Get Started

Docker (no config needed):

```bash
docker compose up -d
docker compose logs app | grep "invite code"
# Windows PowerShell: docker compose logs app | Select-String "invite code"
```

Pulls the image (`pull_policy: always`). Data stays in a managed volume. Host path instead: set `COMPOSE_DATA_PATH` (Linux/macOS/WSL: `chown -R 999:999` on it).

Sign up at `http://127.0.0.1:8978` with the invite code from the logs. Custom setup only: `cp .env.example .env`. Custom port: set `PORT` in `.env` (moves host + container port). Build local: `docker build -t ghcr.io/fl-grtg/typst-editor:main .`.

Local Python 3.11:

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows (source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8978 --workers 1
```

Registration is `invite-only`. Fresh Docker installs print a token on first start (stored `chmod 600` as `DATA_DIR/.invite_token`). Every account needs it. Public servers: set `REGISTRATION_INVITE_TOKEN` before first start (`openssl rand -hex 32`). Empty token blocks registration (fail-closed). `open` is for local tests only.

## ⚙️ Configuration

File + env overrides; env wins. Parsed in `backend/config.py`. `.env.example`/`config.example.toml` mirror it.

| ENV | Default | Notes |
| --- | --- | --- |
| `DATA_DIR` | `./data` | SQLite + uploads; `/app/data` in container. |
| `COMPOSE_DATA_PATH` | managed volume | Host path instead, e.g. `/srv/typst-data`. |
| `TRUST_PROXY` | `false` | Set `true` behind a proxy, else cookies break. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Peers allowed to send `X-Forwarded-*` (CIDR ok); same value goes to uvicorn. Never `*` with `TRUST_PROXY=true` (refuses to start). |
| `REGISTRATION` | `invite-only` | `closed`, `invite-only`, or `open`. |
| `REGISTRATION_INVITE_TOKEN` | empty | Min 16 chars when set, else start refuses. |
| `SESSION_SECONDS` | `1209600` | 14 days. |
| `MAX_DOCS_PER_USER` | `100` | Plus 500 MB and 200 files per doc. |

Never commit `config.toml` or `.env`; only `.example` files are tracked.

## 📡 API

```bash
curl -s http://127.0.0.1:8978/healthz
```

Sync runs over `WS /ws/{doc_id}` (y-websocket). Browser auth is cookie-based (`typst_session`, HttpOnly, SameSite=lax); agents use Bearer API keys (see below). Invite tokens go in the POST body, never in the URL. `/?join=TOKEN` and `/?invite=CODE` are entry links only: the app reads the code, strips it from the URL, sends it via POST.

### 🔗 Invite links

- `https://host/?invite=CODE` opens registration with code prefilled (no auto-submit). Needs logged-out browser.
- `https://host/?join=TOKEN` redeems a doc invite after login. Share via doc Share button.

### 🔑 API keys + MCP

Keys look like `tpe_<8hex>_<32hex>` (only the sha256 hash is stored; the secret is shown once at creation in Settings). Roles: `reviewer` (read + comment, least privilege) or `editor` (default); `expires_in_days` optional (1–365, default never).

```bash
curl -cj jar.txt -b jar.txt -X POST http://127.0.0.1:8978/api/keys \
  -H 'Content-Type: application/json' -d '{"name":"agent","role":"reviewer","expires_in_days":90}'
curl -s -b jar.txt http://127.0.0.1:8978/api/keys
curl -s http://127.0.0.1:8978/api/keys -H "Authorization: Bearer tpe_..."
```

Claude Code: `claude mcp add --transport http typst-editor http://127.0.0.1:8978/mcp --header "Authorization: Bearer tpe_..."`

OpenCode (`opencode.json`): server `"typst-editor"` with `"type": "remote"`, `"url": "http://127.0.0.1:8978/mcp"`, `"headers": {"Authorization": "Bearer tpe_..."}`.

Agent loop `ls -> read -> edit -> view -> fix`; see `skills/typst-editor/SKILL.md` for path model and edit rules. Note: `view` returns native image blocks (longest side ≤1280px) + `count`/`cache_hit`/`last_seen` — update server and skill together, the old base64 `pages[]` field is gone.

## 💾 Backup

```bash
python scripts/backup.py --include-files
```

Writes `DATA_DIR/backup/app-YYYYMMDD-HHMMSS.db` (`VACUUM INTO`) + `*-files.tar.gz` of `DATA_DIR/files`. Keeps newest 7 (`--keep N`, `--dry-run` to preview). `--keep 0` still keeps 1. Cron: `docker compose exec -T app python scripts/backup.py --include-files`. Backups are plain: `gpg -c DATA_DIR/backup/app-*.db`.

Restore: stop server, copy backup over `app.db`, delete `app.db-wal`/`app.db-shm`, unpack files (`tar -xzf ... -C DATA_DIR`), `chown -R 999:999 DATA_DIR` on host paths, start. Check with `PRAGMA integrity_check;`.

## 🔌 Reverse proxy

Needs `TRUST_PROXY=true`. Never expose directly; TLS is yours. Caddy:

```
typst.example.com {
    reverse_proxy 127.0.0.1:8978
}
```

nginx (WebSocket needs `http_version 1.1` + `Upgrade`/`Connection`):

```
server {
    listen 443 ssl;
    server_name typst.example.com;
    ssl_certificate /etc/letsencrypt/live/typst.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/typst.example.com/privkey.pem;

    client_max_body_size 12M;

    location / {
        proxy_pass http://127.0.0.1:8978;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
    }
}
```

Without those headers the sync socket stays dead. `client_max_body_size 12M` covers 10 MB uploads. Custom `PORT`: point proxy at that port.

Uvicorn trusts `X-Forwarded-For`/`Proto` only from `FORWARDED_ALLOW_IPS` (default `127.0.0.1,::1`). Behind compose the proxy uses a `172.x` IP, so extend the default: `FORWARDED_ALLOW_IPS=127.0.0.1,::1,172.16.0.0/12`. Else all clients share one rate-limit bucket. Never `*` with `TRUST_PROXY=true`.

One worker (`--workers 1`), one replica: rooms live in memory. 512 MB min, 1 GB advised. No public demo; self-host.

Limits: 200000 chars per doc (`MAX_TXT` in `backend/constants.py`); titles 100 chars, folders 40; uploads 10 MB per file; 50 snapshots per doc, auto max every 15 min; invites valid 7 days, max 20 per doc, multi-use (token shown once); search needs 2 chars, max 20 hits, docs only; quotas 100 docs + 500 MB per user, 200 files per doc; avatars 200 KB; `.zip` capped at 100 MB, files over 10 MB go to `SKIPPED.txt`; reads share `files_list` bucket (120/min).

### 🔒 Security Contact

Report vulns via GitHub Private Vulnerability Reporting.
No public issues for security problems.
Allow time for a fix before disclosure.

Unshare wipes pending invite links (they carry no username). First load needs internet (CDN: cdnjs/esm.sh/jsdelivr; pins: typst.ts 0.8.0-rc3 = bundled Typst 0.15.1 = CLI 0.15.1, pdf.js 3.11.174, yjs 13.6.27, y-websocket 1.5.0). Typst alignment (2026-10-05): no 0.16 release exists (0.15.1 is newest), so CLI stays 0.15.1; WASM is 0.8.0-rc3 on purpose — latest stable (0.7.0) still bundles Typst 0.14.2, only the RC bundles 0.15.1. View cache is salted with `typst --version`, so CLI bumps auto-bust it. Afterwards the shell stays in browser cache; saving needs net (24 h stash). No service worker (dropped 2026-10-03, plain HTTP cache). `Cache-Control: no-store` on `/`, `*.html`, `*.js`, `/api/*` (see `backend/main.py`); versioned assets (`vendor-cm.js`, `manifest.json`, icons) are `immutable`. CSP needs `unsafe-inline`/`unsafe-eval`/`wasm-unsafe-eval` for Typst WASM; user content renders via `textContent` only.

### 🛠 Troubleshooting

- First load needs internet (CDN). Check `#cdnLine` / console.
- Single worker only (`--workers 1`). Multi-worker exits on purpose.
- Behind proxy: `TRUST_PROXY=true`.
- Port `8978` is loopback-only (override via `PORT`); TLS via proxy.
- Host path perms only: `chown -R 999:999` on it.
- `429` on reads: shared `files_list` bucket (120/min), slow down.

### 🧪 Develop

```bash
pip install -r requirements-dev.txt
python -m pytest            # 215 tests
ruff check backend/ scripts/ tests/
mypy backend/ scripts/ tests/
```

Vendor bundle (`cm-build/` → `vendor-cm.js`): `cd cm-build && npm ci && npm run build`. CI fails on diff or >600 KB.

### 📦 Changelog

See GitHub Releases (no CHANGELOG file, single README on purpose).

## 💡 Why

Most collab editors need heavy infra or lock you into a cloud. This is one container you self-host: enough collab to work together, small enough to read in one sitting.

## 📜 License

Apache-2.0, see `LICENSE`. Third-party versions in `NOTICE` (pins match CDN imports and CSP).
