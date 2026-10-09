"""Document file routes (upload, download, text editing)."""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse

from backend import db, deps
from backend.schemas import FileText
from backend.services import quota as quota_svc
from backend.services.docfiles import (
    _upload_locked,
    drop_file,
    need_text,
    safe_name,
    save_text_file,
    store,
    sync_doc_files,
    touch_doc,
)
from backend.services.locks import _named_lock
from backend.services.sidebar import emit_doc

log = logging.getLogger("typst.main")

router = APIRouter()


@router.get("/api/docs/{doc_id}/files")
def list_files(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list") # own bucket: preview polls this per render, must not starve uploads
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    try:
        sync_doc_files(doc_id)  # external writers (duplicate, MCP) heal here
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
    return {"name": n, "content": content}


@router.post("/api/docs/{doc_id}/files/{name:path}/text")
def save_file_text(doc_id: str, name: str, b: FileText, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "save") # autosave every SAVE_MS, like doc save (files bucket is for up/download)
    deps.need_edit(user, doc_id)
    n = need_text(name)
    with _named_lock(f"upload:{doc_id}"):
        try:
            save_text_file(doc_id, n, b.content, deps._owner(doc_id, user))
        except sqlite3.OperationalError as e:
            raise deps.busy_503("save_file_text", e) from e
    quota_svc.invalidate_quota_cache(deps._owner(doc_id, user))
    emit_doc(doc_id, "file")
    return {"ok": True}


@router.get("/api/docs/{doc_id}/files/{name:path}")
def get_file(doc_id: str, name: str, req: Request, user: str = Depends(deps.me)) -> Response:
    deps.limited(req, "files")
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
            gone = store.delete(doc_id, n)
        except OSError as e:
            log.warning("delete_file %s gone: %s", n, e)
            gone = False
        if gone:
            drop_file(doc_id, n)
            touch_doc(doc_id)
            quota_svc.invalidate_quota_cache(deps._owner(doc_id, user))
            emit_doc(doc_id, "file")
    return {"ok": True}
