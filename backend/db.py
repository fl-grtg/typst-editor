from __future__ import annotations

import logging
import secrets
import sqlite3
import time
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


def _migrate_backup_target() -> Path:
    db_path = get_db_path()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = db_path.parent / f"{db_path.stem}-migrate-{stamp}.db"
    i = 2
    while target.exists():
        target = db_path.parent / f"{db_path.stem}-migrate-{stamp}-{i}.db"
        i += 1
    return target


def _needs_migrate_backup(con: sqlite3.Connection, done: set[int]) -> bool:
    # Fresh DBs (nothing applied, no user data) need no backup; returning
    # DBs always get one before any step runs.
    if done:
        return True
    try:
        for table in ("users", "docs"):
            try:
                if con.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    return True
            except sqlite3.OperationalError:
                continue
    except Exception:
        pass
    return False


def backup_before_migrate(con: sqlite3.Connection, done: set[int]) -> Path | None:
    """VACUUM INTO a timestamped file next to the DB. None when skipped.

    Fail-open: a backup failure only warns and returns None so startup
    migration still runs (a half-migrated DB is worse than a missing
    pre-migrate snapshot).
    """
    if not get_db_path().is_file():
        return None
    if not _needs_migrate_backup(con, done):
        return None
    target = _migrate_backup_target()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        con.commit()  # VACUUM cannot run inside a transaction
        con.execute("VACUUM INTO ?", (str(target),))
    except (OSError, sqlite3.Error) as e:
        logging.getLogger(__name__).warning("pre-migrate backup failed, continuing: %s", e)
        return None
    logging.getLogger(__name__).info("pre-migrate backup: %s", target)
    return target


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


def _migrate_v9(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS api_keys ("
                "id TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, "
                "name TEXT NOT NULL DEFAULT '', prefix TEXT NOT NULL DEFAULT '', "
                "key_hash TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'editor', "
                "expires_at TEXT NOT NULL DEFAULT '', last_used TEXT NOT NULL DEFAULT '', "
                "revoked INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(username)")


def _migrate_v10(con: sqlite3.Connection) -> None:
    if "author" not in _cols(con, "comments"):
        con.execute("ALTER TABLE comments ADD COLUMN author TEXT NOT NULL DEFAULT ''")


def _migrate_v11(con: sqlite3.Connection) -> None:
    # Anchors are 1-based line numbers; 0 ("top" via old MCP/skill doc)
    # broke the comment card (Line 0, no gutter dot, no re-render on
    # close/reopen). Heal existing rows to line 1.
    con.execute("UPDATE comments SET anchor=1 WHERE anchor < 1")


def _migrate_v12(con: sqlite3.Connection) -> None:
    # FTS5 index over docs(title, content). External-content table keyed by
    # docs.rowid (docs.id is TEXT, so content-sync is not an option);
    # triggers keep it in sync, the WHEN clause skips no-op rewrites
    # (touch_doc bumps updated_at without touching title/content).
    # Rebuild is a single DELETE + INSERT ... SELECT: one write txn, WAL
    # stays responsive (no exclusive lock beyond the statement).
    # Without FTS5 (minimal SQLite builds) skip gracefully: search.py
    # falls back to LIKE + filesystem scan.
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts "
                    "USING fts5(title, content, tokenize='unicode61')")
    except sqlite3.OperationalError as e:
        logging.getLogger(__name__).warning("fts5 unavailable, skipping docs_fts: %s", e)
        return
    con.execute("CREATE TRIGGER IF NOT EXISTS docs_fts_ai AFTER INSERT ON docs BEGIN "
                "INSERT INTO docs_fts(rowid, title, content) "
                "VALUES (new.rowid, new.title, new.content); END")
    con.execute("CREATE TRIGGER IF NOT EXISTS docs_fts_ad AFTER DELETE ON docs BEGIN "
                "DELETE FROM docs_fts WHERE rowid=old.rowid; END")
    con.execute("CREATE TRIGGER IF NOT EXISTS docs_fts_au AFTER UPDATE ON docs "
                "WHEN old.title IS NOT new.title OR old.content IS NOT new.content BEGIN "
                "DELETE FROM docs_fts WHERE rowid=old.rowid; "
                "INSERT INTO docs_fts(rowid, title, content) "
                "VALUES (new.rowid, new.title, new.content); END")
    con.execute("DELETE FROM docs_fts")
    con.execute("INSERT INTO docs_fts(rowid, title, content) "
                "SELECT rowid, title, content FROM docs")


