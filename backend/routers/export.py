"""Export routes (ZIP and single-document export)."""
from __future__ import annotations

import logging
import os
import re
import tempfile
import zipfile
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from backend import config, db, deps, sync
from backend.constants import EXPORT_MAX, UPLOAD_MAX
from backend.services.locks import _export_lock

log = logging.getLogger("typst.main")

router = APIRouter()


def zip_name(s: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_.-]+", "_", s.strip())[:80].strip("._") or "document"
    return n


def prune_old_exports(max_age_s: int = 86400) -> None:
    try:
        data_dir = config.load().DATA_DIR
    except Exception:
        data_dir = deps.ROOT / "data"
    exp = data_dir / "exports"
    try:
        cut = datetime.now(UTC).timestamp() - max_age_s
        for p in exp.glob("job_*.zip"):
            try:
                if p.is_file() and p.stat().st_mtime < cut:
                    p.unlink()
            except OSError:
                logging.getLogger(__name__).warning("prune export failed: %s", p)
        for p in data_dir.glob("tmp*.zip"):
            try:
                if p.is_file() and p.stat().st_mtime < cut:
                    p.unlink()
            except OSError:
                logging.getLogger(__name__).warning("prune export-tmp failed: %s", p)
    except OSError as e:
        logging.getLogger(__name__).warning("prune exports failed: %s", e)


@router.get("/api/export.zip")
def export_zip(req: Request, background: BackgroundTasks, user: str = Depends(deps.me)) -> Response:
    deps.limited(req, "export")
    o = req.headers.get("origin", "") or req.headers.get("referer", "")
    if o:
        host = (req.headers.get("host", "") or "").split(",")[-1].strip().lower()
        if urlparse(o).netloc.lower() != host:
            log.warning("csrf-block %s", req.url.path)
            raise HTTPException(403, "Forbidden")
    # Defense in depth for this cookie-authed download: a cross-site top-level
    # navigation cannot carry the session usefully, so reject it when the
    # browser tells us where the request comes from. Only enforced when the
    # header is present (curl/TestClient send none).
    sfs = (req.headers.get("sec-fetch-site", "") or "").strip().lower()
    if sfs and sfs not in ("same-origin", "same-site", "none"):
        log.warning("csrf-block %s (sec-fetch-site=%s)", req.url.path, sfs)
        raise HTTPException(403, "Forbidden")
    lock = _export_lock(user)
    if not lock.acquire(blocking=False):
        raise HTTPException(429, "Export already running")
    try:
        return _export_zip(req, background, user)
    finally:
        lock.release()


