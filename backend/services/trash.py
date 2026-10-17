"""Recoverable deletions for modules and document attachments."""
from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from backend import db
from backend.services import projects, quota
from backend.services.docfiles import file_type, store
from backend.services.locks import _named_lock
from backend.services.sidebar import emit_doc, notify_sidebar


def archive(con: sqlite3.Connection, owner: str, kind: str, name: str, content: bytes,
            project_id: str = "", doc_id: str = "", line: str = "", folder: str = "") -> str:
    """Insert one trash row and return its id (callers may need to undo
    their own insert, e.g. a failed FS delete that must keep the file)."""
    if kind not in ("personal", "resource", "file"):
        raise ValueError(f"unknown trash kind: {kind!r}")
    entry_id = db.new_id("tr_")
    con.execute("INSERT INTO trash_entries (id,owner,kind,project_id,doc_id,name,content,line,folder,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (entry_id, owner, kind, project_id, doc_id, name, content, line, folder, db.now_iso()))
    return entry_id


def restore(user: str, entry_id: str) -> dict:
    # Fixed lock order: trash lock first, upload lock second, DB tx last.
    # The tx is never held while acquiring a named lock. The old code took
    # trash -> tx -> upload (FS put + files INSERT inside the tx), which
    # deadlocked against delete_file's upload -> tx order and stalled every
    # other writer across disk I/O held under BEGIN IMMEDIATE.
    # NOTE: the upload lock is acquired below BEFORE any tx (threading.Lock
    # is not reentrant, so nesting it inside the tx path would self-deadlock).
    with _named_lock("trash:" + entry_id):
        preview_con = db.connect()
        try:
            preview = preview_con.execute(
                "SELECT kind, doc_id FROM trash_entries WHERE id=? AND owner=?",
                (entry_id, user)).fetchone()
            if preview is None:
                raise HTTPException(404, "Trash entry gone")
            kind0, doc0 = preview["kind"], preview["doc_id"]
        finally:
            preview_con.close()
        # Trash rows are immutable (INSERT/DELETE only), so the preview
        # stays valid under the trash lock.
        if kind0 not in ("personal", "resource") and doc0:
            with _named_lock("upload:" + doc0):
                return _restore_locked(user, entry_id)
        return _restore_locked(user, entry_id)


def _restore_locked(user: str, entry_id: str) -> dict:
    # Caller holds the trash lock (+ the upload lock for file kinds) and no
    # further lock is acquired below. FS writes happen outside the tx; the
    # tx only re-validates (row, doc, role, quota) and swaps the DB rows.
    written: tuple[str, str] | None = None
    row: sqlite3.Row | None = None
    name, kind = "", ""
    charged = user  # account whose quota gains the restored bytes
    try:
        snap_con = db.connect()
        try:
            snap = snap_con.execute("SELECT * FROM trash_entries WHERE id=? AND owner=?",
                                    (entry_id, user)).fetchone()
        finally:
            snap_con.close()
        if snap is None:
            raise HTTPException(404, "Trash entry gone")
        name, kind = snap["name"], snap["kind"]
        content_bytes = bytes(snap["content"])
        if kind == "personal":
            with db.tx() as con:
                row = con.execute("SELECT * FROM trash_entries WHERE id=? AND owner=?",
                                  (entry_id, user)).fetchone()
                if row is None:
                    raise HTTPException(404, "Trash entry gone")
                # Quota-neutral restore: the bytes leave trash (already
                # counted against the restorer) as copies land in the
                # template, so only the net delta may fail the cap.
                quota.check_quota(user, 0, con)
                con.execute("INSERT INTO templates(owner,name,content,line,folder,updated_at) VALUES (?,?,?,?,?,?)",
                            (user, name, content_bytes.decode(), row["line"], row["folder"], db.now_iso()))
                con.execute("DELETE FROM trash_entries WHERE id=?", (entry_id,))
        elif kind == "resource":
            with db.tx() as con:
                row = con.execute("SELECT * FROM trash_entries WHERE id=? AND owner=?",
                                  (entry_id, user)).fetchone()
                if row is None:
                    raise HTTPException(404, "Trash entry gone")
                projects.require(con, row["project_id"], user, edit=True)
                prow = con.execute("SELECT owner FROM projects WHERE id=?",
                                   (row["project_id"],)).fetchone()
                # Resource bytes stay charged to the project owner; the
                # entry's own trash bytes (restorer's bucket) only offset
                # the check when both buckets share an account.
                charged = prow["owner"] if prow else user
                projects.assert_resource_name_free(con, row["project_id"], name)
                quota.check_quota(charged, 0 if charged == user else len(content_bytes), con)
                con.execute("INSERT INTO project_resources VALUES (?,?,?,?)",
                            (row["project_id"], name, content_bytes.decode(), db.now_iso()))
                con.execute("DELETE FROM trash_entries WHERE id=?", (entry_id,))
        else:
            doc_id = snap["doc_id"]
            # Fail-fast FS guard before the authoritative tx below (still
            # under the upload lock, so no API/MCP writer can interleave;
            # lock-free healers only mirror disk into the table).
            if store.doc_path(doc_id, name).exists():
                raise HTTPException(409, "Name already exists; rename the existing file first")
            store.put(doc_id, name, content_bytes)
            written = (doc_id, name)
            stat = store.doc_path(*written).stat()
            with db.tx() as con:
                row = con.execute("SELECT * FROM trash_entries WHERE id=? AND owner=?",
                                  (entry_id, user)).fetchone()
                if row is None:
                    raise HTTPException(404, "Trash entry gone")
                doc = con.execute("SELECT owner,trashed,project_id FROM docs WHERE id=?", (row["doc_id"],)).fetchone()
                if doc is None:
                    # Permanent doc delete purges trash_entries; still give a
                    # sensible verdict for legacy ghost entries.
                    raise HTTPException(410, "Document was deleted permanently; this entry can no longer be restored")
                if doc["trashed"]:
                    raise HTTPException(409, "Restore the original document first")
                if db.role_on(con, user, row["doc_id"]) not in ("owner", "editor"):
                    raise HTTPException(403, "Insufficient permissions to restore this file")
                projects.assert_file_name_free(con, doc["project_id"], name)
                # files-table bytes stay charged to the doc owner; the
                # entry's own trash bytes (restorer's bucket) only offset
                # the check when both buckets share an account.
                charged = doc["owner"]
                quota.check_quota(charged, max(0, stat.st_size - (len(content_bytes) if charged == user else 0)), con)
                con.execute("INSERT INTO files(doc_id,path,size,mtime,type) VALUES (?,?,?,?,?)",
                            (row["doc_id"], name, stat.st_size, stat.st_mtime, file_type(name)))
                con.execute("DELETE FROM trash_entries WHERE id=?", (entry_id,))
    except Exception as error:
        if written:
            store.delete(*written)
        if isinstance(error, sqlite3.IntegrityError):
            raise HTTPException(409, "Name already exists; rename the existing entry first") from error
        raise
    quota.invalidate_quota_cache(user)
    if charged != user:
        quota.invalidate_quota_cache(charged)
    notify_sidebar(user)
    if charged != user:
        notify_sidebar(charged)
    assert row is not None
    if row["project_id"]:
        projects.notify(row["project_id"])
    if row["doc_id"]:
        emit_doc(row["doc_id"], "file")
    return {"kind": kind, "name": name, "project_id": row["project_id"], "doc_id": row["doc_id"]}