def _migrate_v13(con: sqlite3.Connection) -> None:
    # Files table (doc_id, path, size, mtime, type),
    # notifications table, read_tokens table, plus a start-scan that
    # populates files from existing on-disk attachments.
    con.execute("CREATE TABLE IF NOT EXISTS files ("
                "doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE, "
                "path TEXT NOT NULL, size INTEGER NOT NULL DEFAULT 0, "
                "mtime REAL NOT NULL DEFAULT 0, type TEXT NOT NULL DEFAULT '', "
                "PRIMARY KEY (doc_id, path))")
    con.execute("CREATE INDEX IF NOT EXISTS idx_files_doc ON files(doc_id)")
    con.execute("CREATE TABLE IF NOT EXISTS notifications ("
                "id TEXT PRIMARY KEY, recipient TEXT NOT NULL, type TEXT NOT NULL DEFAULT '', "
                "doc_id TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '', "
                "is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_notifications_recipient "
                "ON notifications(recipient, created_at)")
    con.execute("CREATE TABLE IF NOT EXISTS read_tokens ("
                "token_hash TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE, "
                "hint TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, expires_at TEXT NOT NULL DEFAULT '')")
    con.execute("CREATE INDEX IF NOT EXISTS idx_read_tokens_doc ON read_tokens(doc_id)")
    try:
        from backend import deps as _deps
        base = _deps.get_files_dir()
    except Exception as e:
        logging.getLogger(__name__).warning("v13 start-scan skipped (files dir): %s", e)
        return
    try:
        known = {r[0] for r in con.execute("SELECT id FROM docs").fetchall()}
    except sqlite3.OperationalError:
        return
    try:
        if not base.is_dir():
            logging.getLogger(__name__).warning("v13 start-scan skipped (no files dir)")
            return
        top = list(base.iterdir())
    except OSError as e:
        logging.getLogger(__name__).warning("v13 start-scan skipped: %s", e)
        return
    scanned = 0
    logging.getLogger(__name__).info("v13 attachment scan started: %s", base)
    for d in top:
        try:
            if d.is_symlink() or not d.is_dir() or d.name.startswith(".") or ".tmp." in d.name:
                continue
        except OSError:
            continue
        if d.name not in known:
            continue  # orphan dir (doc gone): no rows, FK would reject them anyway
        try:
            # Iterator, never list(rglob): a huge tree must not be
            # materialized, and one bad entry must not kill the dir.
            for p in d.rglob("*"):
                try:
                    if p.is_symlink():
                        continue  # like the export walk: never follow/count links
                    if not p.is_file():
                        continue
                    rel = p.relative_to(d).as_posix()
                    if any(seg.startswith(".") for seg in rel.split("/")) or ".tmp." in p.name:
                        continue
                    st = p.stat()
                    con.execute("INSERT OR REPLACE INTO files (doc_id, path, size, mtime, type) "
                                "VALUES (?,?,?,?,?)",
                                (d.name, rel, st.st_size, st.st_mtime, p.suffix.lower()))
                except (OSError, ValueError, sqlite3.Error) as e:
                    # Broken name (surrogates), unreadable file, bad row:
                    # skip the file, never abort the migration.
                    logging.getLogger(__name__).warning("v13 scan skipped %s: %s", d.name, e)
                    continue
                scanned += 1
                if scanned % 200 == 0:
                    con.commit()  # chunk-commits, no giant txn
        except OSError as e:
            logging.getLogger(__name__).warning("v13 scan skipped dir %s: %s", d.name, e)
            continue


    logging.getLogger(__name__).info("v13 attachment scan complete: %d files", scanned)


def _migrate_v14(con: sqlite3.Connection) -> None:
    if "project_id" not in _cols(con, "docs"):
        con.execute("ALTER TABLE docs ADD COLUMN project_id TEXT REFERENCES projects(id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_docs_project ON docs(project_id)")


def _migrate_v15(con: sqlite3.Connection) -> None:
    if "archived" not in _cols(con, "projects"):
        con.execute("ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")


