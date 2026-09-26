from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
SCHEMA_PATH = BACKEND_DIR / "schema.sql"
DB_PATH = ROOT / "data" / "app.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(16)}"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")  # WS-Saves + HTTP parallel: kurz warten statt locked-Fehler
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    con = connect()
    try:
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        cols = [r["name"] for r in con.execute("PRAGMA table_info(docs)").fetchall()]
        if "yjs" not in cols:  # alte DB: Spalte nachziehen
            con.execute("ALTER TABLE docs ADD COLUMN yjs BLOB")
        if "folder" not in cols:  # alte DB: Ordner nachziehen
            con.execute("ALTER TABLE docs ADD COLUMN folder TEXT NOT NULL DEFAULT ''")
        if "trashed" not in cols:  # alte DB: Papierkorb nachziehen
            con.execute("ALTER TABLE docs ADD COLUMN trashed INTEGER NOT NULL DEFAULT 0")
        ccols = [r["name"] for r in con.execute("PRAGMA table_info(comments)").fetchall()]
        if "quote" not in ccols:
            con.execute("ALTER TABLE comments ADD COLUMN quote TEXT NOT NULL DEFAULT ''")
        ucols = [r["name"] for r in con.execute("PRAGMA table_info(users)").fetchall()]
        if "avatar" not in ucols:  # alte DB: Profilbild nachziehen
            con.execute("ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT ''")
        if "resolved" not in ccols:  # alte DB: Erledigt-Haken nachziehen
            con.execute("ALTER TABLE comments ADD COLUMN resolved INTEGER NOT NULL DEFAULT 0")
        con.execute("CREATE TABLE IF NOT EXISTS snapshots ("  # Verlauf: Inhalt je Stand
                    "id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE, "
                    "content TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_doc ON snapshots(doc_id, created_at)")
        con.execute("CREATE TABLE IF NOT EXISTS invites ("  # Link-Einladungen pro Doc
                    "token TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE, "
                    "role TEXT NOT NULL DEFAULT 'reviewer', created_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS folders ("  # explizite Ordner (auch leer), kind doc/tpl
                    "owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, "
                    "kind TEXT NOT NULL DEFAULT 'doc', name TEXT NOT NULL, created_at TEXT NOT NULL, "
                    "PRIMARY KEY (owner, kind, name))")
        tcols = [r["name"] for r in con.execute("PRAGMA table_info(templates)").fetchall()]
        if "folder" not in tcols:  # alte DB: Vorlagen-Ordner nachziehen
            con.execute("ALTER TABLE templates ADD COLUMN folder TEXT NOT NULL DEFAULT ''")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_owner_title "
                    "ON docs(owner, title COLLATE NOCASE)")  # Titel pro Owner nur einmal
        con.commit()
    finally:
        con.close()


def doc_role(user: str, doc_id: str) -> str | None:
    """owner | editor | reviewer | None. Eine Stelle für HTTP + WS."""
    con = connect()
    try:
        d = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not d:
            return None
        if d["owner"] == user:
            return "owner"
        s = con.execute("SELECT role FROM shares WHERE doc_id=? AND username=?",
                        (doc_id, user)).fetchone()
        return s["role"] if s else None
    finally:
        con.close()


def get_room_state(doc_id: str) -> tuple[bytes | None, str]:
    """(yjs-Bytes, Text) zum Room-Aufbau. Bytes zuerst: gleiche IDs, kein Doppeltext."""
    con = connect()
    try:
        r = con.execute("SELECT yjs, content FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not r:
            return None, ""
        return (bytes(r["yjs"]) if r["yjs"] is not None else None, r["content"] or "")
    finally:
        con.close()


def save_room(doc_id: str, yjs: bytes, text: str) -> None:
    """Live-Room sichern: Bytes (IDs) + Text + Zeit."""
    con = connect()
    try:
        con.execute("UPDATE docs SET yjs=?, content=?, updated_at=? WHERE id=?",
                    (yjs, text, now_iso(), doc_id))
        con.commit()
    finally:
        con.close()


def clear_room_state(doc_id: str) -> None:
    """Stale Yjs-Bytes weg: nächster Room baut aus content neu (nach Restore)."""
    con = connect()
    try:
        con.execute("UPDATE docs SET yjs=NULL WHERE id=?", (doc_id,))
        con.commit()
    finally:
        con.close()


def is_trashed(doc_id: str) -> bool:
    con = connect()
    try:
        r = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
        return bool(r and r["trashed"])
    finally:
        con.close()
