# Security

Local-first app: run behind 127.0.0.1.
No rate limiting yet, do not expose publicly.
SQLite storage lives in local `data/` (gitignored).
Passwords: minimum 8 chars, hashed storage.
Sessions expire server-side; report leaks fast.
Reviewer role is read-only by server check.
Share tokens grant the linked role, guard them.
Backups are plain `.zip` files, store safely.
Do not commit secrets, tokens, or database files.
Report issues via GitHub issue on this repo.
Supported: latest main branch only.
See limits and backup notes in README.md.

