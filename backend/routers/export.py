"""Export routes (ZIP and single-document export)."""
from __future__ import annotations

import logging
import os
import re
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
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
        docs = [dict(r) for r in con.execute("SELECT id, title, content, folder,project_id FROM docs WHERE owner=? AND trashed=0 "
                                             "ORDER BY folder, title", (user,)).fetchall()]
        tpls = [dict(r) for r in con.execute("SELECT name, content FROM templates WHERE owner=? ORDER BY name",
                                             (user,)).fetchall()]
    finally:
        con.close()
    try:
        from backend.services import resources as _res
    except ImportError:
        _res = None  # type: ignore
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
                entries = list(fdir.rglob("*"))
            except OSError:
                entries = []
            for p in entries:
                try:
                    rel = p.relative_to(fdir).as_posix()
                except ValueError:
                    continue
                if p.is_symlink() or not p.is_file() or ".tmp." in p.name:
                    continue
                if any(seg.startswith(".") for seg in rel.split("/")):
                    continue
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
                if d["project_id"]:
                    prefix = "projects/" + d["project_id"] + "/" + prefix
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
                bundle = prefix + name + "-files/"
                have_rels: set[str] = set()
                local_texts: dict[str, str] = {}
                fdir = deps.get_files_dir() / d["id"]
                if fdir.is_dir():
                    try:
                        entries = sorted(fdir.rglob("*"))
                    except OSError:
                        entries = []
                    rels: list[tuple[str, Path]] = []
                    for p in entries:
                        try:
                            rel = p.relative_to(fdir).as_posix()
                        except ValueError:
                            continue
                        if not p.is_file() or p.is_symlink() or ".tmp." in p.name:
                            continue
                        if any(seg.startswith(".") for seg in rel.split("/")):
                            continue
                        rels.append((rel, p))
                    rels.sort(key=lambda t: t[0])
                    for rel, p in rels:
                        try:
                            sz = p.stat().st_size
                        except OSError:
                            continue
                        if sz <= UPLOAD_MAX:
                            total += sz
                            if total > EXPORT_MAX:
                                raise HTTPException(413, "Export too large (max 100 MB)")
                            try:
                                z.write(str(p), bundle + rel)
                                have_rels.add(rel)
                            except OSError as e:
                                log.warning("export write gone %s: %s", rel, e)
                                continue
                            if _res is not None and _res.kind_of(rel):
                                try:
                                    local_texts[rel] = p.read_text(encoding="utf-8", errors="replace")
                                except (OSError, ValueError):
                                    continue
                        else:
                            skipped.append(bundle + rel)
                # Per-doc resource closure (owner's reachable set, local wins):
                # the bundle carries what the doc compiles against, with
                # original relative paths, alongside the global templates/.
                if _res is not None:
                    try:
                        found = _res.doc_effective(user, txt, local_texts, d["id"])["resources"]
                    except Exception as e:
                        log.warning("backup closure failed: %s", e)
                        found = {}
                    for rn in sorted(found):
                        if rn in local_texts or rn in have_rels or ".tmp." in rn:
                            continue
                        clean = rn.replace("\\", "/").lstrip("/")
                        if not clean or ".." in clean.split("/"):
                            continue
                        b = found[rn].encode("utf-8")
                        total += len(b)
                        if total > EXPORT_MAX:
                            raise HTTPException(413, "Export too large (max 100 MB)")
                        z.writestr(bundle + clean, b)
                        have_rels.add(clean)
            for t in tpls:
                raw = (t["name"] or "").strip()
                stem, dot, ext = raw.rpartition(".")
                base = zip_name(stem if dot and ext.lower() in ("typ", "bib", "csv") else raw)
                suffix = "." + ext.lower() if dot and ext.lower() in ("typ", "bib", "csv") else ".typ"
                name, i = base, 2
                while ("templates/" + name + suffix).lower() in used:
                    name, i = f"{base} {i}", i + 1
                used.add(("templates/" + name + suffix).lower())
                txt = t["content"] or ""
                total += len(txt.encode("utf-8"))
                if total > EXPORT_MAX:
                    raise HTTPException(413, "Export too large (max 100 MB)")
                z.writestr("templates/" + name + suffix, txt)
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
def export_doc(doc_id: str, req: Request, format: str = "pdf", pdf_standard: str = "none",
               pages: str = "", ppi: str = "", user: str = Depends(deps.me)) -> Response:
    """Per-doc export via typst CLI (W2-A, MCP `export` parity).

    ?format=pdf|svg|png|zip. pdf = full multi-page PDF; svg/png = the single
    page directly, or a ZIP of all pages for multi-page docs; zip = source
    bundle (main.typ + sources at root paths, directly renderable).
    Read-only: any role with access may export (reviewer included). Own
    `export_doc` rate scope (isolated from the full `export.zip` backup);
    per-user `_export_lock` (429 while one runs). Sync endpoint: runs in a
    worker thread, the blocking CLI call never touches the event loop (B13).
    Compile errors -> 422 with diagnostics, missing typst -> 500, oversize
    -> 413. No migration. (MCP `export` shares the pipeline via op_export
    under the `mcp` scope, like `view`.) Resource closure (owner's
    reachable .typ/.bib/.csv, doc-local wins) is resolved once in
    `_collect_export_source`, so REST/MCP/view all compile the same set.

    2C options (CLI-only, the WASM bundle cannot do them): pdf_standard =
    none|1.7|2.0|a-1b|a-2b|a-3b|a-2u|a-3u|ua-1 (pdf only, typst 0.15.1
    --pdf-standard), pages like 1-3,5 (pdf/svg/png, --pages), ppi 72-300
    (png only, --ppi). Bad values -> 400 before any compile.
    """
    from backend import mcp_tools as _mt

    deps.limited(req, "export_doc", user)
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    fmt = _mt._check_export_format(format)  # single source (same 400 as MCP)
    std = _mt._check_pdf_standard(pdf_standard)
    pg = _mt._check_export_pages(pages)
    res = _mt._parse_export_ppi(ppi)  # str param: non-numeric -> 400, not 422
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
        # Single resolution point (nested locals + owner closure); no
        # wrapper-level re-merge, so REST/MCP/view stay in parity.
        main_text, files, skipped = _mt._collect_export_source(doc_id)
        payload, mime, filename = _mt.build_export_payload(
            row["title"], main_text, files, fmt, skipped, std, pg, res)
    finally:
        lock.release()
    return Response(content=payload, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