def _migrate_v16(con: sqlite3.Connection) -> None:
    from backend.services import projects
    con.execute("CREATE TABLE IF NOT EXISTS legacy_project_folders (owner TEXT NOT NULL, folder TEXT NOT NULL, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, PRIMARY KEY(owner,folder))")
    for d in con.execute("SELECT id FROM docs WHERE project_id IS NULL ORDER BY owner,folder,trashed,id").fetchall():
        projects.attach_doc(con, d["id"], check_quota=False)
    for f in con.execute("SELECT owner,name FROM folders WHERE kind='doc'").fetchall():
        title = f["name"].split("/")[0]
        if not con.execute("SELECT 1 FROM legacy_project_folders WHERE owner=? AND folder=?", (f["owner"], title)).fetchone():
            pid = projects.create(con, f["owner"], title)
            con.execute("INSERT INTO legacy_project_folders VALUES (?,?,?)", (f["owner"], title, pid))
    con.execute("DELETE FROM folders WHERE kind='doc'")


def _migrate_v17(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS project_snapshots (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, content TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'manual')")


def _migrate_v18(con: sqlite3.Connection) -> None:
    con.execute("DROP INDEX IF EXISTS idx_docs_owner_title")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_project_title ON docs(project_id,title COLLATE NOCASE) WHERE project_id IS NOT NULL AND trashed=0")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_legacy_title ON docs(owner,title COLLATE NOCASE) WHERE project_id IS NULL AND trashed=0")


def _migrate_v19(con: sqlite3.Connection) -> None:
    added = "migration_bytes" not in _cols(con, "users")
    if added:
        con.execute("ALTER TABLE users ADD COLUMN migration_bytes INTEGER NOT NULL DEFAULT 0")
    if added and _cols(con, "project_resources"):  # table gone since v34
        con.execute("UPDATE users SET migration_bytes=(SELECT COALESCE(SUM(LENGTH(CAST(r.content AS BLOB))),0) "
                    "FROM project_resources r JOIN projects p ON p.id=r.project_id WHERE p.owner=users.name)")
    seen: set[tuple[str, str]] = set()
    for p in con.execute("SELECT id,owner,title FROM projects ORDER BY created_at,id").fetchall():
        title, number = p["title"], 2
        # Match SQLite's ASCII NOCASE, including on non-ASCII project titles.
        key = con.execute("SELECT lower(?)", (title,)).fetchone()[0]
        if (p["owner"], key) in seen:
            while True:
                suffix = f" ({number})"
                title = p["title"][:100-len(suffix)] + suffix
                key = con.execute("SELECT lower(?)", (title,)).fetchone()[0]
                number += 1
                if not con.execute("SELECT 1 FROM projects WHERE owner=? AND title=? COLLATE NOCASE AND id<>?", (p["owner"], title, p["id"])).fetchone():
                    break
        con.execute("UPDATE projects SET title=? WHERE id=?", (title, p["id"]))
        seen.add((p["owner"], key))
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_owner_title_nocase ON projects(owner,title COLLATE NOCASE)")


def _migrate_v20(con: sqlite3.Connection) -> None:
    for name, definition in (("suggestion_old", "TEXT"), ("replacement", "TEXT"),
                             ("suggestion_status", "TEXT NOT NULL DEFAULT ''")):
        if name not in _cols(con, "comments"):
            con.execute(f"ALTER TABLE comments ADD COLUMN {name} {definition}")


def _migrate_v21(con: sqlite3.Connection) -> None:
    if "spell_language" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN spell_language TEXT NOT NULL DEFAULT 'auto'")


def _migrate_v22(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS trash_entries (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
 kind TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT '', doc_id TEXT NOT NULL DEFAULT '',
 name TEXT NOT NULL, content BLOB NOT NULL, line TEXT NOT NULL DEFAULT '',
 folder TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);""")


def _migrate_v23(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS suggestion_packages (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 author TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, title TEXT NOT NULL,
 files TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, accepted INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
)""")


def _migrate_v24(con: sqlite3.Connection) -> None:
    # Hot query: the trash sidebar reads one owner's entries by recency.
    con.execute("CREATE INDEX IF NOT EXISTS idx_trash_owner ON trash_entries(owner, created_at)")


def _migrate_v25(con: sqlite3.Connection) -> None:
    # Legacy unlabeled checkpoints can be manual too. Preserve them;
    # retention applies only to explicitly classified automatic saves.
    if "kind" not in _cols(con, "project_snapshots"):
        con.execute("ALTER TABLE project_snapshots ADD COLUMN kind TEXT NOT NULL DEFAULT 'manual'")


