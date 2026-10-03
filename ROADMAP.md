# Roadmap — Typst Editor

## Erledigt

- **Editor & Kollaboration:** CodeMirror 6 (lokal gevendort), Yjs-Sync via WebSocket,
  Live-Preview (Typst-WASM), Snapshots, Trash, Shares/Invites, Templates, Folders.
- **Accounts & Sicherheit:** PBKDF2-Login, Sessions, CSRF/CSP, Rate-Limits, Quota mit Rollback.
- **PWA & Ops:** Manifest/Icons, Docker + Compose (read-only, no-new-privileges),
  Entrypoint mit Writability-Gate, Healthcheck, Backup-Skript, CI mit Vendor-Budget.
- **MCP-Phase (M1–M4):** API-Keys (`tpe_…`, Bearer-only), 8 Tools
  (ls/read/create/edit/search/upload/comment/view), Pfadmodell
  `/docs|/shared|/templates`, Reviewer-Cap, Agent-Skill (`skills/typst-editor/`).

## Als Nächstes (siehe PLAN.md)

- Quota-Check aus Transaktionen holen (503 unter Last).
- Invites pro User zuordenbar.
- ARM64-Image publizieren + Startup-/Proxy-Gates testen.
- WS-Reconnect + Offline-Outbox, Preview-Perf.

## Später

- Single-Worker entwachsen (persistente Rooms/Queues).
- Echter Offline-Modus (Service Worker, IndexedDB).
- Suite beschleunigen, Doku-Counts automatisieren.
