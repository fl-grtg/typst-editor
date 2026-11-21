"""Typst compile sandbox: page renders (cached) and exports for REST and the agent tools.

ENTRY is the compile entry file inside the temp dir; a document is its title, never a file name.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading as _compile_threading
import zipfile
from contextlib import contextmanager as _compile_cm
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from mcp.types import Annotations

from backend import db, sync
from backend.constants import ENTRY, EXPORT_FORMATS, EXPORT_MAX, UPLOAD_MAX
from backend.services import quota as quota_svc

log = logging.getLogger("typst.render")



def _bad(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(code, msg)


def _files_dir() -> Path:
    return quota_svc.files_dir()

VIEW_MAX_PAGES = 20
VIEW_MAX_NUM = 20
VIEW_MAX_SIDE = 1280
VIEW_TIMEOUT = 10.0
VIEW_CACHE_MAX = 20
VIEW_CACHE_BYTES = 20 * 1024 * 1024
VIEW_SRC_MAX = 50 * 1024 * 1024
VIEW_BASE_PPI = 144
VIEW_MIN_SCALE = 0.5
VIEW_MAX_SCALE = 3.0



def _expand_pages(pages: str) -> list[int]:
    """Validate pages spec and return sorted unique page numbers.

    Format: comma-separated "N" or "A-B" parts, e.g. "2", "1-3", "1-3,5".
    Page numbers 1..VIEW_MAX_NUM, at most VIEW_MAX_PAGES pages per call.
    Raises HTTPException 400 on invalid input.
    """
    if not pages or not isinstance(pages, str):
        raise _bad("pages 1-20 only (e.g. 1-5, 6-10 or 2)")
    if len(pages) > 200:
        raise _bad("pages 1-20 only (e.g. 1-5, 6-10 or 2)")
    seen: list[int] = []
    try:
        for raw in pages.split(","):
            part = raw.strip()
            if not part:
                raise _bad("pages 1-20 only (e.g. 1-5, 6-10 or 2)")
            nums = [int(x) for x in part.split("-")]
            if len(nums) > 2:
                raise _bad("pages 1-20 only (e.g. 1-5, 6-10 or 2)")
            if any(not 1 <= x <= VIEW_MAX_NUM for x in nums):
                raise _bad("pages 1-20 only (e.g. 1-5, 6-10 or 2)")
            if len(nums) == 2 and nums[0] > nums[1]:
                raise _bad("pages 1-20 only (e.g. 1-5, 6-10 or 2)")
            lo, hi = (nums[0], nums[0]) if len(nums) == 1 else (nums[0], nums[1])
            for p in range(lo, hi + 1):
                if p not in seen:
                    seen.append(p)
    except ValueError:
        raise _bad("pages 1-20 only (e.g. 1-5, 6-10 or 2)") from None
    if not seen or len(seen) > VIEW_MAX_PAGES:
        raise _bad(f"pages 1-20 only, max {VIEW_MAX_PAGES} per call (e.g. 1-5, 6-10 or 2)")
    return sorted(seen)


def _pages_ok(pages: str) -> bool:
    if not pages or not isinstance(pages, str):
        return False
    try:
        _expand_pages(pages)
    except HTTPException:
        return False
    return True


def _parse_typst_diagnostics(stderr: str, level: str = "error") -> list[dict]:
    """Parse typst CLI stderr into [{file, line, col, message}] for errors (or warnings)."""
    diags: list[dict] = []
    if not stderr:
        return diags
    # Typst CLI prints "error: <msg>\n --> <entry>:line:col" blocks;
    # fall back to one entry per "error:" line when no position is found.
    blocks = re.split(r"(?m)^(?=error:|warning:)", stderr.strip())
    for b in blocks:
        b = b.strip()
        if not b or not b.startswith(level + ":"):
            continue
        first, _, rest = b.partition("\n")
        msg = first[len(level) + 1:].strip() or "compile error"
        m = re.search(r"([^\s:]+\.typ):(\d+):(\d+)", b)
        if m:
            try:
                line, col = int(m.group(2)), int(m.group(3))
            except ValueError:
                line, col = None, None
            diags.append({"file": m.group(1), "line": line, "col": col, "message": msg})
        else:
            # Multi-line message without position: keep first 300 chars.
            detail = (rest.strip().split("\n")[0].strip() if rest.strip() else "")
            full = f"{msg} {detail}".strip()[:300] if detail else msg[:300]
            diags.append({"file": None, "line": None, "col": None, "message": full})
    if not diags and level == "error":
        # Unknown format: single truncated entry so callers always get context.
        diags.append({"file": None, "line": None, "col": None,
                      "message": stderr.strip()[:300] or "compile error"})
    return diags


_TYPST_TAG: str | None = None


def _typst_tag() -> str:
    """Cache-busting salt: fonts/packages/env changes alter the render.

    B7: runs inside the same compile sandbox as every other typst call
    (slot + whitelisted env + rlimit preexec). A full slot queue (503) or
    any sandbox failure falls back to "unknown" instead of raising, so view
    caching never hard-fails on contention.
    """
    global _TYPST_TAG
    if _TYPST_TAG is None:
        try:
            exe = shutil.which("typst") or "typst"
            try:
                root = _files_dir()
            except Exception:
                root = Path(tempfile.gettempdir())
            try:
                with _compile_slot():
                    try:
                        env = _typst_env(root)
                    except HTTPException as e:
                        log.warning("typst tag env failed, use unknown: %s", e.detail)
                        _TYPST_TAG = "unknown"
                        return _TYPST_TAG
                    except Exception as e:
                        log.warning("typst tag env failed, use unknown: %s", e)
                        _TYPST_TAG = "unknown"
                        return _TYPST_TAG
                    try:
                        cwd = str(root) if Path(root).is_dir() else None
                    except Exception:
                        cwd = None
                    p = subprocess.run([exe, "--version"], capture_output=True, timeout=10,
                                       env=env, preexec_fn=_subprocess_preexec(), cwd=cwd)
            except HTTPException as e:
                if getattr(e, "status_code", 0) == 503:
                    log.warning("typst tag busy, use unknown")
                    _TYPST_TAG = "unknown"
                    return _TYPST_TAG
                raise
            _TYPST_TAG = (p.stdout or b"").decode("utf-8", "replace").strip()[:80] if p.returncode == 0 else "unknown"
        except Exception as e:
            log.warning("typst tag failed, use unknown: %s", e)
            _TYPST_TAG = "unknown"
    return _TYPST_TAG


# --- view (M3, PR4 paging): render doc pages as PNG via typst CLI ---

# 1C compile sandbox: at most COMPILE_MAX_CONCURRENT typst processes, with
# COMPILE_QUEUE_MAX waiters; beyond that -> HTTP 503 + Retry-After (callers
# must back off). QUEUE_MAX/TIMEOUT/RETRY_AFTER are read live so tests can
# monkeypatch them; MAX_CONCURRENT sizes _COMPILE_SLOTS once at import (patch
# + reimport to change it).
COMPILE_MAX_CONCURRENT = 2
COMPILE_QUEUE_MAX = 4
COMPILE_QUEUE_TIMEOUT_S = 30.0
COMPILE_RETRY_AFTER_S = 5
# Memory/CPU caps for the typst child (preexec_fn, POSIX only).
COMPILE_MEM_BYTES = 1_000_000_000
COMPILE_CPU_S = 30
COMPILE_FSIZE_BYTES = 100 * 1024 * 1024
# Env whitelist for the typst child (1C: never leak os.environ, in particular
# never REGISTRATION_INVITE_TOKEN or other server secrets into compile env).
COMPILE_ENV_ALLOW = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP", "TZ",
    "SYSTEMROOT", "WINDIR", "FONTCONFIG_PATH",
})

_COMPILE_SLOTS = _compile_threading.Semaphore(COMPILE_MAX_CONCURRENT)
_COMPILE_LOCK = _compile_threading.Lock()
_COMPILE_WAITING = 0

_VIEW_CACHE: dict[str, dict] = {}
_VIEW_TOTALS: dict[str, int] = {}


def _content_hash(doc_id: str, main_text: str, files: list[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    h.update(_typst_tag().encode("utf-8"))
    h.update(b"\0")
    h.update(main_text.encode("utf-8"))
    for name, data in files:
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(data)
    return f"{doc_id}:{h.hexdigest()}"


def _view_key(doc_id: str, main_text: str, files: list[tuple[str, bytes]],
              pages: str, ppi: int = VIEW_BASE_PPI) -> str:
    return f"{_content_hash(doc_id, main_text, files)}:{pages}:{ppi}:{VIEW_MAX_SIDE}"


def _view_cache_get(key: str) -> dict | None:
    hit = _VIEW_CACHE.pop(key, None)
    if hit is None:
        return None
    _VIEW_CACHE[key] = hit  # LRU refresh
    return hit


def _view_cache_put(key: str, entry: dict) -> None:
    new_size = sum(len(b) for b in entry["pngs"])
    while len(_VIEW_CACHE) >= VIEW_CACHE_MAX or (
            _VIEW_CACHE and sum(sum(len(b) for b in e["pngs"]) for e in _VIEW_CACHE.values()) + new_size > VIEW_CACHE_BYTES):
        _VIEW_CACHE.pop(next(iter(_VIEW_CACHE)), None)
    _VIEW_CACHE[key] = entry


def _png_bytes(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _compile_503() -> HTTPException:
    return HTTPException(status_code=503, detail="Compile busy, try again",
                         headers={"Retry-After": str(COMPILE_RETRY_AFTER_S)})


@_compile_cm
def _compile_slot():
    """Hold one compile slot (1C sandbox). 503 + Retry-After when full."""
    global _COMPILE_WAITING
    # Fast path: free slot, no queue accounting.
    try:
        got = _COMPILE_SLOTS.acquire(blocking=False)
    except Exception as e:
        log.warning("compile slot acquire failed: %s", e)
        raise _compile_503() from e
    if got:
        try:
            yield
        finally:
            try:
                _COMPILE_SLOTS.release()
            except Exception as e:
                log.warning("compile slot release failed: %s", e)
        return
    # All slots busy: bounded queue, else 503 immediately.
    with _COMPILE_LOCK:
        if _COMPILE_WAITING >= COMPILE_QUEUE_MAX:
            raise _compile_503()
        _COMPILE_WAITING += 1
    try:
        try:
            ok = _COMPILE_SLOTS.acquire(timeout=COMPILE_QUEUE_TIMEOUT_S)
        except Exception as e:
            log.warning("compile slot queued acquire failed: %s", e)
            raise _compile_503() from e
        if not ok:
            raise _compile_503()
        try:
            yield
        finally:
            try:
                _COMPILE_SLOTS.release()
            except Exception as e:
                log.warning("compile slot release failed: %s", e)
    finally:
        with _COMPILE_LOCK:
            _COMPILE_WAITING -= 1


def _compile_preexec() -> None:
    """Child-side rlimits for typst (1C): 1 GB AS, 30s CPU, 100 MB files."""
    _res: Any
    try:
        import resource as _res
    except ImportError as e:
        log.debug("compile preexec: resource unavailable: %s", e)
        return
    try:
        _res.setrlimit(_res.RLIMIT_AS, (COMPILE_MEM_BYTES, COMPILE_MEM_BYTES))
    except (ValueError, OSError) as e:
        log.warning("compile preexec RLIMIT_AS failed: %s", e)
    try:
        _res.setrlimit(_res.RLIMIT_CPU, (COMPILE_CPU_S, COMPILE_CPU_S))
    except (ValueError, OSError) as e:
        log.warning("compile preexec RLIMIT_CPU failed: %s", e)
    try:
        _res.setrlimit(_res.RLIMIT_FSIZE, (COMPILE_FSIZE_BYTES, COMPILE_FSIZE_BYTES))
    except (ValueError, OSError) as e:
        log.warning("compile preexec RLIMIT_FSIZE failed: %s", e)


def _subprocess_preexec():
    # preexec_fn only works on POSIX; on Windows pass None.
    try:
        import sys as _sys
        if _sys.platform == "win32":
            return None
    except Exception as e:
        log.warning("compile preexec platform check failed: %s", e)
        return None
    return _compile_preexec


def _typst_env(root: Path) -> dict:
    # Container runs as USER 999: typst's package cache defaults to a
    # non-writable location, so any @preview import
    # fails with "failed to create temporary package directory: Permission
    # denied". Point it at DATA_DIR/typst-cache (persistent, survives
    # views) with a tmp fallback. TYPST_PACKAGE_CACHE_PATH is the
    # documented override (typst 0.15.1, also as --package-cache-path);
    # XDG_CACHE_HOME covers the dirs-crate fallback on Linux.
    # 1C: whitelist env (never dict(os.environ): that leaks
    # REGISTRATION_INVITE_TOKEN and other secrets into the child).
    try:
        persistent = _files_dir().parent / "typst-cache"
        persistent.mkdir(parents=True, exist_ok=True)
        cache_home = str(persistent)
    except OSError:
        try:
            cache_home = str(root / "typst-cache")
            Path(cache_home).mkdir(exist_ok=True)
        except OSError as e:
            raise _bad(f"compile failed: {e}", 500) from e
    env: dict[str, str] = {}
    for k in COMPILE_ENV_ALLOW:
        try:
            v = os.environ.get(k)
        except Exception as e:
            log.warning("compile env read %s failed: %s", k, e)
            continue
        if v:
            env[k] = v
    # Minimal PATH fallback so `typst` resolves even with a bare env.
    if not env.get("PATH"):
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    env["TYPST_PACKAGE_CACHE_PATH"] = cache_home
    env["XDG_CACHE_HOME"] = cache_home
    return env


def _pdf_page_count(pdf_bytes: bytes) -> int | None:
    """Count pages in PDF bytes via /Type /Page markers. None when unknown."""
    try:
        n = len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))
        return n if n > 0 else None
    except Exception as e:
        log.warning("pdf page count failed: %s", e)
        return None


def _page_no(path: Path) -> int:
    """page-10.png sorts after page-9.png: the number in the name, not the text, decides."""
    m = re.search(r"(\d+)\D*$", path.stem)
    return int(m.group(1)) if m else 0


def _typst_page_files(root: Path, typst: str) -> int | None:
    """Render every page as SVG and count the files: no PDF object parsing."""
    try:
        (root / "__pages__").mkdir(exist_ok=True)  # own output folder: a user file named out-1.svg is no rendered page
    except OSError as e:
        log.warning("svg pages dir failed: %s", e)
        return None
    cmd = [typst, "compile", "--format", "svg", ENTRY, "__pages__/p-{p}.svg"]
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True,
                              timeout=VIEW_TIMEOUT, env=_typst_env(root),
                              preexec_fn=_subprocess_preexec())
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning("svg pages compile failed: %s", e)
        return None
    if proc.returncode != 0:
        return None
    try:
        return len(list((root / "__pages__").glob("p-*.svg"))) or None
    except OSError as e:
        log.warning("svg pages count failed: %s", e)
        return None


def _compile_pngs(main_text: str, files: list[tuple[str, bytes]],
                  pages: str, ppi: int = VIEW_BASE_PPI) -> list[bytes]:
    """Temp-dir typst compile, 10s timeout. Returns PNG bytes (<=20, longest side <=1280)."""
    with _compile_slot():
        typst = shutil.which("typst")
        if not typst:
            raise _bad("typst CLI missing (Dockerfile installs it)", 500)
        try:
            from PIL import Image as _Image
        except ImportError as e:
            raise _bad(f"render failed: {e}", 500) from e

        with tempfile.TemporaryDirectory(prefix="mcp-view-") as tmp:
            root = Path(tmp)
            try:
                (root / ENTRY).write_text(main_text, encoding="utf-8")
                for name, data in files:
                    if ".tmp." in name:
                        continue
                    dest = root / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
            except OSError as e:
                raise _bad(f"compile failed: {e}", 500) from e
            (root / "__shots__").mkdir(exist_ok=True)  # own output folder: uploaded page-*.png files are never returned as pages
            cmd = [typst, "compile", "--format", "png", "--ppi", str(ppi),
                   "--pages", pages, ENTRY, "__shots__/page-{p}.png"]
            env = _typst_env(root)
            try:
                proc = subprocess.run(cmd, cwd=tmp, capture_output=True, timeout=VIEW_TIMEOUT, env=env,
                                      preexec_fn=_subprocess_preexec())
            except subprocess.TimeoutExpired as e:
                raise _bad("compile timed out (10s)", 500) from e
            except OSError as e:
                raise _bad(f"compile failed: {e}", 500) from e
            if proc.returncode != 0:
                raw = (proc.stderr or b"").decode("utf-8", "replace").strip()
                diags = _parse_typst_diagnostics(raw)
                short = raw.strip()[-500:] or "unknown"
                raise HTTPException(422, {"message": f"compile error: {short}",
                                          "diagnostics": diags})
            shots = sorted((root / "__shots__").glob("page-*.png"), key=_page_no)[:VIEW_MAX_PAGES]
            if not shots:
                raise _bad("no pages rendered", 500)
            out = []
            for shot in shots:
                try:
                    with _Image.open(shot) as im:
                        im.load()
                        side = max(im.width, im.height)
                        if side > VIEW_MAX_SIDE:
                            s = VIEW_MAX_SIDE / side
                            out.append(_png_bytes(im.resize(
                                (round(im.width * s), round(im.height * s)))))
                        else:
                            out.append(_png_bytes(im))
                except OSError as e:
                    raise _bad(f"render failed: {e}", 500) from e
            return out


def _compile_pdf_pages(main_text: str, files: list[tuple[str, bytes]]) -> int | None:
    """Count every page of a compile. SVG files first (stable), PDF markers as fallback."""
    with _compile_slot():
        typst = shutil.which("typst")
        if not typst:
            raise _bad("typst CLI missing (Dockerfile installs it)", 500)
        with tempfile.TemporaryDirectory(prefix="mcp-view-total-") as tmp:
            root = Path(tmp)
            try:
                (root / ENTRY).write_text(main_text, encoding="utf-8")
                for name, data in files:
                    if ".tmp." in name:
                        continue
                    dest = root / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
            except OSError as e:
                log.warning("pdf-pages write failed: %s", e)
                return None
            n = _typst_page_files(root, typst)
            if n is not None:
                return n
            cmd = [typst, "compile", "--format", "pdf", ENTRY, "out.pdf"]
            try:
                proc = subprocess.run(cmd, cwd=tmp, capture_output=True,
                                      timeout=VIEW_TIMEOUT, env=_typst_env(root),
                                      preexec_fn=_subprocess_preexec())
            except (subprocess.TimeoutExpired, OSError) as e:
                log.warning("pdf-pages compile failed: %s", e)
                return None
            if proc.returncode != 0:
                return None
            try:
                return _pdf_page_count((root / "out.pdf").read_bytes())
            except OSError as e:
                log.warning("pdf-pages read failed: %s", e)
                return None


_VIEW_TOTALS_LOCK = _compile_threading.Lock()  # the counts run in worker threads: LRU refresh and eviction must not interleave


def _total_pages_exact(doc_id: str, main_text: str,
                       files: list[tuple[str, bytes]]) -> int | None:
    """Rendered page count (cached), None when it could not be counted right now."""
    key = _content_hash(doc_id, main_text, files)
    with _VIEW_TOTALS_LOCK:
        hit = _VIEW_TOTALS.pop(key, None)
        if hit is not None:
            _VIEW_TOTALS[key] = hit  # LRU refresh
            return hit
    try:
        n = _compile_pdf_pages(main_text, files)
    except HTTPException:
        n = None
    if n is None:
        return None  # transient failure (busy slot, timeout): never cached
    with _VIEW_TOTALS_LOCK:
        while len(_VIEW_TOTALS) >= VIEW_CACHE_MAX:
            _VIEW_TOTALS.pop(next(iter(_VIEW_TOTALS)), None)
        _VIEW_TOTALS[key] = n
    return n


def _total_pages_cached(doc_id: str, main_text: str,
                        files: list[tuple[str, bytes]], fallback: int) -> int:
    """Total doc pages via cached page count, fallback = max requested page."""
    n = _total_pages_exact(doc_id, main_text, files)
    return fallback if n is None else n


def _view_result(pngs: list[bytes], cache_hit: bool, last_seen: str,
                 total_pages: int, pages: str = "1-5", scale: float = 1.0) -> ToolResult:
    text = f"{len(pngs)} page(s) rendered (pages {pages}, {total_pages} total)"
    ann = Annotations(audience=["user"], priority=0.9)
    return ToolResult(
        content=[text, *[Image(data=b, format="png", annotations=ann) for b in pngs]],
        structured_content={"count": len(pngs), "total_pages": total_pages,
                            "cache_hit": cache_hit, "last_seen": last_seen,
                            "pages": pages, "scale": scale},
    )


def _check_scale(scale: float) -> int:
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise _bad("scale 0.5-3.0 (default 1.0)")
    f = float(scale)
    if not VIEW_MIN_SCALE <= f <= VIEW_MAX_SCALE:
        raise _bad("scale 0.5-3.0 (default 1.0)")
    return round(VIEW_BASE_PPI * f)


# --- export (W2-A): per-doc export via typst CLI, REST + MCP parity ---

EXPORT_TIMEOUT = 30.0
EXPORT_PPI = VIEW_BASE_PPI
EXPORT_MIMES = {"pdf": "application/pdf", "svg": "image/svg+xml",
                "png": "image/png", "zip": "application/zip"}
# 2C: PDF standards via server CLI (typst 0.15.1 --pdf-standard). The WASM
# bundle has no pdfStandard option, so standards always compile server-side
# in the 1C sandbox. Curated subset (commonly needed); unknown -> 400.
PDF_STANDARDS = frozenset({"1.7", "2.0", "a-1b", "a-2b", "a-3b", "a-2u",
                           "a-3u", "ua-1"})
EXPORT_PPI_MIN = 72
EXPORT_PPI_MAX = 300
EXPORT_PAGES_MAXLEN = 40


def _check_pdf_standard(s: str) -> str:
    v = (s or "").strip().lower()
    if v in ("", "none"):
        return ""
    if v not in PDF_STANDARDS:
        raise _bad("pdf_standard must be one of: none, " + ", ".join(sorted(PDF_STANDARDS)))
    return v


def _check_export_pages(s: str) -> str:
    v = (s or "").strip().replace(" ", "")
    if not v:
        return ""
    if len(v) > EXPORT_PAGES_MAXLEN or not re.fullmatch(r"[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*", v):
        raise _bad("pages must look like 1-3,5 (max 40 chars)")
    return v


def _check_export_ppi(p: int) -> int:
    if isinstance(p, bool) or not isinstance(p, int):
        raise _bad(f"ppi must be {EXPORT_PPI_MIN}-{EXPORT_PPI_MAX}")
    if not EXPORT_PPI_MIN <= p <= EXPORT_PPI_MAX:
        raise _bad(f"ppi must be {EXPORT_PPI_MIN}-{EXPORT_PPI_MAX}")
    return p


def _parse_export_ppi(s: str) -> int:
    """Query param -> int (0 = default). Non-numeric -> 400, not 422."""
    v = (s or "").strip()
    if not v:
        return 0
    if not re.fullmatch(r"[0-9]+", v):
        raise _bad(f"ppi must be {EXPORT_PPI_MIN}-{EXPORT_PPI_MAX}")
    return _check_export_ppi(int(v))


def _check_export_format(fmt: str) -> str:
    f = (fmt or "").strip().lower()
    if f not in EXPORT_FORMATS:
        raise _bad("format must be pdf, svg, png or zip")
    return f


def _export_stem(title: str) -> str:
    # Same sanitizer as main.zip_name (filenames must stay in sync).
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", (title or "").strip())[:80].strip("._") or "document"


def _collect_export_source(doc_id: str, max_bytes: int | None = None,
                             skip_oversize: bool = True,
                             include_resources: bool = True) -> tuple[str, list[tuple[str, bytes]], list[str]]:
    """(main_text, files, skipped) for one doc: live room text wins, then DB content.

    Attachments are collected recursively (nested paths preserved as zip/compile
    relative paths). Files over UPLOAD_MAX land in skipped when `skip_oversize`
    (the zip bundle reports them via SKIPPED.txt, like the full backup);
    symlinks are never followed. The total source size is capped at `max_bytes`
    (default EXPORT_MAX, 413 beyond).

    With `include_resources` (default) the owner's reachable resource closure
    (transitive, doc-local wins) is merged into `files`, so ALL export/view
    paths share one resolution: REST, MCP export and MCP view compile the
    same set. Callers must not re-merge (the old REST wrapper did).
    """
    cap = max_bytes if max_bytes is not None else EXPORT_MAX
    live = sync.room_text(doc_id)
    con = db.connect()
    try:
        row = con.execute("SELECT content, owner FROM docs WHERE id=?", (doc_id,)).fetchone()
    finally:
        con.close()
    if not row:
        raise _bad("Doc gone", 404)
    main_text = live if live is not None else (row["content"] or "")
    owner = row["owner"] or ""
    files: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    src_bytes = len(main_text.encode("utf-8"))
    d = _files_dir() / doc_id
    if d.is_dir():
        try:
            entries = sorted(d.rglob("*"))
        except OSError:
            entries = []
        for p in entries:
            try:
                name = p.relative_to(d).as_posix()
            except ValueError:
                continue
            if not p.is_file() or p.is_symlink() or any(s.startswith(".") for s in p.relative_to(d).parts) or ".tmp." in p.name:
                continue
            try:
                if skip_oversize and p.stat().st_size > UPLOAD_MAX:
                    skipped.append(name)
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            src_bytes += len(data)
            if src_bytes > cap:
                raise _bad("Export too large (max 100 MB)", 413)
            files.append((name, data))
    if src_bytes > cap:
        raise _bad("Export too large (max 100 MB)", 413)
    if include_resources and owner:
        try:
            from backend.services import resources as _res
        except ImportError:
            return main_text, files, skipped
        local_texts: dict[str, str] = {}
        for n, data in files:
            if _res.kind_of(n):
                try:
                    local_texts[n] = data.decode("utf-8", errors="replace")
                except Exception:
                    continue
        try:
            eff = _res.doc_effective(owner, main_text, local_texts, doc_id)
        except Exception as e:
            log.warning("export resource closure failed: %s", e)
            return main_text, files, skipped
        have = {n for n, _ in files}
        for n, c in (eff.get("resources") or {}).items():
            if n in have or ".tmp." in n:
                continue
            b = c.encode("utf-8")
            src_bytes += len(b)
            if src_bytes > cap:
                raise _bad("Export too large (max 100 MB)", 413)
            files.append((n, b))
            have.add(n)
    return main_text, files, skipped


def _typst_compile(args: list[str], tmp: str) -> str:
    """Run `typst <args>` in tmp and return its stderr (warnings). Compile errors -> 422 with diagnostics."""
    with _compile_slot():
        typst = shutil.which("typst")
        if not typst:
            raise _bad("typst CLI missing (Dockerfile installs it)", 500)
        try:
            proc = subprocess.run([typst, *args], cwd=tmp, capture_output=True,
                                  timeout=EXPORT_TIMEOUT, env=_typst_env(Path(tmp)),
                                  preexec_fn=_subprocess_preexec())
        except subprocess.TimeoutExpired as e:
            raise _bad("compile timed out (30s)", 500) from e
        except OSError as e:
            raise _bad(f"compile failed: {e}", 500) from e
        if proc.returncode != 0:
            raw = (proc.stderr or b"").decode("utf-8", "replace").strip()
            diags = _parse_typst_diagnostics(raw)
            short = raw.strip()[-500:] or "unknown"
            raise HTTPException(422, {"message": f"compile error: {short}",
                                      "diagnostics": diags})
        return (proc.stderr or b"").decode("utf-8", "replace")


def _compile_export_doc(main_text: str, files: list[tuple[str, bytes]], fmt: str,
                        skipped: list[str] | None = None, pdf_standard: str = "",
                        pages: str = "", ppi: int = 0, doc_name: str = "") -> tuple[bytes, str, bool]:
    """Compile one doc to (payload, mime, pages_zip).

    pdf = full multi-page PDF. svg/png = the single page directly, or a ZIP
    of all pages when the doc has more than one (typst needs a {p} template
    for multi-page image output). zip = source bundle (ENTRY + sources at
    root paths, directly renderable unpacked).
    pdf_standard/pages/ppi are CLI-only (the WASM bundle cannot do them):
    --pdf-standard (pdf only), --pages (pdf/svg/png), --ppi (png only).
    Outputs over EXPORT_MAX -> 413. Temp dirs auto-clean (no migration).
    """
    f = _check_export_format(fmt)
    std = _check_pdf_standard(pdf_standard)
    pg = _check_export_pages(pages)
    res = _check_export_ppi(ppi) if ppi else 0
    if std and f != "pdf":
        raise _bad("pdf_standard only applies to pdf")
    if pg and f == "zip":
        raise _bad("pages only applies to pdf, svg and png")
    if res and f != "png":
        raise _bad("ppi only applies to png")
    if f == "zip":
        buf = io.BytesIO()
        total = len(main_text.encode("utf-8"))
        doc_name = doc_name or ENTRY
        seen: set[str] = {doc_name.lower()}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(doc_name, main_text)
            for name, data in files:
                if ".tmp." in name:
                    continue
                # Directly renderable bundle: every source at its original
                # root-relative path (nested preserved), so an unchanged
                # #include "part.typ" / "sub/part.typ" compiles unpacked.
                clean = (name or "").replace("\\", "/").strip().lstrip("/")
                if not clean or ".." in clean.split("/"):
                    continue
                if clean.lower() in seen:
                    continue
                seen.add(clean.lower())
                total += len(data)
                if total > EXPORT_MAX:
                    raise _bad("Export too large (max 100 MB)", 413)
                z.writestr(clean, data)
            if skipped:
                z.writestr("SKIPPED.txt", "Oversized files left out:\n" + "\n".join(skipped) + "\n")
        payload = buf.getvalue()
        if len(payload) > EXPORT_MAX:
            raise _bad("Export too large (max 100 MB)", 413)
        return payload, EXPORT_MIMES["zip"], False
    with tempfile.TemporaryDirectory(prefix="export-doc-") as tmp:
        root = Path(tmp)
        try:
            (root / ENTRY).write_text(main_text, encoding="utf-8")
            for name, data in files:
                if ".tmp." in name:
                    continue
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
        except OSError as e:
            raise _bad(f"compile failed: {e}", 500) from e
        pg_args = ["--pages", pg] if pg else []
        if f == "pdf":
            std_args = ["--pdf-standard", std] if std else []
            _typst_compile(["compile", "--format", "pdf", *std_args, *pg_args, ENTRY, "out.pdf"], tmp)
            try:
                payload = (root / "out.pdf").read_bytes()
            except OSError as e:
                raise _bad(f"compile failed: {e}", 500) from e
            return _sized(payload, EXPORT_MIMES["pdf"], False)
        out = root / "__export__"  # own output folder: an uploaded page-1.png is never exported as a page
        try:
            out.mkdir(exist_ok=True)
        except OSError as e:
            raise _bad(f"compile failed: {e}", 500) from e
        if f == "svg":
            _typst_compile(["compile", "--format", "svg", *pg_args, ENTRY, "__export__/page-{p}.svg"], tmp)
            shots = sorted(out.glob("page-*.svg"), key=_page_no)  # page-10 after page-9
            return _pages_or_zip(shots, EXPORT_MIMES["svg"])
        _typst_compile(["compile", "--format", "png", "--ppi", str(res or EXPORT_PPI),
                        *pg_args, ENTRY, "__export__/page-{p}.png"], tmp)
        shots = sorted(out.glob("page-*.png"), key=_page_no)
        return _pages_or_zip(shots, EXPORT_MIMES["png"])


def _sized(payload: bytes, mime: str, multi: bool) -> tuple[bytes, str, bool]:
    if len(payload) > EXPORT_MAX:
        raise _bad("Export too large (max 100 MB)", 413)
    return payload, mime, multi


def _pages_or_zip(shots: list[Path], mime: str) -> tuple[bytes, str, bool]:
    if not shots:
        raise _bad("no pages rendered", 500)
    if len(shots) == 1:
        try:
            return _sized(shots[0].read_bytes(), mime, False)
        except OSError as e:
            raise _bad(f"compile failed: {e}", 500) from e
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        added = 0
        for shot in shots:
            try:
                data = shot.read_bytes()
            except OSError:
                continue
            z.writestr(shot.name, data)
            added += 1
    if not added:
        raise _bad("no pages rendered", 500)
    payload = buf.getvalue()
    return _sized(payload, EXPORT_MIMES["zip"], True)


def build_export_payload(title: str, main_text: str, files: list[tuple[str, bytes]],
                         fmt: str, skipped: list[str] | None = None, pdf_standard: str = "",
                         pages: str = "", ppi: int = 0) -> tuple[bytes, str, str]:
    """(payload, mime, filename) for REST responses. Multi-page svg/png
    arrive as `<stem>-<fmt>.zip`, everything else as `<stem>.<fmt>`."""
    f = _check_export_format(fmt)
    stem = _export_stem(title)
    payload, mime, multi = _compile_export_doc(main_text, files, f, skipped, pdf_standard, pages, ppi, f"{stem}.typ")
    suffix = "zip" if (multi or f == "zip") else f
    name = f"{stem}-{f}.zip" if multi else f"{stem}.{suffix}"
    return payload, mime, name


def _export_doc_sync(doc_id: str, title: str, fmt: str, pdf_standard: str = "",
                     pages: str = "", ppi: int = 0) -> tuple[bytes, str, str]:
    """Blocking collect + compile. Callers must offload (B13): the REST
    endpoint is sync (worker thread), op_export uses asyncio.to_thread."""
    main_text, files, skipped = _collect_export_source(doc_id)
    return build_export_payload(title, main_text, files, fmt, skipped, pdf_standard, pages, ppi)


_CHECKS: dict[str, dict] = {}


def check_source(main_text: str, files: list[tuple[str, bytes]]) -> dict:
    """Compile once to PDF: page count and warnings, cached per content; errors raise 422 with diagnostics."""
    key = _content_hash("", main_text, files)
    if key in _CHECKS:
        return _CHECKS[key]
    with tempfile.TemporaryDirectory(prefix="check-doc-") as tmp:
        root = Path(tmp)
        try:
            (root / ENTRY).write_text(main_text, encoding="utf-8")
            for name, data in files:
                if ".tmp." not in name:
                    (root / name).parent.mkdir(parents=True, exist_ok=True)
                    (root / name).write_bytes(data)
        except OSError as e:
            raise _bad(f"compile failed: {e}", 500) from e
        stderr = _typst_compile(["compile", "--format", "pdf", ENTRY, "out.pdf"], tmp)
        pages = _pdf_page_count((root / "out.pdf").read_bytes())
    result = {"pages": pages, "warnings": _parse_typst_diagnostics(stderr, "warning")}
    while len(_CHECKS) >= VIEW_CACHE_MAX:
        _CHECKS.pop(next(iter(_CHECKS)))
    _CHECKS[key] = result
    return result