def _migrate_v26(con: sqlite3.Connection) -> None:
    if "author_name" not in _cols(con, "suggestion_packages"):
        con.execute("ALTER TABLE suggestion_packages ADD COLUMN author_name TEXT NOT NULL DEFAULT ''")


def _migrate_v27(con: sqlite3.Connection) -> None:
    # Empty project folders: entries (modules, doc files, docs.folder) carry their folder in the path,
    # so only folders without content need a row of their own.
    con.execute("""CREATE TABLE IF NOT EXISTS project_folders (
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 path TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(project_id, path)
);""")


def _migrate_v28(con: sqlite3.Connection) -> None:
    # Who saved a project checkpoint (may delete/rename their own); '' for older rows.
    if "author" not in _cols(con, "project_snapshots"):
        con.execute("ALTER TABLE project_snapshots ADD COLUMN author TEXT NOT NULL DEFAULT ''")


def _migrate_v29(con: sqlite3.Connection) -> None:
    # Watch level per project and user (what reaches the inbox) + inbox links.
    con.execute("""CREATE TABLE IF NOT EXISTS project_watch (
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 username TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
 level TEXT NOT NULL CHECK(level IN ('mentions','proposals','all')),
 seen_at TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(project_id, username)
);""")
    cols = _cols(con, "notifications")
    for name in ("project_id", "ref", "actor"):
        if name not in cols:
            con.execute(f"ALTER TABLE notifications ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")


def _migrate_v30(con: sqlite3.Connection) -> None:
    # Document titles are unique per project folder, not per project: copies
    # and moves into another folder keep their name (modules already do).
    con.execute("DROP INDEX IF EXISTS idx_docs_project_title")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_project_folder_title "
                "ON docs(project_id, folder, title COLLATE NOCASE) "
                "WHERE project_id IS NOT NULL AND trashed=0")


def _migrate_v31(con: sqlite3.Connection) -> None:
    cols = _cols(con, "users")
    if "oidc_issuer" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN oidc_issuer TEXT NOT NULL DEFAULT ''")
    if "oidc_sub" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN oidc_sub TEXT NOT NULL DEFAULT ''")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oidc "
                "ON users(oidc_issuer, oidc_sub) "
                "WHERE oidc_issuer <> '' AND oidc_sub <> ''")


