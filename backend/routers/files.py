"""Document file routes (upload, download, text editing)."""
from __future__ import annotations

import logging
import os
import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse

from backend import deps
from backend.constants import MAX_TXT
from backend.schemas import FileText
from backend.services import quota as quota_svc
from backend.services.docfiles import _upload_locked, need_text, safe_name, touch_doc
from backend.services.locks import _named_lock

log = logging.getLogger("typst.main")

router = APIRouter()


@router.get("/api/docs/{doc_id}/files")
def list_files(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list") # own bucket: preview polls this per render, must not starve uploads
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    d = deps.get_files_dir() / doc_id
    out = []
    if d.is_dir():
        try:
            entries = sorted(d.iterdir())
        except OSError as e:
            log.warning("list_files list failed: %s", e)
            raise HTTPException(500, "File list failed") from e
        for p in entries:
            if p.is_file() and ".tmp." not in p.name:
                try:
                    st = p.stat()
                except OSError as e:
                    log.warning("list_files stat gone %s: %s", p.name, e)
                    continue
                out.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    return {"files": out}


@router.post("/api/docs/{doc_id}/files")
def upload_file(doc_id: str, f: UploadFile, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files")
    deps.check_doc_id(doc_id)
    deps.need_edit(user, doc_id)
    n = safe_name(f.filename or "")
    with _named_lock(f"upload:{doc_id}"):
        return _upload_locked(doc_id, f, n, user)


@router.get("/api/docs/{doc_id}/files/{name}")
def get_file(doc_id: str, name: str, req: Request, user: str = Depends(deps.me)) -> Response:
    deps.limited(req, "files")
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    p = deps.get_files_dir() / doc_id / safe_name(name)
    if not p.is_file():
        raise HTTPException(404, "File gone")
    if p.suffix.lower() == ".svg":
        try:
            data = p.read_bytes()
        except OSError as e:
            log.warning("get_file gone %s: %s", p.name, e)
            raise HTTPException(404, "File gone") from e
        return Response(content=data, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{p.name}"',
                                 "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
    try:
        return FileResponse(str(p), filename=p.name,
                            headers={"Content-Disposition": f'attachment; filename="{p.name}"',
                                     "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
    except (FileNotFoundError, RuntimeError, OSError) as e:
        log.warning("get_file gone %s: %s", p.name, e)
        raise HTTPException(404, "File gone") from e


@router.delete("/api/docs/{doc_id}/files/{name}")
def delete_file(doc_id: str, name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "files")
    deps.need_edit(user, doc_id)
    with _named_lock(f"upload:{doc_id}"):
        p = deps.get_files_dir() / doc_id / safe_name(name)
        if p.is_file():
            try:
                p.unlink()
            except OSError as e:
                log.warning("delete_file %s gone: %s", p.name, e)
        touch_doc(doc_id)
    return {"ok": True}


@router.get("/api/docs/{doc_id}/files/{name}/text")
def get_file_text(doc_id: str, name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "save") # same cadence as doc save, not the tight files bucket
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    p = deps.get_files_dir() / doc_id / need_text(name)
    if not p.is_file():
        raise HTTPException(404, "File gone")
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        log.warning("get_file_text gone %s: %s", p.name, e)
        raise HTTPException(404, "File gone") from e
    return {"name": p.name, "content": content}


@router.post("/api/docs/{doc_id}/files/{name}/text")
def save_file_text(doc_id: str, name: str, b: FileText, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "save") # autosave every SAVE_MS, like doc save (files bucket is for up/download)
    deps.need_edit(user, doc_id)
    if len(b.content) > MAX_TXT:
        raise HTTPException(400, "Max 200 KB")
    with _named_lock(f"upload:{doc_id}"):
        p = deps.get_files_dir() / doc_id / need_text(name)
        try:
            _old_sz = p.stat().st_size if p.is_file() else 0
        except OSError:
            _old_sz = 0
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning("save_file_text mkdir failed: %s", e)
            raise HTTPException(500, "Upload failed") from e
        try:
            old = p.read_bytes() if p.is_file() else None
        except OSError:
            old = None

        def _restore_text() -> None:
            try:
                if old is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(old)
            except OSError:
                pass

        tmp = p.parent / f"{p.name}.tmp.{secrets.token_hex(8)}"
        try:
            with quota_svc.quota_guard(deps._owner(doc_id, user),
                                       max(0, len(b.content.encode("utf-8")) - _old_sz),
                                       rollback=_restore_text):
                try:
                    tmp.write_text(b.content, encoding="utf-8")
                    os.replace(tmp, p)
                except OSError:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
        except sqlite3.OperationalError as e:
            raise deps.busy_503("save_file_text", e) from e
        touch_doc(doc_id)
    return {"ok": True}
