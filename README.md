# 📝 Typst Editor

[![ci](https://github.com/fl-grtg/typst-editor/actions/workflows/ci.yml/badge.svg)](https://github.com/fl-grtg/typst-editor/actions/workflows/ci.yml) [![docker](https://github.com/fl-grtg/typst-editor/actions/workflows/docker.yml/badge.svg)](https://github.com/fl-grtg/typst-editor/actions/workflows/docker.yml) [![license](https://img.shields.io/github/license/fl-grtg/typst-editor)](./LICENSE)

Collaborative Typst editor in the browser: code on the left, live PDF on the right.

One process, clean API, boring on purpose. FastAPI serves the API, Yjs syncs the edits, and SQLite stores everything. No Node needed at runtime.

<img width="1280" height="688" alt="editor" src="./screenshot.png" />

## ✨ Features

- Live PDF preview next to the editor, compiled in the browser via Typst WASM
- Realtime collaboration with presence over a cookie-only WebSocket
- Owner, editor, and reviewer roles with share links and doc invites
- Comment threads with anchors, @-mentions, replies, resolve
- Outline, symbol picker, autocomplete + hover docs, find/replace
- File uploads for `#image` and `#include`, 10 MB per file and 200 per doc
- Templates saved per account, organized in folders, reused via `#include`
- History with snapshots, diff view, and one-click restore
- Folders, trash, duplicate, and global search across all docs
- Export as `.typ`, PDF, SVG, first-page PNG, or all own docs as one `.zip`
- Autosave (2.5 s debounce) + 24 h local stash, offline app shell via service worker
- Editor font (10–24 px) + preview zoom (30–200 %) settings, avatars
- Per-user quotas and per-endpoint rate limits enforced server-side
- Self-hostable single container with SQLite, reverse-proxy ready

## 🚀 Get Started

With Docker (under 5 minutes):

```bash
cp .env.example .env
mkdir -p data # Linux: chown 999:999 data; Windows: skip (entrypoint fixes a root-owned mount on first root start)
docker compose up --build
```

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

File plus env overrides; env wins. Defaults live in `backend/config.py`.

| ENV | Default | Notes |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Bare-metal bind address; in the container it is fixed to `0.0.0.0`. |
| `PORT` | `8978` | HTTP port; in the container it is fixed to `8978`. |
| `DATA_DIR` | `./data` | SQLite plus uploads; in the container it is fixed to `/app/data`. |
| `COMPOSE_DATA_PATH` | `./data` | Compose-only host path for the volume, e.g. `/srv/typst-data`. |
| `TRUST_PROXY` | `false` | Required `true` behind Caddy or nginx, else scheme and cookies break. |
| `COOKIE_SECURE` | `auto` | `auto`, `true`, or `false`; keep `auto` behind a proxy. |
| `REGISTRATION` | `invite-only` | `closed`, `invite-only`, or `open`; `open` for local tests only. |
| `REGISTRATION_INVITE_TOKEN` | empty | Invite code for accounts after the first; set via `openssl rand -hex 32`. |
| `SESSION_SECONDS` | `1209600` | Session lifetime in seconds (14 days). |
| `MAX_DOCS_PER_USER` | `100` | Max docs per user. |
| `MAX_BYTES_PER_USER` | `524288000` | Max storage bytes per user (500 MB). |
| `MAX_FILES_PER_DOC` | `200` | Max files per doc. |
| `RATE_LOGIN_PER_MIN` | `10` | Login attempts per minute. |
| `RATE_REGISTER_PER_HOUR` | `20` | Registrations per hour. |
| `RATE_JOIN_PER_MIN` | `30` | Invite redemptions per minute. |
| `RATE_SEARCH_PER_MIN` | `60` | Searches per minute. |
| `RATE_FILES_PER_MIN` | `20` | File up- and downloads per minute. |
| `RATE_FILES_LIST_PER_MIN` | `120` | File list refreshes per minute. |
| `RATE_SAVE_PER_MIN` | `30` | Doc saves per minute. |
| `RATE_COMMENTS_PER_MIN` | `30` | Comment writes per minute. |
| `RATE_EXPORT_PER_MIN` | `5` | ZIP exports per minute. |
| `RATE_PW_PER_MIN` | `10` | Password changes per minute. |
| `RATE_INVITE_PER_MIN` | `10` | Invite creations per minute. |
| `RATE_SHARE_PER_MIN` | `10` | Share changes per minute. |
| `RATE_SNAPSHOTS_PER_MIN` | `60` | Snapshot reads and writes per minute. |
| `RATE_CREATE_PER_MIN` | `20` | Doc creations per minute. |
| `RATE_DUPLICATE_PER_MIN` | `10` | Doc duplications per minute. |
| `RATE_AVATAR_PER_MIN` | `10` | Avatar uploads per minute. |
| `RATE_FOLDERS_PER_MIN` | `20` | Folder operations per minute. |

Never commit local `config.toml` or `.env`; only the `.example` files are tracked.

## 📡 Usage

Health check:

```bash
curl -s http://127.0.0.1:8978/healthz
```

Live sync runs over `WS /ws/{doc_id}`. Auth is cookie-only (`typst_session`, HttpOnly, SameSite=lax): API clients must store cookies, there is no token in body or URL.

## 💾 Data, Backup & Security

Data lives in `DATA_DIR` (`/app/data` in the container, host path via `COMPOSE_DATA_PATH`). It holds `app.db` (SQLite with WAL), `files/`, `backup/`, and `exports/`.

Back up with:

```bash
python scripts/backup.py --include-files
```

This writes `DATA_DIR/backup/app-YYYYMMDD-HHMMSS.db` via `VACUUM INTO` plus a `files/` archive, keeping the newest 7. Run it hourly via cron or `docker compose exec app python scripts/backup.py --include-files`. Tune with `--keep N`, `--no-include-files` (DB only), or preview with `--dry-run`.

Restore: stop the server, copy the backup over `app.db`, delete `app.db-wal` and `app.db-shm`, unpack files with `tar -xzf DATA_DIR/backup/app-*-files.tar.gz -C DATA_DIR/`, then start. Never copy the live DB; WAL would be inconsistent. Verify with `PRAGMA integrity_check;` afterwards.

Backups are unencrypted. Encrypt them: `gpg -c DATA_DIR/backup/app-*.db`.

Behind a reverse proxy (nginx, Caddy), `TRUST_PROXY=true` is required; never expose the app directly, TLS is your responsibility. Minimal nginx example:

```nginx
server {
  listen 443 ssl;
  server_name editor.example.com;
  client_max_body_size 12M; # 10 MB upload + ZIP overhead
  location / {
    proxy_pass http://127.0.0.1:8978;
    proxy_http_version 1.1;
    proxy_set_header Host $host; # WS origin check compares Origin to Host
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade"; # WS needs this
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr; # overwrite, never append: else clients can spoof IPs past rate limits
    proxy_read_timeout 86400; # idle WebSockets stay open (default 60s kills them)
    proxy_buffering off; # live WS traffic, no buffering
  }
}
```

Always run one worker (`--workers 1`) and one replica: sync rooms live in process memory and split across workers. Minimum 512 MB RAM (`mem_limit: 512m`), 1 GB recommended. There is no public demo instance; self-host.

Limits, openly: docs max 200_000 bytes each; uploads max 10 MB per file; history max 50 snapshots per doc with auto-snapshot at most every 15 min; doc invites valid 7 days and visible only once at creation; search needs min 2 chars and returns max 20 hits; quotas are 100 docs and 500 MB per user with 200 files per doc; rate limits per the table above.

### 🔒 Security Contact

Report vulnerabilities via GitHub Private Vulnerability Reporting.
Do not open public issues for security problems.
Allow time for a fix before any disclosure.

Unshare removes the user and wipes all pending invite links for the doc (they carry no username, so per-user revoke is impossible). Downgrading editor to reviewer wipes editor links too. Preview needs internet on first load (cdnjs/esm.sh/jsdelivr for pdf.js/Yjs/typst.ts); afterwards the service worker serves the app shell offline, but saving and syncing need network — offline edits survive at most 24h in the local stash (same-origin localStorage, user-owned drafts only).

CSP intentionally allows `unsafe-inline`, `unsafe-eval`, `wasm-unsafe-eval` plus pinned cdnjs/esm.sh/jsdelivr origins: CodeMirror + Typst WASM cannot run without them. Mitigations: user content via `textContent` only, same-origin API/WS with Origin checks, backups outside web root.

Backups are unencrypted. Encrypt them: `gpg -c DATA_DIR/backup/app-*.db` or `age -r <recipient> <file>`. Use `chmod 600` on shared hosts.

### 🛠 Troubleshooting

- First load needs internet (CDN), then shell offline. Check `#cdnLine` / console.
- Single worker only (`--workers 1`, one replica). Multi-worker exits on purpose.
- Behind proxy set `TRUST_PROXY=true` in `.env`, else cookies/rate-limit break. Overwrite `X-Forwarded-For`, never append.
- Port `8978` loopback-only; TLS via proxy.
- `DATA_DIR` change needs restart. Root-owned volume: entrypoint fixes top-level, retries recursive; else `chown -R 999:999 data`.
- Many read `GET /api/*` share the `files_list` bucket (120/min) – search/snapshots/export have their own; 429 means slow down polling.

### 📦 Changelog

See GitHub Releases (no CHANGELOG file, single README on purpose).

## 💡 Why

Most collaborative editors either need heavy infrastructure or lock you into a cloud. This sits in the middle: one container you can self-host, enough collaboration to work together, little enough surface area to understand in one sitting.

If this saves you time, please ⭐ the repo! Thanks! ♥️

## 📜 License

Apache-2.0, see `LICENSE`.

| Library | Version | License | Upstream |
| --- | --- | --- | --- |
| CodeMirror | 6.0.2 | MIT | https://www.npmjs.com/package/codemirror |
| @codemirror/autocomplete | 6.20.3 | MIT | https://www.npmjs.com/package/@codemirror/autocomplete |
| @codemirror/commands | 6.11.1 | MIT | https://www.npmjs.com/package/@codemirror/commands |
| codemirror-lang-typst | 0.6.0 | Apache-2.0 | https://www.npmjs.com/package/codemirror-lang-typst |
| Yjs | 13.6.27 | MIT | https://www.npmjs.com/package/yjs |
| y-websocket | 1.5.0 | MIT | https://www.npmjs.com/package/y-websocket |
| pdf.js | 3.11.174 | Apache-2.0 | https://www.npmjs.com/package/pdfjs-dist |
| typst-all-in-one.ts | 0.7.0 | Apache-2.0 | https://www.npmjs.com/package/@myriaddreamin/typst-all-in-one.ts |
| typst-ts-web-compiler | 0.7.0 | Apache-2.0 | https://www.npmjs.com/package/@myriaddreamin/typst-ts-web-compiler |
| typst-ts-renderer | 0.7.0 | Apache-2.0 | https://www.npmjs.com/package/@myriaddreamin/typst-ts-renderer |

Yjs/y-websocket/pdf.js/typst-* are pinned on purpose: the CDN imports and CSP entries assume exact versions.
