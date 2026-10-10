"""MCP core: path resolver + doc/file/template ops for the 9 MCP tools.

Pure logic with explicit (user, cap); backend/mcp_server.py wraps these as
FastMCP tools, tests call them directly. Raises HTTPException (the MCP
wrapper maps them to ToolError).

Path model:
    /docs/{Titel}              own doc (main text)
    /docs/{Titel}/{Datei}      file inside own doc
    /shared/{Owner}/{Titel}[/{Datei}]  doc shared with the caller
    /templates/{Name}.typ      own template (name must end in .typ)

Titles containing / are rejected with 400 (after percent-decoding).
Effective rights = min(key sort, doc_role()): a reviewer key (or share)
caps every op at read+comment, keys never reach owner/admin.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading as _compile_threading
import zipfile
from contextlib import contextmanager as _compile_cm
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException
from fastapi import UploadFile as FastUploadFile
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from mcp.types import Annotations

from backend import config as _config
from backend import db, search, sync
from backend.constants import EXPORT_FORMATS, EXPORT_MAX, MAX_TXT, TITLE_MAX, UPLOAD_MAX
from backend.services import quota as quota_svc

log = logging.getLogger("typst.mcp")

TEXT_SUFFIX = {".typ", ".bib", ".csv"}
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


def _parse_typst_diagnostics(stderr: str) -> list[dict]:
    """Parse typst CLI stderr into [{file, line, col, message}]."""
    diags: list[dict] = []
    if not stderr:
        return diags
    # Typst CLI prints "error: <msg>\n --> main.typ:line:col" blocks;
    # fall back to one entry per "error:" line when no position is found.
    blocks = re.split(r"(?m)^(?=error:|warning:)", stderr.strip())
    for b in blocks:
        b = b.strip()
        if not b or not b.startswith("error:"):
            continue
        first, _, rest = b.partition("\n")
        msg = first[len("error:"):].strip() or "compile error"
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
    if not diags:
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


def _bad(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(code, msg)


def _split(path: str) -> list[str]:
    if not path or not path.startswith("/"):
        raise _bad("Unknown path, use /docs/..., /shared/... or /templates/...")
    segs = [unquote(s) for s in path.split("/")[1:]]
    if any(s in ("", ".", "..") for s in segs):
        raise _bad("Unknown path, use /docs/..., /shared/... or /templates/...")
    return segs


def _title(seg: str) -> str:
    t = seg.strip()
    if not t or len(t) > TITLE_MAX:
        raise _bad(f"Title: 1-{TITLE_MAX} chars")
    if "/" in t:
        raise _bad("Title must not contain /")
    return t


def _file_name(seg: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(seg or "").name.strip().lstrip("."))[:100]
    if not n or ".tmp." in n:
        raise _bad("Invalid file name")
    return n


def _tpl_name(seg: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(seg or "").name.strip().lstrip("."))[:100]
    if not n.endswith(".typ"):
        raise _bad("Template gone", 404)  # same status as UI tpl_name
    return n


def _doc_by_title(owner: str, title: str) -> sqlite3.Row | None:
    con = db.connect()
    try:
        return con.execute("SELECT id, owner, title, content, updated_at, trashed FROM docs "
                           "WHERE owner=? AND title=? COLLATE NOCASE", (owner, title)).fetchone()
    finally:
        con.close()


def resolve_path(user: str, cap: str, path: str) -> dict:
    """Map an MCP path to a doc/file/template + effective role."""
    from backend.services import apikeys

    if path in ("", "/"):
        return {"kind": "root"}
    segs = _split(path)
    if segs == ["docs"]:
        return {"kind": "docs"}
    if segs == ["shared"]:
        return {"kind": "shared"}
    if segs == ["templates"]:
        return {"kind": "templates"}
    head = segs[0]
    if head == "docs" and len(segs) in (2, 3):
        title = _title(segs[1])
        row = _doc_by_title(user, title)
        if not row:
            raise _bad("Document not found", 404)
        if row["trashed"]:
            raise _bad("In trash - restore first", 410)
        role = apikeys.cap_min(cap, "owner")
        res: dict = {"kind": "doc", "doc_id": row["id"], "title": row["title"],
                     "owner": row["owner"], "role": role}
        if len(segs) == 3:
            res["kind"] = "file"
            res["filename"] = _file_name(segs[2])
        return res
    if head == "shared" and len(segs) in (3, 4):
        owner = segs[1].strip()
        if not owner or "/" in owner:
            raise _bad("Invalid owner")
        title = _title(segs[2])
        row = _doc_by_title(owner, title)
        base = db.doc_role(user, row["id"]) if row else None
        if not row or not base:
            raise _bad("Document not found", 404)  # share check before trash: no existence oracle
        if row["trashed"]:
            raise _bad("In trash - restore first", 410)
        res = {"kind": "doc", "doc_id": row["id"], "title": row["title"],
               "owner": row["owner"], "role": apikeys.cap_min(cap, base)}
        if len(segs) == 4:
            res["kind"] = "file"
            res["filename"] = _file_name(segs[3])
        return res
    if head == "templates" and len(segs) == 2:
        name = _tpl_name(segs[1])
        con = db.connect()
        try:
            row = con.execute("SELECT name, content, updated_at FROM templates WHERE owner=? AND name=?",
                              (user, name)).fetchone()
        finally:
            con.close()
        if not row:
            raise _bad("Template gone", 404)
        return {"kind": "template", "tpl": row["name"], "role": apikeys.cap_min(cap, "owner")}
    raise _bad("Unknown path, use /docs/..., /shared/... or /templates/...")


def _need_edit(res: dict) -> None:
    if res.get("role") not in ("owner", "editor"):
        raise _bad("Reviewer can only comment", 403)


def _files_dir() -> Path:
    return quota_svc.files_dir()


def op_ls(user: str, cap: str, path: str = "/") -> dict:
    res = resolve_path(user, cap, path) if path not in ("", "/") else {"kind": "root"}
    kind = res["kind"]
    con = db.connect()
    try:
        if kind == "root":
            own = con.execute("SELECT title, updated_at FROM docs WHERE owner=? AND trashed=0 "
                              "ORDER BY updated_at DESC", (user,)).fetchall()
            shared = con.execute(
                "SELECT d.owner, d.title, d.updated_at, s.role FROM docs d JOIN shares s ON s.doc_id=d.id "
                "WHERE s.username=? AND d.trashed=0 ORDER BY d.updated_at DESC", (user,)).fetchall()
            tpls = con.execute("SELECT name FROM templates WHERE owner=? ORDER BY name", (user,)).fetchall()
            return {"docs": [dict(r) for r in own],
                    "shared": [dict(r) for r in shared],
                    "templates": [dict(r) for r in tpls]}
        if kind == "docs":
            own = con.execute("SELECT title, updated_at FROM docs WHERE owner=? AND trashed=0 "
                              "ORDER BY updated_at DESC", (user,)).fetchall()
            return {"docs": [dict(r) for r in own]}
        if kind == "shared":
            shared = con.execute(
                "SELECT d.owner, d.title, d.updated_at, s.role FROM docs d JOIN shares s ON s.doc_id=d.id "
                "WHERE s.username=? AND d.trashed=0 ORDER BY d.updated_at DESC", (user,)).fetchall()
            return {"shared": [dict(r) for r in shared]}
        if kind == "templates":
            tpls = con.execute("SELECT name FROM templates WHERE owner=? ORDER BY name", (user,)).fetchall()
            return {"templates": [dict(r) for r in tpls]}
        if kind == "doc":
            d = _files_dir() / res["doc_id"]
            out = []
            if d.is_dir():
                try:
                    entries = sorted(d.iterdir())
                except OSError as e:
                    log.warning("mcp ls failed: %s", e)
                    raise _bad("File list failed", 500) from e
                for p in entries:
                    if p.is_file() and ".tmp." not in p.name:
                        try:
                            st = p.stat()
                        except OSError:
                            continue
                        out.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
            return {"title": res["title"], "files": out}
        raise _bad("ls works on / , /docs, /shared, /templates or a document path, use read for files")
    finally:
        con.close()


def _page_text(text: str, offset: int, limit: int) -> tuple[str, int]:
    """1-based line window over text; limit 0 = all. Returns (slice, total_lines)."""
    if (isinstance(offset, bool) or not isinstance(offset, int)
            or isinstance(limit, bool) or not isinstance(limit, int)):
        raise _bad("offset/limit must be integers")
    if offset < 1 or limit < 0:
        raise _bad("offset >= 1, limit >= 0")
    if not text:
        return "", 0
    lines = text.split("\n")
    total = len(lines)
    sel = lines[offset - 1:] if limit == 0 else lines[offset - 1:offset - 1 + limit]
    return "\n".join(sel), total


def op_read(user: str, cap: str, path: str, offset: int = 1, limit: int = 0) -> dict:
    res = resolve_path(user, cap, path)
    kind = res["kind"]
    if kind == "doc":
        live = sync.room_text(res["doc_id"])
        con = db.connect()
        try:
            row = con.execute("SELECT content, updated_at FROM docs WHERE id=?", (res["doc_id"],)).fetchone()
        finally:
            con.close()
        if not row:
            raise _bad("Doc gone", 404)
        content, total = _page_text(live if live is not None else (row["content"] or ""), offset, limit)
        return {"kind": "doc", "title": res["title"], "role": res["role"],
                "content": content, "offset": offset, "total_lines": total,
                "last_seen": row["updated_at"], "live": live is not None}
    if kind == "file":
        p = _files_dir() / res["doc_id"] / res["filename"]
        if Path(res["filename"]).suffix.lower() not in TEXT_SUFFIX:
            raise _bad("Binary file - use view to render the document or upload to replace it")
        if not p.is_file():
            raise _bad("File gone", 404)
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            mtime = p.stat().st_mtime
        except OSError as e:
            log.warning("mcp read gone %s: %s", p.name, e)
            raise _bad("File gone", 404) from e
        content, total = _page_text(raw, offset, limit)
        return {"kind": "file", "title": res["title"], "name": res["filename"],
                "content": content, "offset": offset, "total_lines": total,
                "last_seen": str(mtime)}
    if kind == "template":
        con = db.connect()
        try:
            row = con.execute("SELECT content, updated_at FROM templates WHERE owner=? AND name=?",
                              (user, res["tpl"])).fetchone()
        finally:
            con.close()
        if not row:
            raise _bad("Template gone", 404)
        content, total = _page_text(row["content"] or "", offset, limit)
        return {"kind": "template", "name": res["tpl"], "content": content,
                "offset": offset, "total_lines": total, "last_seen": row["updated_at"]}
    raise _bad("read needs a document, file or template path, use ls to browse")


def op_create(user: str, cap: str, path: str, content: str = "") -> dict:
    from backend import deps
    from backend.services import sidebar

    if cap == "reviewer":
        raise _bad("Reviewer can only comment", 403)
    if len(content) > MAX_TXT:
        raise _bad("Doc too large (max 200 KB)")
    if path in ("", "/"):
        raise _bad("create needs a /docs/... or /templates/... path")
    segs = _split(path)
    if segs[0] == "docs" and len(segs) == 2:
        title = _title(segs[1])
        try:
            max_docs = _config.load().MAX_DOCS_PER_USER
        except Exception:
            max_docs = 100
        did = db.new_id("d_")

        def _rollback_create() -> None:
            rc = db.connect()
            try:
                rc.execute("DELETE FROM docs WHERE id=?", (did,))
                rc.commit()
            finally:
                rc.close()

        try:
            with quota_svc.quota_guard(user, len(content.encode("utf-8")), rollback=_rollback_create):
                try:
                    with db.tx() as con:
                        if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?",
                                       (user,)).fetchone()["n"] >= max_docs:
                            raise _bad("Too many docs")
                        if con.execute("SELECT 1 FROM docs WHERE owner=? AND title=? COLLATE NOCASE",
                                       (user, title)).fetchone():
                            raise _bad("Title already exists")
                        now = db.now_iso()
                        con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) "
                                    "VALUES (?,?,?,?,?,?,?)", (did, user, title, content, "", now, now))
                except sqlite3.IntegrityError as e:
                    raise _bad("Title already exists") from e
                except sqlite3.OperationalError as e:
                    raise deps.busy_503("mcp_create", e) from e
        except sqlite3.OperationalError as e:
            raise deps.busy_503("mcp_create", e) from e
        sidebar.notify_sidebar(user)
        return {"id": did, "title": title, "path": f"/docs/{title}"}
    if segs[0] == "docs" and len(segs) == 3:
        title = _title(segs[1])
        row = _doc_by_title(user, title)
        if not row:
            raise _bad("Document not found", 404)
        if row["trashed"]:
            raise _bad("In trash - restore first", 410)
        filename = _file_name(segs[2])
        if Path(filename).suffix.lower() not in TEXT_SUFFIX:
            raise _bad("Binary file - use upload to add it")
        _write_text_file(row["id"], filename, content, user, cap, must_create=True)
        return {"title": title, "name": filename, "path": f"/docs/{title}/{filename}"}
    if segs[0] == "templates" and len(segs) == 2:
        name = _tpl_name(segs[1])
        try:
            with quota_svc.quota_guard(user, len(content.encode("utf-8"))):
                with db.tx() as con:
                    if con.execute("SELECT 1 FROM templates WHERE owner=? AND name=?", (user, name)).fetchone():
                        raise _bad("Template already exists")
                    con.execute("INSERT INTO templates (owner, name, content, line, folder, updated_at) "
                                "VALUES (?,?,?,?,?,?)",
                                (user, name, content, f'#include "{name}"', "", db.now_iso()))
        except sqlite3.IntegrityError as e:
            raise _bad("Template already exists") from e
        except sqlite3.OperationalError as e:
            raise deps.busy_503("mcp_create", e) from e
        sidebar.notify_sidebar(user)
        return {"name": name, "path": f"/templates/{name}"}
    if segs[0] == "shared":
        raise _bad("Cannot create in the shared namespace", 403)
    raise _bad("create needs a /docs/{Title}[/{File}] or /templates/{Name}.typ path")


def _recheck_edit(user: str, cap: str, doc_id: str) -> None:
    """Role/trash re-check right before a file write (closes revoke races)."""
    from backend.services import apikeys

    con = db.connect()
    try:
        row = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
    finally:
        con.close()
    if not row:
        raise _bad("Doc gone", 404)
    if row["trashed"]:
        raise _bad("In trash - restore first", 410)
    if apikeys.cap_min(cap, db.doc_role(user, doc_id) or "") not in ("owner", "editor"):
        raise _bad("Reviewer can only comment", 403)


def _write_text_file(doc_id: str, filename: str, content: str, user: str, cap: str, must_create: bool) -> None:
    """Same write path as save_file_text: upload lock, tmp+replace, quota, touch."""
    from backend import deps
    from backend.services import docfiles, locks

    if len(content) > MAX_TXT:
        raise _bad("Max 200 KB")
    with locks._named_lock(f"upload:{doc_id}"):
        _recheck_edit(user, cap, doc_id)
        p = _files_dir() / doc_id / filename
        try:
            if must_create and p.is_file():
                raise _bad("File already exists")
            if not must_create and not p.is_file():
                raise _bad("File gone", 404)
            _old_sz = p.stat().st_size if p.is_file() else 0
        except HTTPException:
            raise
        except OSError as e:
            log.warning("mcp write stat failed: %s", e)
            raise _bad("File gone", 404) from e
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise _bad("Upload failed", 500) from e
        try:
            old = p.read_bytes() if p.is_file() else None
        except OSError:
            old = None

        def _restore() -> None:
            # Mirror save_text_file's rollback: disk AND files table revert
            # together, otherwise quota/search (table readers) desync.
            try:
                if old is None:
                    p.unlink(missing_ok=True)
                    try:
                        docfiles.drop_file(doc_id, filename)
                    except HTTPException:
                        pass
                else:
                    p.write_bytes(old)
                    try:
                        _rst = p.stat()
                    except OSError:
                        pass
                    else:
                        docfiles.record_file(doc_id, filename, _rst.st_size, _rst.st_mtime)
            except (OSError, HTTPException):
                pass

        tmp = p.parent / f"{p.name}.tmp.{db.new_id('')}"
        try:
            with quota_svc.quota_guard(quota_svc.doc_owner(doc_id, user),
                                       max(0, len(content.encode("utf-8")) - _old_sz),
                                       rollback=_restore):
                try:
                    tmp.write_text(content, encoding="utf-8")
                    import os as _os

                    _os.replace(tmp, p)
                except OSError:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
                # Write-through (same pattern as save_text_file): the files
                # table mirrors the tree, quota/search read the table.
                try:
                    _st = p.stat()
                except OSError as e:
                    log.warning("mcp write stat failed: %s", e)
                else:
                    docfiles.record_file(doc_id, filename, _st.st_size, _st.st_mtime)
        except sqlite3.OperationalError as e:
            raise deps.busy_503("mcp_write", e) from e
        docfiles.touch_doc(doc_id)
        quota_svc.invalidate_quota_cache(quota_svc.doc_owner(doc_id, user))


def _current_text(user: str, res: dict) -> tuple[str, str]:
    """(text, version marker) for doc/file/template. Marker feeds last_seen."""
    kind = res["kind"]
    if kind == "doc":
        live = sync.room_text(res["doc_id"])
        con = db.connect()
        try:
            row = con.execute("SELECT content, updated_at, trashed FROM docs WHERE id=?",
                              (res["doc_id"],)).fetchone()
        finally:
            con.close()
        if not row:
            raise _bad("Doc gone", 404)
        if row["trashed"]:
            raise _bad("In trash - restore first", 410)
        return (live if live is not None else (row["content"] or "")), row["updated_at"]
    if kind == "file":
        p = _files_dir() / res["doc_id"] / res["filename"]
        if Path(res["filename"]).suffix.lower() not in TEXT_SUFFIX:
            raise _bad("Binary file - use upload to replace it")
        if not p.is_file():
            raise _bad("File gone", 404)
        try:
            return p.read_text(encoding="utf-8", errors="replace"), str(p.stat().st_mtime)
        except OSError as e:
            raise _bad("File gone", 404) from e
    if kind == "template":
        con = db.connect()
        try:
            row = con.execute("SELECT content, updated_at FROM templates WHERE owner=? AND name=?",
                              (user, res["tpl"])).fetchone()
        finally:
            con.close()
        if not row:
            raise _bad("Template gone", 404)
        return row["content"] or "", row["updated_at"]
    raise _bad("edit needs a document, file or template path")


async def op_edit(user: str, cap: str, path: str, old_string: str,
                  new_string: str, replace_all: bool = False, last_seen: str | None = None) -> dict:
    """Anchor edit: old_string (with 2-3 lines context) must match 1x, or
    replace_all=true replaces every match. 0x -> 409 anchor-gone, >1x without
    replace_all -> 409 anchor-ambiguous. last_seen (from read) only guards
    the anchor: a changed marker with a still-clean anchor proceeds (no false
    alarm on distant foreign edits)."""
    from backend import deps
    from backend.services import apikeys
    from backend.services import snapshots as snapsvc

    if not old_string:
        raise _bad("old_string required (quote 2-3 lines context around the change)")
    res = resolve_path(user, cap, path)
    _need_edit(res)
    current, marker = _current_text(user, res)
    stale = last_seen is not None and last_seen != marker
    n = current.count(old_string)
    if n == 0:
        raise _bad("anchor-gone: old_string not found, re-read first", 409)
    if n > 1 and not replace_all:
        raise _bad(f"anchor-ambiguous: {n} matches, add context or use replace_all=true", 409)
    new_text = current.replace(old_string, new_string, -1 if replace_all else 1)
    if len(new_text) > MAX_TXT:
        raise _bad("Doc too large (max 200 KB)")
    if new_text == current:
        return {"ok": True, "replaced": 0, "last_seen": marker, "stale": stale}
    replaced = n if replace_all else 1
    kind = res["kind"]
    if kind == "doc":
        doc_id = res["doc_id"]
        live_before = sync.room_text(doc_id)
        con0 = db.connect()
        try:
            old_row = con0.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        finally:
            con0.close()
        old_db = (old_row["content"] or "") if old_row else ""
        owner = quota_svc.doc_owner(doc_id, user)

        def _restore() -> None:
            rb = db.connect()
            try:
                rb.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                           (old_db, db.now_iso(), doc_id))
                rb.commit()
            finally:
                rb.close()

        try:
            with quota_svc.quota_guard(owner, max(0, len(new_text.encode("utf-8"))
                                                  - len(old_db.encode("utf-8"))), rollback=_restore):
                try:
                    with db.tx() as con:
                        cur = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
                        if not cur:
                            raise _bad("Doc gone", 404)
                        if cur["trashed"]:
                            raise _bad("In trash - restore first", 410)
                        # B5: role re-check ON the tx connection (db.doc_role
                        # opens its own connection and can go stale in the gap).
                        _orow = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
                        if _orow and _orow["owner"] == user:
                            _role = "owner"
                        else:
                            _srow = con.execute("SELECT role FROM shares WHERE doc_id=? AND username=?",
                                                (doc_id, user)).fetchone()
                            _role = _srow["role"] if _srow else ""
                        if apikeys.cap_min(cap, _role) not in ("owner", "editor"):
                            raise _bad("Reviewer can only comment", 403)
                        con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                                    (new_text, db.now_iso(), doc_id))
                except sqlite3.OperationalError as e:
                    raise deps.busy_503("mcp_edit", e) from e
        except sqlite3.OperationalError as e:
            raise deps.busy_503("mcp_edit", e) from e
        try:
            # Snapshot of the pre-edit state (old_db): after the commit so a
            # failed edit leaves no stray snapshot; failures only warn.
            snapsvc.auto_snap(doc_id, old_db, label="mcp-edit")
        except HTTPException as e:
            log.warning("mcp_edit snap: %s", e.detail)
        if live_before is not None:
            await sync.replace_text(doc_id, new_text)
        elif not sync.persist(doc_id):
            db.clear_room_state(doc_id)
    elif kind == "file":
        _write_text_file(res["doc_id"], res["filename"], new_text, user, cap, must_create=False)
    else:
        con = db.connect()
        try:
            with quota_svc.quota_guard(user, max(0, len(new_text.encode("utf-8")) - len(current.encode("utf-8")))):
                try:
                    cur = con.execute("UPDATE templates SET content=?, updated_at=? WHERE owner=? AND name=?",
                                      (new_text, db.now_iso(), user, res["tpl"]))
                    con.commit()
                    if cur.rowcount == 0:
                        raise _bad("Template gone", 404)
                except sqlite3.OperationalError as e:
                    raise deps.busy_503("mcp_edit", e) from e
        except sqlite3.OperationalError as e:
            raise deps.busy_503("mcp_edit", e) from e
        finally:
            con.close()
    new_marker = _current_text(user, resolve_path(user, cap, path))[1]
    return {"ok": True, "replaced": replaced, "last_seen": new_marker, "stale": stale}


def op_search(user: str, cap: str, query: str) -> dict:
    _ = cap  # read access is enough (resolve already gates per doc)
    if len((query or "").strip()[:50]) < 2:
        return {"hits": []}
    con = db.connect()
    try:
        rows = search.search_visible(user, query, con, _files_dir(), sync.room_text)
    finally:
        con.close()
    hits = []
    for h in rows:
        base = f"/docs/{h['title']}" if h["owner"] == user else f"/shared/{h['owner']}/{h['title']}"
        hits.append({"path": base, "title": h["title"], "owner": h["owner"],
                     "snippet": h["snippet"], "pos": h["pos"]})
    return {"hits": hits}


def op_upload(user: str, cap: str, path: str, content_base64: str, filename: str | None = None) -> dict:
    """Upload/replace a binary or text attachment. Path is /docs/{Titel}/{Datei}
    or /docs/{Titel} + filename. Same locks/quota/size rules as the UI upload."""
    from backend.services import docfiles, locks

    res = resolve_path(user, cap, path)
    _need_edit(res)
    if res["kind"] == "file":
        doc_id, fname = res["doc_id"], res["filename"]
    elif res["kind"] == "doc" and filename:
        doc_id, fname = res["doc_id"], filename
    else:
        raise _bad("upload needs /docs/{Title}/{File} or /docs/{Title} + filename")
    try:
        data = base64.b64decode(content_base64, validate=True)
    except Exception:
        raise _bad("Invalid base64") from None
    if len(data) > UPLOAD_MAX:
        raise _bad("Max 10 MB")
    n = docfiles.safe_name(fname)
    with locks._named_lock(f"upload:{doc_id}"):
        _recheck_edit(user, cap, doc_id)
        uf = FastUploadFile(file=io.BytesIO(data), filename=n)
        return docfiles._upload_locked(doc_id, uf, n, user)


def op_comment(user: str, cap: str, path: str, anchor: int,
               text: str, quote: str = "", parent_id: str | None = None,
               author: str | None = None) -> dict:
    _ = cap  # any role with read access may comment (mirrors add_comment)
    res = resolve_path(user, cap, path)
    if res["kind"] != "doc":
        raise _bad("comments live on documents, use /docs/{Title}")
    if not isinstance(anchor, int) or anchor < 0 or anchor > 10_000_000:
        raise _bad("Anchor 0-10000000 (0 = line 1)")
    if not text.strip() or len(text) > 2000:
        raise _bad("Comment: 1-2000 chars")
    # Display author: key name for key auth (auth stays on the account name,
    # so no impersonation is possible). Empty key name falls back to user.
    shown = (author or "").strip()[:40]
    cid = db.new_id("c_")
    con = db.connect()
    try:
        if parent_id:
            p = con.execute("SELECT parent_id FROM comments WHERE id=? AND doc_id=?",
                            (parent_id, res["doc_id"])).fetchone()
            if not p:
                raise _bad("Thread gone", 404)
            if p["parent_id"]:
                raise _bad("Nested replies not allowed")
        q = quote[:500]
        con.execute("INSERT INTO comments (id, doc_id, username, author, anchor, quote, text, parent_id, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (cid, res["doc_id"], user, shown, max(1, anchor), q if q.strip() else "",
                     text.strip(), parent_id, db.now_iso()))
        con.commit()
        return {"id": cid}
    finally:
        con.close()


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
    # Container runs read-only (USER 999, read_only:true): typst's package
    # cache defaults to a non-writable location, so any @preview import
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
                (root / "main.typ").write_text(main_text, encoding="utf-8")
                for name, data in files:
                    if ".tmp." in name:
                        continue
                    (root / name).write_bytes(data)
            except OSError as e:
                raise _bad(f"compile failed: {e}", 500) from e
            cmd = [typst, "compile", "--format", "png", "--ppi", str(ppi),
                   "--pages", pages, "main.typ", "page-{p}.png"]
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
            shots = sorted(root.glob("page-*.png"))[:VIEW_MAX_PAGES]
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
    """Compile to PDF and count pages. None when the count is unknown."""
    with _compile_slot():
        typst = shutil.which("typst")
        if not typst:
            raise _bad("typst CLI missing (Dockerfile installs it)", 500)
        with tempfile.TemporaryDirectory(prefix="mcp-view-total-") as tmp:
            root = Path(tmp)
            try:
                (root / "main.typ").write_text(main_text, encoding="utf-8")
                for name, data in files:
                    if ".tmp." in name:
                        continue
                    (root / name).write_bytes(data)
            except OSError as e:
                log.warning("pdf-pages write failed: %s", e)
                return None
            cmd = [typst, "compile", "--format", "pdf", "main.typ", "out.pdf"]
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


def _total_pages_cached(doc_id: str, main_text: str,
                        files: list[tuple[str, bytes]], fallback: int) -> int:
    """Total doc pages via cached PDF page count, fallback = max requested page."""
    key = _content_hash(doc_id, main_text, files)
    hit = _VIEW_TOTALS.get(key)
    if hit is not None:
        _VIEW_TOTALS[key] = _VIEW_TOTALS.pop(key)  # LRU refresh
        return hit
    try:
        n = _compile_pdf_pages(main_text, files)
    except HTTPException:
        n = None
    if n is None:
        return fallback  # transient PDF failure: do not poison the cache
    if len(_VIEW_TOTALS) >= VIEW_CACHE_MAX:
        _VIEW_TOTALS.pop(next(iter(_VIEW_TOTALS)), None)
    _VIEW_TOTALS[key] = n
    return n


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


async def op_view(user: str, cap: str, path: str,
                  pages: str = "1-5", scale: float = 1.0) -> ToolResult:
    res = resolve_path(user, cap, path)
    if res["kind"] != "doc":
        raise _bad("view renders documents, use /docs/{Title}")
    wanted = _expand_pages(pages or "")
    ppi = _check_scale(scale)
    pages_arg = ",".join(str(p) for p in wanted)
    live = sync.room_text(res["doc_id"])
    con = db.connect()
    try:
        row = con.execute("SELECT content, updated_at FROM docs WHERE id=?", (res["doc_id"],)).fetchone()
    finally:
        con.close()
    if not row:
        raise _bad("Doc gone", 404)
    main_text = live if live is not None else (row["content"] or "")
    d = _files_dir() / res["doc_id"]
    files: list[tuple[str, bytes]] = []
    src_bytes = 0
    if d.is_dir():
        try:
            entries = sorted(d.iterdir())
        except OSError:
            entries = []
        for p in entries:
            if p.is_file() and ".tmp." not in p.name:
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                src_bytes += len(data)
                if src_bytes > VIEW_SRC_MAX:
                    raise _bad("too many files for view", 413)
                files.append((p.name, data))
    key = _view_key(res["doc_id"], main_text, files, pages_arg, ppi)
    hit = _view_cache_get(key)
    if hit is not None:
        cached_total = hit.get("total_pages")
        total_hit: int = (cached_total if isinstance(cached_total, int) else
                          _total_pages_cached(res["doc_id"], main_text, files, max(wanted)))
        hit["total_pages"] = total_hit
        return _view_result(hit["pngs"], True, row["updated_at"], total_hit, pages_arg, float(scale))
    pngs = await asyncio.to_thread(_compile_pngs, main_text, files, pages_arg, ppi)
    total = await asyncio.to_thread(_total_pages_cached, res["doc_id"], main_text, files, max(wanted))
    _view_cache_put(key, {"pngs": pngs, "total_pages": total})
    return _view_result(pngs, False, row["updated_at"], total, pages_arg, float(scale))


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


def _collect_export_source(doc_id: str) -> tuple[str, list[tuple[str, bytes]], list[str]]:
    """(main_text, files, skipped) for one doc: live room text wins, then DB content.

    Attachments over UPLOAD_MAX land in skipped (the zip bundle reports them
    via SKIPPED.txt, like the full backup); symlinks are never followed.
    The total source size is capped at EXPORT_MAX (413 beyond).
    """
    live = sync.room_text(doc_id)
    if live is not None:
        main_text = live
    else:
        con = db.connect()
        try:
            row = con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        finally:
            con.close()
        if not row:
            raise _bad("Doc gone", 404)
        main_text = row["content"] or ""
    files: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    src_bytes = len(main_text.encode("utf-8"))
    d = _files_dir() / doc_id
    if d.is_dir():
        try:
            entries = sorted(d.iterdir())
        except OSError:
            entries = []
        for p in entries:
            if not p.is_file() or p.is_symlink() or ".tmp." in p.name:
                continue
            try:
                if p.stat().st_size > UPLOAD_MAX:
                    skipped.append(p.name)
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            src_bytes += len(data)
            if src_bytes > EXPORT_MAX:
                raise _bad("Export too large (max 100 MB)", 413)
            files.append((p.name, data))
    if src_bytes > EXPORT_MAX:
        raise _bad("Export too large (max 100 MB)", 413)
    return main_text, files, skipped


def _typst_compile(args: list[str], tmp: str) -> None:
    """Run `typst <args>` in tmp. Compile errors -> 422 with diagnostics."""
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


def _compile_export_doc(main_text: str, files: list[tuple[str, bytes]], fmt: str,
                        skipped: list[str] | None = None, pdf_standard: str = "",
                        pages: str = "", ppi: int = 0) -> tuple[bytes, str, bool]:
    """Compile one doc to (payload, mime, pages_zip).

    pdf = full multi-page PDF. svg/png = the single page directly, or a ZIP
    of all pages when the doc has more than one (typst needs a {p} template
    for multi-page image output). zip = source bundle (main.typ + files/).
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
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("main.typ", main_text)
            for name, data in files:
                if ".tmp." in name:
                    continue
                total += len(data)
                if total > EXPORT_MAX:
                    raise _bad("Export too large (max 100 MB)", 413)
                z.writestr(f"files/{name}", data)
            if skipped:
                z.writestr("SKIPPED.txt", "Oversized files left out:\n" + "\n".join(skipped) + "\n")
        payload = buf.getvalue()
        if len(payload) > EXPORT_MAX:
            raise _bad("Export too large (max 100 MB)", 413)
        return payload, EXPORT_MIMES["zip"], False
    with tempfile.TemporaryDirectory(prefix="export-doc-") as tmp:
        root = Path(tmp)
        try:
            (root / "main.typ").write_text(main_text, encoding="utf-8")
            for name, data in files:
                if ".tmp." in name:
                    continue
                (root / name).write_bytes(data)
        except OSError as e:
            raise _bad(f"compile failed: {e}", 500) from e
        pg_args = ["--pages", pg] if pg else []
        if f == "pdf":
            std_args = ["--pdf-standard", std] if std else []
            _typst_compile(["compile", "--format", "pdf", *std_args, *pg_args, "main.typ", "out.pdf"], tmp)
            try:
                payload = (root / "out.pdf").read_bytes()
            except OSError as e:
                raise _bad(f"compile failed: {e}", 500) from e
            return _sized(payload, EXPORT_MIMES["pdf"], False)
        if f == "svg":
            _typst_compile(["compile", "--format", "svg", *pg_args, "main.typ", "page-{p}.svg"], tmp)
            shots = sorted(root.glob("page-*.svg"))
            return _pages_or_zip(shots, EXPORT_MIMES["svg"])
        _typst_compile(["compile", "--format", "png", "--ppi", str(res or EXPORT_PPI),
                        *pg_args, "main.typ", "page-{p}.png"], tmp)
        shots = sorted(root.glob("page-*.png"))
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
    payload, mime, multi = _compile_export_doc(main_text, files, f, skipped, pdf_standard, pages, ppi)
    stem = _export_stem(title)
    suffix = "zip" if (multi or f == "zip") else f
    name = f"{stem}-{f}.zip" if multi else f"{stem}.{suffix}"
    return payload, mime, name


