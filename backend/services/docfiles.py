"""Document file helpers shared by the REST routes and the MCP tools."""
from __future__ import annotations

import logging
import os
import re
import secrets
import sqlite3
from pathlib import Path

from fastapi import HTTPException, UploadFile

from backend import config, db, deps
from backend.constants import UPLOAD_MAX
from backend.services import quota as quota_svc

log = logging.getLogger("typst.main")


def safe_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "").name.strip().lstrip("."))[:100]
    if not n or Path(n).suffix.lower() not in deps.ALLOWED_IMG:
        raise HTTPException(400, "Only png/jpg/jpeg/svg/gif/webp/pdf/typ/bib/csv")
    if ".tmp." in n:
        raise HTTPException(400, "Reserved name")
    return n


def _upload_locked(doc_id: str, f: UploadFile, n: str, user: str) -> dict:
    try:
        max_files = config.load().MAX_FILES_PER_DOC
    except Exception:
        max_files = 200
    d = deps.get_files_dir() / doc_id
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("upload_file mkdir failed: %s", e)
        raise HTTPException(500, "Upload failed") from e
    try:
        pre = sum(1 for p in d.iterdir() if p.is_file() and p.name != n and ".tmp." not in p.name)
    except OSError as e:
        log.warning("upload_file list failed: %s", e)
        raise HTTPException(500, "File list failed") from e
    if pre >= max_files:
        raise HTTPException(400, "Too many files")
    tmp = d / f"{n}.tmp.{secrets.token_hex(8)}"
    size = 0
    try:
        with open(tmp, "wb") as fh:
            while True:
                blk = f.file.read(64 * 1024)
                if not blk:
                    break
                size += len(blk)
                if size > UPLOAD_MAX:
                    raise HTTPException(400, "Max 10 MB")
                fh.write(blk)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
    except HTTPException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except OSError as e:
        log.warning("upload_file write failed: %s", e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(500, "Upload failed") from e
    try:
        old = (d / n).read_bytes() if (d / n).is_file() else None
    except OSError:
        old = None

    def _restore_upload() -> None:
        try:
            if old is not None:
                (d / n).write_bytes(old)
            else:
                (d / n).unlink(missing_ok=True)
        except OSError:
            pass

    _up_owner = deps._owner(doc_id, user)
    try:
        with quota_svc.quota_guard(_up_owner, max(0, size - (len(old) if old is not None else 0)), rollback=_restore_upload):
            try:
                os.replace(tmp, d / n)
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            try:
                post = sum(1 for p in d.iterdir() if p.is_file() and ".tmp." not in p.name)
            except OSError as e:
                log.warning("upload_file recount failed: %s", e)
                raise HTTPException(500, "File list failed") from e
            if post > max_files:
                _restore_upload()
                raise HTTPException(400, "Too many files")
    except sqlite3.OperationalError as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise deps.busy_503("upload_file", e) from e
    except HTTPException:
        # Both 413 paths clean up tmp (pre-check never replaced it, post-check rolls back).
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    touch_doc(doc_id)
    return {"name": n, "size": size}


def need_text(name: str) -> str:
    n = safe_name(name)
    if Path(n).suffix.lower() not in deps.TEXT_SUFFIX:
        raise HTTPException(400, "Only typ/bib/csv as text")
    return n


def touch_doc(doc_id: str) -> None:
    con = db.connect()
    try:
        try:
            con.execute("UPDATE docs SET updated_at=? WHERE id=?", (db.now_iso(), doc_id))
            con.commit()
        except sqlite3.OperationalError as e:
            raise deps.busy_503("touch_doc", e) from e
    finally:
        con.close()
