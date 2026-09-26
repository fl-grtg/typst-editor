# 📝 Typst Editor

Collaborative Typst editor in the browser: code on the left, live PDF on the right.

One process, clean API, boring on purpose. FastAPI + live sync, SQLite storage, no Node needed at runtime.

<!-- Screenshot vor Public: App starten, Bild als docs/screenshot.png speichern, dann einbetten:
<img width="1280" height="640" alt="editor" src="docs/screenshot.png" />
-->

## ✨ Features

- Live PDF preview next to the editor
- Real-time collaboration (shared editing, presence, comments)
- Sharing with owner / editor / reviewer roles + invite links
- File uploads (`#image`, `#include` ready) and `.typ` / PDF / PNG / SVG export
- History with snapshots, diff and restore
- Folders, trash, duplicate, global search, ZIP backup
- Self-hostable: single container, SQLite, reverse-proxy ready

## 🚀 Get Started

With Docker (easiest):

```bash
cp .env.example .env
docker compose up --build
```

Open `http://127.0.0.1:8978`, register, start writing.

Or locally with Python 3.11:

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows (source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8978 --workers 1
```

Always use `--workers 1` and a single replica — live rooms live in process memory and split across workers.

Test: `pip install -r requirements-dev.txt` then `pytest -q`.

Rebuild the CodeMirror bundle only after `cm-build/entry.js` changes:

```sh
cd cm-build && npm run build
```

## ⚙️ Config

File + env overrides; env wins. Defaults live in `backend/config.py` (see `config.example.toml`):

- `PORT=8978`, `HOST=127.0.0.1` (keep loopback unless proxied)
- `DATA_DIR=./data` (SQLite + uploads)
- `REGISTRATION=open` (`open` | `invite-only` | `closed`)
- `SESSION_SECONDS=1209600` (14 days)
- Quotas: `MAX_DOCS_PER_USER=100`, `MAX_BYTES_PER_USER=524288000`, `MAX_FILES_PER_DOC=200`
- Rate limits: `RATE_LOGIN_PER_MIN=10`, `RATE_REGISTER_PER_HOUR=20`

Never commit local `config.toml` or `.env`; only the `.example` files are tracked.

Behind a reverse proxy set `TRUST_PROXY=true`. Do NOT expose the app directly — TLS is your
responsibility. Example: `Caddyfile.example`.

## 📡 API

- `POST /api/register`, `POST /api/login`, `POST /api/logout`, `GET /api/me`
- `GET /api/docs`, `POST /api/docs/create`, `GET /api/docs/{id}`, `POST /api/docs/{id}/save`
- `POST /api/docs/{id}/share`, `POST /api/docs/{id}/invite`, `POST /api/join/{token}`
- `WS /ws/{doc_id}` for live sync (token as query param)
- `GET /api/export.zip` for backup, `GET /healthz` for health checks

## 🔒 Security & Limits

- Passwords: min 8 chars, PBKDF2-hashed. Sessions expire server-side.
- Reviewer role is read-only; share links grant the linked role — guard them.
- Backups are plain `.zip` files — store them encrypted.
- History: max 50 snapshots per doc. Uploads: max 10 MB per file. Docs: max 200 KB.
- UI is currently German-first; docs are English. EN contributions welcome.
- Preview needs network for CDN (pdf.js, Yjs, Typst WASM); PWA offline covers app shell only.

Report vulnerabilities via GitHub Private Vulnerability Reporting (no public issues).

## 💡 Why

Most collaborative editors either need heavy infrastructure or lock you into a cloud. This sits in the middle: one container you can self-host, enough collaboration to work together, little enough surface area to understand in one sitting.

If this saves you time, please ⭐ the repo! Thanks! ♥️

## 📜 License

Apache-2.0, see `LICENSE`. Third-party: CodeMirror 6 (MIT, bundled in `vendor-cm.js`),
Yjs + y-websocket (MIT, via CDN), pdf.js (Apache-2.0, via CDN), typst.ts (Apache-2.0, via CDN).