def _export_doc_sync(doc_id: str, title: str, fmt: str, pdf_standard: str = "",
                     pages: str = "", ppi: int = 0) -> tuple[bytes, str, str]:
    """Blocking collect + compile. Callers must offload (B13): the REST
    endpoint is sync (worker thread), op_export uses asyncio.to_thread."""
    main_text, files, skipped = _collect_export_source(doc_id)
    return build_export_payload(title, main_text, files, fmt, skipped, pdf_standard, pages, ppi)


async def op_export(user: str, cap: str, path: str, format: str = "pdf",
                  pdf_standard: str = "none", pages: str = "", ppi: int = 0) -> dict:
    """Export a document via typst CLI (read-only: any role with access).

    format pdf = full PDF; svg/png = single page directly, multi-page docs
    as ZIP of pages; zip = source bundle (main.typ + files/). Returns
    base64 payload + mime + filename (REST parity, no worker block: compile
    runs in asyncio.to_thread). Like view: MCP rate scope (`mcp`) applies,
    no per-user export lock (REST serializes via _export_lock).
    2C options (CLI-only): pdf_standard (pdf only), pages (pdf/svg/png),
    ppi 72-300 (png only). Bad values -> error before any compile.
    """
    _ = cap  # read access is enough (resolve already gates per doc)
    res = resolve_path(user, cap, path)
    if res["kind"] != "doc":
        raise _bad("export needs a document path, use /docs/{Title}")
    fmt = _check_export_format(format)
    std = _check_pdf_standard(pdf_standard)
    pg = _check_export_pages(pages)
    pp = _check_export_ppi(ppi) if ppi else 0  # 0 = unset, wie REST ohne ppi-Param
    payload, mime, filename = await asyncio.to_thread(
        _export_doc_sync, res["doc_id"], res["title"], fmt, std, pg, pp)
    return {"format": fmt, "mime": mime, "filename": filename,
            "content_base64": base64.b64encode(payload).decode("ascii"),
            "size_bytes": len(payload)}