def _export_zip(req: Request, background: BackgroundTasks, user: str) -> Response:
    prune_old_exports()
    con = db.connect()
    try:
        docs = [dict(r) for r in con.execute("SELECT id, title, content, folder FROM docs WHERE owner=? AND trashed=0 "
                                             "ORDER BY folder, title", (user,)).fetchall()]
        tpls = [dict(r) for r in con.execute("SELECT name, content FROM templates WHERE owner=? ORDER BY name",
                                             (user,)).fetchall()]
    finally:
        con.close()
    pre_bytes = 0
    for t in tpls:
        pre_bytes += len((t["content"] or "").encode("utf-8"))
        if pre_bytes > EXPORT_MAX:
            raise HTTPException(413, "Export too large (max 100 MB)")
    for d in docs:
        pre_bytes += len(d["content"].encode("utf-8"))
        fdir = deps.get_files_dir() / d["id"]
        if fdir.is_dir():
            try:
                entries = list(fdir.iterdir())
            except OSError:
                entries = []
            for p in entries:
                if p.is_file() and ".tmp." not in p.name:
                    try:
                        sz = p.stat().st_size
                    except OSError:
                        continue
                    if sz <= UPLOAD_MAX:
                        pre_bytes += sz
        if pre_bytes > EXPORT_MAX:
            raise HTTPException(413, "Export too large (max 100 MB)")
    deps.get_files_dir().parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, dir=deps.get_files_dir().parent, suffix=".zip")
        tmp.close()
    except OSError as e:
        log.warning("export tmp failed: %s", e)
        raise HTTPException(503, "Export busy, try again") from e
    try:
        used = set()
        total = 0
        skipped: list[str] = []
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
            for d in docs:
                prefix = (zip_name(d["folder"]) + "/") if d["folder"] else ""
                base = zip_name(d["title"])
                name, i = base, 2
                while (prefix + name + ".typ").lower() in used:
                    name, i = f"{base} {i}", i + 1
                used.add((prefix + name + ".typ").lower())
                live = sync.room_text(d["id"])
                txt = live if live is not None else d["content"]
                total += len(txt.encode("utf-8"))
                if total > EXPORT_MAX:
                    raise HTTPException(413, "Export too large (max 100 MB)")
                z.writestr(prefix + name + ".typ", txt)
                fdir = deps.get_files_dir() / d["id"]
                if fdir.is_dir():
                    try:
                        entries = sorted(fdir.iterdir())
                    except OSError:
                        entries = []
                    for p in entries:
                        if not p.is_file() or ".tmp." in p.name:
                            continue
                        try:
                            sz = p.stat().st_size
                        except OSError:
                            continue
                        if sz <= UPLOAD_MAX:
                            total += sz
                            if total > EXPORT_MAX:
                                raise HTTPException(413, "Export too large (max 100 MB)")
                            try:
                                z.write(str(p), prefix + name + "-files/" + p.name)
                            except OSError as e:
                                log.warning("export write gone %s: %s", p.name, e)
                                continue
                        else:
                            skipped.append(prefix + name + "-files/" + p.name)
            for t in tpls:
                raw = (t["name"] or "")
                if raw.lower().endswith(".typ"):
                    raw = raw[:-4]
                base = zip_name(raw)
                name, i = base, 2
                while ("templates/" + name + ".typ").lower() in used:
                    name, i = f"{base} {i}", i + 1
                used.add(("templates/" + name + ".typ").lower())
                txt = t["content"] or ""
                total += len(txt.encode("utf-8"))
                if total > EXPORT_MAX:
                    raise HTTPException(413, "Export too large (max 100 MB)")
                z.writestr("templates/" + name + ".typ", txt)
            if skipped:
                z.writestr("SKIPPED.txt", "Oversized files left out:\n" + "\n".join(skipped) + "\n")
        background.add_task(os.unlink, tmp.name)
        return FileResponse(tmp.name, media_type="application/zip",
                            filename="typst-backup.zip", background=background)
    except Exception as e:
        if not isinstance(e, HTTPException):
            log.warning("export failed")
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


@router.post("/api/docs/{doc_id}/export")
def export_doc(doc_id: str, req: Request, format: str = "pdf", user: str = Depends(deps.me)) -> Response:
    """Per-doc export via typst CLI (W2-A, MCP `export` parity).

    ?format=pdf|svg|png|zip. pdf = full multi-page PDF; svg/png = the single
    page directly, or a ZIP of all pages for multi-page docs; zip = source
    bundle (main.typ + files/). Read-only: any role with access may export
    (reviewer included). Own `export_doc` rate scope (isolated from the full
    `export.zip` backup); per-user `_export_lock` (429 while one runs).
    Sync endpoint: runs in a worker thread, the blocking CLI call never
    touches the event loop (B13). Compile errors -> 422 with diagnostics,
    missing typst -> 500, oversize -> 413. No migration. (MCP `export`
    shares the pipeline via op_export under the `mcp` scope, like `view`.)
    """
    from backend import mcp_tools as _mt

    deps.limited(req, "export_doc", user)
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    fmt = _mt._check_export_format(format)  # single source (same 400 as MCP)
    con = db.connect()
    try:
        row = con.execute("SELECT title FROM docs WHERE id=?", (doc_id,)).fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(404, "Doc gone")
    lock = _export_lock(user)
    if not lock.acquire(blocking=False):
        raise HTTPException(429, "Export already running")
    try:
        payload, mime, filename = _mt._export_doc_sync(doc_id, row["title"], fmt)
    finally:
        lock.release()
    return Response(content=payload, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
