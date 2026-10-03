from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
SCHEMA_PATH = BACKEND_DIR / "schema.sql"
try:
    from backend.config import load as _load
    DB_PATH = _load().DATA_DIR / "app.db"
except Exception:
    DB_PATH = ROOT / "data" / "app.db"

# Startup default (backwards compat); get_db_path() below is the live view.
_STARTUP_DB_PATH = DB_PATH


def get_db_path() -> Path:
    """Live DB location: current DATA_DIR unless DB_PATH was overridden.

    Tests monkeypatch db.DB_PATH for tmp isolation; honor that override.
    Otherwise follow config.load().DATA_DIR so a later DATA_DIR change
    stays consistent with get_files_dir().
    """
    try:
        from backend import config as _cfg

        live = _cfg.load().DATA_DIR / "app.db"
    except Exception:
        return DB_PATH
    try:
        if DB_PATH != _STARTUP_DB_PATH:
            return DB_PATH
    except Exception:
        return DB_PATH
    return live


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(16)}"


def connect() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def backup_to(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        con.execute("VACUUM INTO ?", (str(path),))
    finally:
        con.close()


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    # One transaction, one owner: BEGIN IMMEDIATE on entry, commit on clean
    # exit, ROLLBACK on any error (HTTPException included). Callers map
    # OperationalError to 503; no manual ROLLBACKs inside the block.
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_v1(con: sqlite3.Connection) -> None:
    # Legacy docs columns (fresh schema.sql already has them: no-ops there).
    cols = _cols(con, "docs")
    if "yjs" not in cols:
        con.execute("ALTER TABLE docs ADD COLUMN yjs BLOB")
    if "folder" not in cols:
        con.execute("ALTER TABLE docs ADD COLUMN folder TEXT NOT NULL DEFAULT ''")
    if "trashed" not in cols:
        con.execute("ALTER TABLE docs ADD COLUMN trashed INTEGER NOT NULL DEFAULT 0")


def _migrate_v2(con: sqlite3.Connection) -> None:
    if "quote" not in _cols(con, "comments"):
        con.execute("ALTER TABLE comments ADD COLUMN quote TEXT NOT NULL DEFAULT ''")


def _migrate_v3(con: sqlite3.Connection) -> None:
    if "avatar" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT ''")
    if "resolved" not in _cols(con, "comments"):
        con.execute("ALTER TABLE comments ADD COLUMN resolved INTEGER NOT NULL DEFAULT 0")


def _migrate_v4(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS snapshots ("
                "id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE, "
                "content TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_doc ON snapshots(doc_id, created_at)")


def _migrate_v5(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS invites ("
                "token TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE, "
                "role TEXT NOT NULL DEFAULT 'reviewer', created_at TEXT NOT NULL)")
    if "hint" not in _cols(con, "invites"):
        con.execute("ALTER TABLE invites ADD COLUMN hint TEXT NOT NULL DEFAULT ''")


def _migrate_v6(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS folders ("
                "owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, "
                "kind TEXT NOT NULL DEFAULT 'doc', name TEXT NOT NULL, created_at TEXT NOT NULL, "
                "PRIMARY KEY (owner, kind, name))")


def _migrate_v7(con: sqlite3.Connection) -> None:
    if "folder" not in _cols(con, "templates"):
        con.execute("ALTER TABLE templates ADD COLUMN folder TEXT NOT NULL DEFAULT ''")


def _migrate_v8(con: sqlite3.Connection) -> None:
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_owner_title "
                "ON docs(owner, title COLLATE NOCASE)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_shares_user ON shares(username, doc_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_shares_doc ON shares(doc_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_docs_updated ON docs(updated_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_invites_doc ON invites(doc_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_templates_owner ON templates(owner)")


_MIGRATIONS: tuple[Callable[[sqlite3.Connection], None], ...] = (
    _migrate_v1, _migrate_v2, _migrate_v3, _migrate_v4,
    _migrate_v5, _migrate_v6, _migrate_v7, _migrate_v8,
)


def migrate(con: sqlite3.Connection) -> None:
    # Idempotent: every step checks before writing; applied versions recorded
    # so re-runs and fresh DBs converge to the same schema.
    con.execute("CREATE TABLE IF NOT EXISTS schema_version (v INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in con.execute("SELECT v FROM schema_version").fetchall()}
    for i, step in enumerate(_MIGRATIONS, start=1):
        if i not in done:
            step(con)
            con.execute("INSERT INTO schema_version (v, applied_at) VALUES (?,?)", (i, now_iso()))
            con.commit()


def init_db() -> None:
    con = connect()
    try:
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        migrate(con)
        con.commit()
    finally:
        con.close()


def doc_role(user: str, doc_id: str) -> str | None:
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
    con = connect()
    try:
        r = con.execute("SELECT yjs, content FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not r:
            return None, ""
        return (bytes(r["yjs"]) if r["yjs"] is not None else None, r["content"] or "")
    finally:
        con.close()


def save_room(doc_id: str, yjs: bytes, text: str) -> None:
    con = connect()
    try:
        con.execute("UPDATE docs SET yjs=?, content=?, updated_at=? WHERE id=?",
                    (yjs, text, now_iso(), doc_id))
        con.commit()
    finally:
        con.close()


def clear_room_state(doc_id: str) -> None:
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