def _migrate_v32(con: sqlite3.Connection) -> None:
    # Reusable URL login tokens, hash-only like API keys.
    con.execute("""CREATE TABLE IF NOT EXISTS login_tokens (
 id TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE, last_used TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_login_tokens_hash ON login_tokens(token_hash)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_login_tokens_user ON login_tokens(username)")


def _migrate_v33(con: sqlite3.Connection) -> None:
    if "mode" not in _cols(con, "api_keys"):
        con.execute("ALTER TABLE api_keys ADD COLUMN mode TEXT NOT NULL DEFAULT 'auto'")
    con.execute("CREATE TABLE IF NOT EXISTS agent_log (id INTEGER PRIMARY KEY AUTOINCREMENT, key_id TEXT NOT NULL, "
                "tool TEXT NOT NULL, path TEXT NOT NULL DEFAULT '', ok INTEGER NOT NULL DEFAULT 1, at TEXT NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_agent_log_key ON agent_log(key_id, id)")


def _migrate_v34(con: sqlite3.Connection) -> None:
    # One file tree per project: modules (project_resources) and document attachments (files,
    # <files>/<doc_id>/<path>) become project files at <files>/<project_id>/<path>. Attachments of
    # a document in folder F land at F/path (clashes get -2, -3, ...); references that would miss
    # their file under the folder-relative compile are rewritten to "/<new path>". Bytes are copied:
    # a crash before the commit leaves the old files intact for the rerun; the startup sweep
    # (maintenance.reap_trash_dirs) removes <files>/<doc_id> once this step is committed.
    # Attachments of trashed documents go to the owner's trash, not into the live tree.
    import json
    import posixpath

    from backend import deps
    from backend.services import project_files as pf
    from backend.services import resources, snapshots, trash
    from backend.services.docfiles import file_type, store

    has_files, has_res = bool(_cols(con, "files")), bool(_cols(con, "project_resources"))
    base = deps.get_files_dir()
    maps: dict[str, dict[str, str]] = {}
    log = logging.getLogger(__name__)

    def add(pid: str, path: str, data: bytes) -> None:
        store.put(pid, path, data)
        con.execute("INSERT OR REPLACE INTO project_files(project_id,path,size,mtime,type,version,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (pid, path, len(data), time.time(), file_type(path), pf.version(data), now_iso()))

    def folder_of(d: sqlite3.Row) -> str:  # one folder rule (pf.doc_folder); a folder no file system can hold moves to the root
        try:
            folder = pf.doc_folder(d["folder"])
        except ValueError:
            log.warning("v34: document %s had folder %r, moved to the project root", d["id"], d["folder"])
            folder = ""
        title, n = d["title"], 2
        while folder != (d["folder"] or ""):  # the title yields when the target folder has it already
            try:
                con.execute("UPDATE docs SET folder=?,title=? WHERE id=?", (folder, title, d["id"]))
                break
            except sqlite3.IntegrityError:
                title, n = f'{d["title"]} ({n})', n + 1
        return folder

    def utf8(name: str) -> bool:
        try:
            name.encode("utf-8")
            return True
        except UnicodeEncodeError:
            return False

    def doc_text(d: sqlite3.Row) -> tuple[str, bytes | None]:  # empty or corrupt CRDT state: the text column wins, like sync does
        yjs = bytes(d["yjs"]) if d["yjs"] else None
        try:
            return pf.stored_text(d["content"] or "", yjs), yjs
        except ValueError:
            log.warning("v34: document %s has an unreadable Yjs state, using its text", d["id"])
            return d["content"] or "", None

    folders = {r[0]: r[1] or "" for r in con.execute("SELECT id,folder FROM docs")}
    old_trash = con.execute("SELECT id,kind,doc_id,name FROM trash_entries WHERE kind IN ('file','resource')").fetchall()  # before this step adds any
    for (pid,) in con.execute("SELECT id FROM projects").fetchall():
        owner = con.execute("SELECT owner FROM projects WHERE id=?", (pid,)).fetchone()[0]
        modules = {r[0]: r[1] or "" for r in con.execute("SELECT name,content FROM project_resources WHERE project_id=?", (pid,))} if has_res else {}
        docs = con.execute("SELECT id,title,folder,content,yjs,trashed FROM docs WHERE project_id=? ORDER BY trashed,created_at,id", (pid,)).fetchall()
        atts = []
        for d in docs:
            folders[d["id"]] = folder_of(d)
            names = {r[0] for r in con.execute("SELECT path FROM files WHERE doc_id=?", (d["id"],))} if has_files else set()
            on_disk = {e.path for e in store.list(d["id"])}
            if bad := {n for n in on_disk if not utf8(n)}:  # bytes that are no UTF-8 name (Linux): no path can hold them
                log.warning("v34: skipped attachments with undecodable names in %s: %r", d["id"], sorted(bad))
            atts.append((d["id"], folders[d["id"]], sorted(names | (on_disk - bad))))
        existing = [r[0] for r in con.execute("SELECT path FROM project_files WHERE project_id=? ORDER BY path", (pid,))]
        empty = [r[0] for r in con.execute("SELECT path FROM project_folders WHERE project_id=?", (pid,))]
        module_map, doc_maps = pf.legacy_paths(existing, list(modules), atts, empty)
        maps.update(doc_maps)
        attached = {old for local in doc_maps.values() for old in local}
        for name, new in module_map.items():
            text = modules[name]
            if new.lower().endswith(".typ"):
                text = pf.legacy_refs(text, posixpath.dirname(name), posixpath.dirname(new), {}, module_map)
                for m in resources.REF_RE.finditer(text):  # old compiles gave it the attachment of whichever document ran
                    hit = resources.resolve(posixpath.dirname(new), m.group(1))
                    if hit in attached and hit not in module_map:
                        log.warning("v34: module %s/%s quotes the attachment %r, check that path", pid, new, m.group(1))
            add(pid, new, text.encode())
        for d in docs:
            local = doc_maps[d["id"]]
            for old, new in local.items():
                src = base / d["id"] / old
                if not src.is_file():
                    log.warning("v34: attachment %s/%s missing, skipped", d["id"], old)
                    continue
                data = src.read_bytes()
                if new.lower().endswith(".typ"):
                    text = data.decode("utf-8", errors="surrogateescape")
                    data = pf.legacy_refs(text, posixpath.dirname(old), posixpath.dirname(new), local, module_map).encode("utf-8", errors="surrogateescape")
                if d["trashed"]:
                    trash.archive(con, owner, "file", new, data, project_id=pid, doc_id=d["id"])  # goes with the document when it is purged
                else:
                    add(pid, new, data)
            folder = folders[d["id"]]
            for snap in con.execute("SELECT id,content FROM snapshots WHERE doc_id=?", (d["id"],)).fetchall():
                fixed = pf.legacy_refs(snap["content"] or "", "", folder, local, module_map)
                if fixed != (snap["content"] or ""):
                    con.execute("UPDATE snapshots SET content=? WHERE id=?", (fixed, snap["id"]))
            text, yjs = doc_text(d)
            fixed = pf.legacy_refs(text, "", folder, local, module_map)
            if fixed != text:
                con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                            (new_id("s_"), d["id"], text, "project-files migration", now_iso()))
                snapshots.prune_snaps(con, d["id"])
                con.execute("UPDATE docs SET content=?,yjs=? WHERE id=?", (fixed, pf.yjs_with(yjs, fixed), d["id"]))
    for t in old_trash:
        if t["kind"] == "resource" or not t["doc_id"]:
            con.execute("UPDATE trash_entries SET kind='file' WHERE id=?", (t["id"],))
            continue
        name = maps.get(t["doc_id"], {}).get(t["name"]) or posixpath.join(folders.get(t["doc_id"]) or "", t["name"])
        con.execute("UPDATE trash_entries SET kind='file',doc_id='',name=?,project_id=COALESCE((SELECT project_id FROM docs WHERE id=?),project_id) WHERE id=?",
                    (name, t["doc_id"], t["id"]))
    for row in con.execute("SELECT id,files FROM suggestion_packages").fetchall():
        files = json.loads(row["files"])
        for f in files:
            if f.get("kind") == "resource":
                f["kind"] = "file"
                f.pop("doc_id", None)
            elif f.get("kind") == "file" and f.get("doc_id"):
                doc = f.pop("doc_id")
                folder = folders.get(doc) or ""
                f["path"] = maps.get(doc, {}).get(f.get("path", "")) or posixpath.join(folder, f.get("path", ""))
                if f.get("target"):
                    f["target"] = posixpath.join(folder, f["target"])
        con.execute("UPDATE suggestion_packages SET files=? WHERE id=?", (json.dumps(files, ensure_ascii=False, separators=(",", ":")), row["id"]))
    con.execute("DROP TABLE IF EXISTS files")
    con.execute("DROP TABLE IF EXISTS project_resources")


def _migrate_v35(con: sqlite3.Connection) -> None:
    # Version settings per project in their own table: the projects row goes to every member
    # (SELECT * in the sidebar payload), the Git token must not.
    con.execute("""CREATE TABLE IF NOT EXISTS project_versioning (
 project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
 auto_minutes INTEGER NOT NULL DEFAULT 30, auto_keep INTEGER NOT NULL DEFAULT 15,
 auto INTEGER NOT NULL DEFAULT 1, git INTEGER NOT NULL DEFAULT 0, git_head TEXT NOT NULL DEFAULT '',
 remote TEXT NOT NULL DEFAULT '', branch TEXT NOT NULL DEFAULT 'main', token TEXT NOT NULL DEFAULT '', -- encrypted, see project_git.seal
 push INTEGER NOT NULL DEFAULT 0, push_status TEXT NOT NULL DEFAULT '', pushed_at TEXT NOT NULL DEFAULT '', pushed_hash TEXT NOT NULL DEFAULT ''
)""")
    if "git_email" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN git_email TEXT NOT NULL DEFAULT ''")
    cols = _cols(con, "project_snapshots")
    for name in ("summary", "editors", "commit_hash"):
        if name not in cols:
            con.execute(f"ALTER TABLE project_snapshots ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")


def _migrate_v36(con: sqlite3.Connection) -> None:
    if "package_id" not in _cols(con, "comments"):
        con.execute("ALTER TABLE comments ADD COLUMN package_id TEXT NOT NULL DEFAULT ''")
    con.execute("CREATE INDEX IF NOT EXISTS idx_comments_pkg ON comments(doc_id, package_id)")


_MIGRATIONS: tuple[Callable[[sqlite3.Connection], None], ...] = (
    _migrate_v1, _migrate_v2, _migrate_v3, _migrate_v4,
    _migrate_v5, _migrate_v6, _migrate_v7, _migrate_v8, _migrate_v9, _migrate_v10,
    _migrate_v11, _migrate_v12, _migrate_v13, _migrate_v14, _migrate_v15, _migrate_v16, _migrate_v17, _migrate_v18, _migrate_v19, _migrate_v20, _migrate_v21, _migrate_v22, _migrate_v23, _migrate_v24, _migrate_v25, _migrate_v26, _migrate_v27, _migrate_v28, _migrate_v29, _migrate_v30, _migrate_v31, _migrate_v32, _migrate_v33, _migrate_v34, _migrate_v35, _migrate_v36,
)


_MIGRATE_RETRIES = 10


def _rollback_quiet(con: sqlite3.Connection) -> None:
    try:
        con.execute("ROLLBACK")
    except Exception:
        pass


def _begin_immediate(con: sqlite3.Connection) -> None:
    # Serialize parallel starters (init_db runs at import, so two workers
    # can migrate the same DB at once): take the write lock up-front,
    # backing off on locked/busy instead of crashing.
    for attempt in range(_MIGRATE_RETRIES):
        try:
            con.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if ("locked" not in msg and "busy" not in msg) or attempt + 1 >= _MIGRATE_RETRIES:
                raise
            _rollback_quiet(con)
            time.sleep(0.05 * (attempt + 1))
    raise sqlite3.OperationalError("database is locked")


def migrate(con: sqlite3.Connection) -> None:
    # Idempotent: every step checks before writing; applied versions recorded
    # so re-runs and fresh DBs converge to the same schema. Before any
    # pending step runs on a returning DB, VACUUM INTO a timestamped file
    # next to the DB (fresh DBs are skipped: nothing to lose).
    # Parallel-safe: each step runs in its own BEGIN IMMEDIATE txn with
    # busy-retry. A peer that commits the version first shows up as an
    # IntegrityError on the schema_version INSERT, which is swallowed
    # (the step itself is idempotent: IF NOT EXISTS / OR REPLACE), so the
    # second starter wins nothing and loses nothing.
    _begin_immediate(con)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS schema_version (v INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        con.commit()
    except Exception:
        _rollback_quiet(con)
        raise
    done = {r[0] for r in con.execute("SELECT v FROM schema_version").fetchall()}
    pending = [(i, step) for i, step in enumerate(_MIGRATIONS, start=1) if i not in done]
    if pending:
        backup_before_migrate(con, done)
    for i, step in pending:
        for attempt in range(_MIGRATE_RETRIES):
            _begin_immediate(con)
            try:
                step(con)
            except sqlite3.OperationalError as e:
                _rollback_quiet(con)
                msg = str(e).lower()
                if ("locked" not in msg and "busy" not in msg) or attempt + 1 >= _MIGRATE_RETRIES:
                    raise
                time.sleep(0.05 * (attempt + 1))
                continue
            except Exception:
                _rollback_quiet(con)
                raise
            try:
                con.execute("INSERT INTO schema_version (v, applied_at) VALUES (?,?)", (i, now_iso()))
                con.commit()
            except sqlite3.IntegrityError:
                _rollback_quiet(con)
                break  # peer applied this version first: their rows stand
            break


def init_db() -> None:
    con = connect()
    try:
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        migrate(con)
        con.commit()
    finally:
        con.close()


def role_on(con: sqlite3.Connection, user: str, doc_id: str) -> str | None:
    d = con.execute("SELECT owner, project_id FROM docs WHERE id=?", (doc_id,)).fetchone()
    if not d:
        return None
    if d["owner"] == user:
        return "owner"
    # Project membership is authoritative for members, including downgrades.
    if d["project_id"]:
        m = con.execute("SELECT role FROM project_members WHERE project_id=? AND username=?",
                        (d["project_id"], user)).fetchone()
        if m:
            return m["role"]
    s = con.execute("SELECT role FROM shares WHERE doc_id=? AND username=?", (doc_id, user)).fetchone()
    return s["role"] if s else None


def doc_role(user: str, doc_id: str) -> str | None:
    con = connect()
    try:
        return role_on(con, user, doc_id)
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
    from backend.services import quota

    with tx() as con:
        row = con.execute("SELECT owner,content,yjs,trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not row or row["trashed"]:
            return
        extra = len(text.encode("utf-8")) + len(yjs) - len(row["content"].encode("utf-8")) - len(row["yjs"] or b'')
        quota.check_quota(row["owner"], extra, con)
        con.execute("UPDATE docs SET yjs=?, content=?, updated_at=? WHERE id=?",
                    (yjs, text, now_iso(), doc_id))
    quota.invalidate_quota_cache(row["owner"])


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
