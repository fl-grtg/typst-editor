"""Document file routes (upload, download, text editing)."""
from __future__ import annotations

import logging
import sqlite3
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse

from backend import db, deps
from backend.schemas import FileText
from backend.services import quota as quota_svc
from backend.services import trash
from backend.services.docfiles import (
    _upload_locked,
    need_text,
    safe_name,
    save_text_file,
    store,
    sync_doc_files,
    touch_doc,
)
from backend.services.locks import _named_lock
from backend.services.project_history import auto_document
from backend.services.sidebar import emit_doc, notify_sidebar

log = logging.getLogger("typst.main")

router = APIRouter()


@router.get("/api/docs/{doc_id}/files")
def list_files(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list") # own bucket: preview polls this per render, must not starve uploads
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    try:
        # A restore/rename may have published bytes before committing its
        # metadata. Reconciliation must not publish that intermediate state.
        with _named_lock(f"upload:{doc_id}"):
            sync_doc_files(doc_id)
    except HTTPException as e:
        if e.status_code == 503:
            raise
        log.warning("list_files sync failed: %s", e.detail)
    con = db.connect()
    try:
        rows = con.execute("SELECT path, size, mtime FROM files WHERE doc_id=? ORDER BY path",
                           (doc_id,)).fetchall()
    except sqlite3.OperationalError as e:
        raise deps.busy_503("list_files", e) from e
    finally:
        con.close()
    return {"files": [{"name": r["path"], "size": r["size"], "mtime": r["mtime"]} for r in rows]}


@router.post("/api/docs/{doc_id}/files")
def upload_file(doc_id: str, f: UploadFile, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files")
    deps.check_doc_id(doc_id)
    deps.need_edit(user, doc_id)
    n = safe_name(f.filename or "")
    with _named_lock(f"upload:{doc_id}"):
        out = _upload_locked(doc_id, f, n, user)
    quota_svc.invalidate_quota_cache(deps._owner(doc_id, user))
    auto_document(doc_id)
    emit_doc(doc_id, "file")
    return out


@router.get("/api/docs/{doc_id}/files/{name:path}/text")
def get_file_text(doc_id: str, name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "save") # same cadence as doc save, not the tight files bucket
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    n = need_text(name)
    try:
        content = store.get(doc_id, n).decode("utf-8", errors="replace")
    except FileNotFoundError:
        raise HTTPException(404, "File gone") from None
    except OSError as e:
        log.warning("get_file_text gone %s: %s", n, e)
        raise HTTPException(404, "File gone") from e
    return {"name": n, "content": content, "version": sha256(content.encode("utf-8")).hexdigest()}


@router.post("/api/docs/{doc_id}/files/{name:path}/text")
def save_file_text(doc_id: str, name: str, b: FileText, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "save") # autosave every SAVE_MS, like doc save (files bucket is for up/download)
    deps.need_edit(user, doc_id)
    n = need_text(name)
    with _named_lock(f"upload:{doc_id}"):
        try:
            if b.version is not None:
                try:
                    current = store.get(doc_id, n).decode("utf-8", errors="replace")
                except FileNotFoundError:
                    current = ""
                if sha256(current.encode("utf-8")).hexdigest() != b.version:
                    raise HTTPException(409, "File changed meanwhile; keep your draft and reload the file")
            save_text_file(doc_id, n, b.content, deps._owner(doc_id, user))
        except sqlite3.OperationalError as e:
            raise deps.busy_503("save_file_text", e) from e
    quota_svc.invalidate_quota_cache(deps._owner(doc_id, user))
    auto_document(doc_id)
    emit_doc(doc_id, "file")
    return {"ok": True, "version": sha256(b.content.encode("utf-8")).hexdigest()}


@router.get("/api/docs/{doc_id}/files/{name:path}")
def get_file(doc_id: str, name: str, req: Request, user: str = Depends(deps.me)) -> Response:
    deps.limited(req, "file_read") # preview loads every attachment; do not consume the upload bucket
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    n = safe_name(name)
    p = store.doc_path(doc_id, n)
    if not p.is_file():
        raise HTTPException(404, "File gone")
    if p.suffix.lower() == ".svg":
        try:
            data = p.read_bytes()
        except OSError as e:
            log.warning("get_file gone %s: %s", n, e)
            raise HTTPException(404, "File gone") from e
        return Response(content=data, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{p.name}"',
                                 "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
    try:
        return FileResponse(str(p), filename=p.name,
                            headers={"Content-Disposition": f'attachment; filename="{p.name}"',
                                     "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
    except (FileNotFoundError, RuntimeError, OSError) as e:
        log.warning("get_file gone %s: %s", n, e)
        raise HTTPException(404, "File gone") from e


@router.delete("/api/docs/{doc_id}/files/{name:path}")
def delete_file(doc_id: str, name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "files")
    deps.need_edit(user, doc_id)
    n = safe_name(name)
    with _named_lock(f"upload:{doc_id}"):
        try:
            content = store.get(doc_id, n)
        except FileNotFoundError:
            try:
                with db.tx() as con:
                    if deps._tx_role(con, user, doc_id) not in ("owner", "editor"):
                        raise HTTPException(403, "Reviewer can only comment")
                    con.execute("DELETE FROM files WHERE doc_id=? AND path=?", (doc_id, n))
            except sqlite3.OperationalError as e:
                raise deps.busy_503("delete_file", e) from e
            # Same epilogue as a successful delete: the files-row the UI
            # was showing just disappeared.
            touch_doc(doc_id)
            quota_svc.invalidate_quota_cache(deps._owner(doc_id, user))
            emit_doc(doc_id, "file")
            notify_sidebar(user)
            return {"ok": True}
        except OSError as e:
            log.error("delete_file %s unreadable: %s", n, e)
            raise HTTPException(500, "Delete failed") from e
        with db.tx() as con:
            if deps._tx_role(con, user, doc_id) not in ("owner", "editor"):
                raise HTTPException(403, "Reviewer can only comment")
            owner_row = con.execute("SELECT owner,project_id FROM docs WHERE id=?", (doc_id,)).fetchone()
            if not owner_row:
                raise HTTPException(404, "Doc gone")
            # Trash is charged to the doc owner (files/quota count toward
            # the owner too): archiving under the deleter would move the
            # quota charge to the wrong account and hide the entry from
            # the owner's trash list.
            entry_id = trash.archive(con, owner_row["owner"], "file", n, content,
                                     project_id=owner_row["project_id"] or "", doc_id=doc_id)
            con.execute("DELETE FROM files WHERE doc_id=? AND path=?", (doc_id, n))
        try:
            gone = store.delete(doc_id, n)
        except OSError as e:
            log.warning("delete_file %s gone: %s", n, e)
            gone = False
        if not gone:
            # Undo the FS-delete attempt: only the trash row created above
            # may go (older same-name entries keep their copy), and
            # sync_doc_files runs OUTSIDE the tx — it opens its own
            # connection and would self-block inside BEGIN IMMEDIATE.
            try:
                sync_doc_files(doc_id)
            except HTTPException:
                pass
            with db.tx() as con:
                con.execute("DELETE FROM trash_entries WHERE id=?", (entry_id,))
            raise HTTPException(500, "Delete failed")
        touch_doc(doc_id)
        quota_svc.invalidate_quota_cache(deps._owner(doc_id, user))
        auto_document(doc_id)
        emit_doc(doc_id, "file")
        notify_sidebar(user)
        if owner_row["owner"] != user:
            notify_sidebar(owner_row["owner"])
    return {"ok": True}
