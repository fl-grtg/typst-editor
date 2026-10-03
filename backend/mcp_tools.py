"""MCP core: path resolver + doc/file/template ops for the 8 MCP tools.

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
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException
from fastapi import UploadFile as FastUploadFile

from backend import config as _config
from backend import db, sync
from backend.constants import MAX_TXT, TITLE_MAX, UPLOAD_MAX
from backend.services import quota as quota_svc

log = logging.getLogger("typst.mcp")

TEXT_SUFFIX = {".typ", ".bib", ".csv"}
VIEW_MAX_PAGES = 5
VIEW_MAX_WIDTH = 1024
VIEW_TIMEOUT = 10.0
VIEW_CACHE_MAX = 20
VIEW_CACHE_BYTES = 20 * 1024 * 1024
VIEW_SRC_MAX = 50 * 1024 * 1024


def _pages_ok(pages: str) -> bool:
    if not pages:
        return False
    try:
        for part in pages.split(","):
            nums = [int(x) for x in part.split("-")]
            if len(nums) > 2 or any(not 1 <= x <= VIEW_MAX_PAGES for x in nums):
                return False
            if len(nums) == 2 and nums[0] > nums[1]:
                return False
    except ValueError:
        return False
    return True


_TYPST_TAG: str | None = None


def _typst_tag() -> str:
    """Cache-busting salt: fonts/packages/env changes alter the render."""
    global _TYPST_TAG
    if _TYPST_TAG is None:
        try:
            exe = shutil.which("typst") or "typst"
            p = subprocess.run([exe, "--version"], capture_output=True, timeout=10)
            _TYPST_TAG = (p.stdout or b"").decode("utf-8", "replace").strip()[:80] if p.returncode == 0 else "unknown"
        except Exception:
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
    from backend import main as _main

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
        role = _main.cap_min(cap, "owner")
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
               "owner": row["owner"], "role": _main.cap_min(cap, base)}
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
        return {"kind": "template", "tpl": row["name"], "role": _main.cap_min(cap, "owner")}
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


def op_read(user: str, cap: str, path: str) -> dict:
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
        return {"kind": "doc", "title": res["title"], "role": res["role"],
                "content": live if live is not None else (row["content"] or ""),
                "last_seen": row["updated_at"], "live": live is not None}
    if kind == "file":
        p = _files_dir() / res["doc_id"] / res["filename"]
        if Path(res["filename"]).suffix.lower() not in TEXT_SUFFIX:
            raise _bad("Binary file - use view to render the document or upload to replace it")
        if not p.is_file():
            raise _bad("File gone", 404)
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            mtime = p.stat().st_mtime
        except OSError as e:
            log.warning("mcp read gone %s: %s", p.name, e)
            raise _bad("File gone", 404) from e
        return {"kind": "file", "title": res["title"], "name": res["filename"],
                "content": content, "last_seen": str(mtime)}
    if kind == "template":
        con = db.connect()
        try:
            row = con.execute("SELECT content, updated_at FROM templates WHERE owner=? AND name=?",
                              (user, res["tpl"])).fetchone()
        finally:
            con.close()
        if not row:
            raise _bad("Template gone", 404)
        return {"kind": "template", "name": res["tpl"], "content": row["content"] or "",
                "last_seen": row["updated_at"]}
    raise _bad("read needs a document, file or template path, use ls to browse")


def op_create(user: str, cap: str, path: str, content: str = "") -> dict:
    from backend import main as _main

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
                    raise _main.busy_503("mcp_create", e) from e
        except sqlite3.OperationalError as e:
            raise _main.busy_503("mcp_create", e) from e
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
            raise _main.busy_503("mcp_create", e) from e
        return {"name": name, "path": f"/templates/{name}"}
    if segs[0] == "shared":
        raise _bad("Cannot create in the shared namespace", 403)
    raise _bad("create needs a /docs/{Title}[/{File}] or /templates/{Name}.typ path")


def _recheck_edit(user: str, cap: str, doc_id: str) -> None:
    """Role/trash re-check right before a file write (closes revoke races)."""
    from backend import main as _main

    con = db.connect()
    try:
        row = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
    finally:
        con.close()
    if not row:
        raise _bad("Doc gone", 404)
    if row["trashed"]:
        raise _bad("In trash - restore first", 410)
    if _main.cap_min(cap, db.doc_role(user, doc_id) or "") not in ("owner", "editor"):
        raise _bad("Reviewer can only comment", 403)


def _write_text_file(doc_id: str, filename: str, content: str, user: str, cap: str, must_create: bool) -> None:
    """Same write path as save_file_text: upload lock, tmp+replace, quota, touch."""
    from backend import main as _main

    if len(content) > MAX_TXT:
        raise _bad("Max 200 KB")
    with _main._doc_lock(f"upload:{doc_id}"):
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
            try:
                if old is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(old)
            except OSError:
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
        except sqlite3.OperationalError as e:
            raise _main.busy_503("mcp_write", e) from e
        _main.touch_doc(doc_id)


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
    from backend import main as _main

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
                        if _main.cap_min(cap, db.doc_role(user, doc_id) or "") not in ("owner", "editor"):
                            raise _bad("Reviewer can only comment", 403)
                        con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                                    (new_text, db.now_iso(), doc_id))
                except sqlite3.OperationalError as e:
                    raise _main.busy_503("mcp_edit", e) from e
        except sqlite3.OperationalError as e:
            raise _main.busy_503("mcp_edit", e) from e
        try:
            # Snapshot of the pre-edit state (old_db): after the commit so a
            # failed edit leaves no stray snapshot; failures only warn.
            _main.auto_snap(doc_id, old_db, label="mcp-edit")
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
                    raise _main.busy_503("mcp_edit", e) from e
        except sqlite3.OperationalError as e:
            raise _main.busy_503("mcp_edit", e) from e
        finally:
            con.close()
    new_marker = _current_text(user, resolve_path(user, cap, path))[1]
    return {"ok": True, "replaced": replaced, "last_seen": new_marker, "stale": stale}


def op_search(user: str, cap: str, query: str) -> dict:
    _ = cap  # read access is enough (resolve already gates per doc)
    q = query.strip()[:50]
    if len(q) < 2:
        return {"hits": []}
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT d.id, d.title, d.owner, d.content FROM docs d LEFT JOIN shares s "
            "ON s.doc_id=d.id AND s.username=? WHERE d.trashed=0 AND (d.owner=? OR s.username=?) "
            "AND (d.title LIKE ? ESCAPE '\\' OR d.content LIKE ? ESCAPE '\\') "
            "ORDER BY d.updated_at DESC LIMIT 20", (user, user, user, like, like)).fetchall()
        hits = []
        for r in rows:
            live = sync.room_text(r["id"])
            txt = live if live is not None else r["content"]
            i = txt.lower().find(q.lower())
            snippet = ("..." + txt[max(0, i - 40):i + 80].replace("\n", " ") + "...") if i >= 0 else ""
            base = f"/docs/{r['title']}" if r["owner"] == user else f"/shared/{r['owner']}/{r['title']}"
            hits.append({"path": base, "title": r["title"], "owner": r["owner"],
                         "snippet": snippet, "pos": i})
        return {"hits": hits}
    finally:
        con.close()


def op_upload(user: str, cap: str, path: str, content_base64: str, filename: str | None = None) -> dict:
    """Upload/replace a binary or text attachment. Path is /docs/{Titel}/{Datei}
    or /docs/{Titel} + filename. Same locks/quota/size rules as the UI upload."""
    from backend import main as _main

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
    n = _main.safe_name(fname)
    with _main._doc_lock(f"upload:{doc_id}"):
        _recheck_edit(user, cap, doc_id)
        uf = FastUploadFile(file=io.BytesIO(data), filename=n)
        return _main._upload_locked(doc_id, uf, n, user)


def op_comment(user: str, cap: str, path: str, anchor: int,
               text: str, quote: str = "", parent_id: str | None = None,
               author: str | None = None) -> dict:
    _ = cap  # any role with read access may comment (mirrors add_comment)
    res = resolve_path(user, cap, path)
    if res["kind"] != "doc":
        raise _bad("comments live on documents, use /docs/{Title}")
    if not isinstance(anchor, int) or anchor < 0 or anchor > 10_000_000:
        raise _bad("Anchor 0-10000000")
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
                    (cid, res["doc_id"], user, shown, anchor, q if q.strip() else "",
                     text.strip(), parent_id, db.now_iso()))
        con.commit()
        return {"id": cid}
    finally:
        con.close()


# --- view (M3): render doc pages as PNG via typst CLI ---

_VIEW_CACHE: dict[str, dict] = {}


def _view_key(doc_id: str, main_text: str, files: list[tuple[str, bytes]], pages: str) -> str:
    h = hashlib.sha256()
    h.update(_typst_tag().encode("utf-8"))
    h.update(b"\0")
    h.update(main_text.encode("utf-8"))
    for name, data in files:
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(data)
    return f"{doc_id}:{pages}:{h.hexdigest()}"


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


def _compile_pngs(main_text: str, files: list[tuple[str, bytes]], pages: str) -> list[bytes]:
    """Temp-dir typst compile, 10s timeout. Returns PNG bytes (<=5, width <=1024)."""
    typst = shutil.which("typst")
    if not typst:
        raise _bad("typst CLI missing (Dockerfile installs it)", 500)
    from PIL import Image as _Image

    with tempfile.TemporaryDirectory(prefix="mcp-view-") as tmp:
        root = Path(tmp)
        (root / "main.typ").write_text(main_text, encoding="utf-8")
        for name, data in files:
            if ".tmp." in name:
                continue
            (root / name).write_bytes(data)
        cmd = [typst, "compile", "--format", "png", "--ppi", "144",
               "--pages", pages, "main.typ", "page-{p}.png"]
        try:
            proc = subprocess.run(cmd, cwd=tmp, capture_output=True, timeout=VIEW_TIMEOUT)
        except subprocess.TimeoutExpired as e:
            raise _bad("compile timed out (10s)", 500) from e
        except OSError as e:
            raise _bad(f"compile failed: {e}", 500) from e
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()[-500:]
            raise _bad(f"compile error: {err or 'unknown'}")
        shots = sorted(root.glob("page-*.png"))[:VIEW_MAX_PAGES]
        if not shots:
            raise _bad("no pages rendered", 500)
        out = []
        for shot in shots:
            try:
                with _Image.open(shot) as im:
                    im.load()
                    if im.width > VIEW_MAX_WIDTH:
                        out.append(_png_bytes(im.resize(
                            (VIEW_MAX_WIDTH, round(im.height * VIEW_MAX_WIDTH / im.width)))))
                    else:
                        out.append(_png_bytes(im))
            except OSError as e:
                raise _bad(f"render failed: {e}", 500) from e
        return out


async def op_view(user: str, cap: str, path: str, pages: str = "1-5") -> dict:
    res = resolve_path(user, cap, path)
    if res["kind"] != "doc":
        raise _bad("view renders documents, use /docs/{Title}")
    if not _pages_ok(pages or ""):
        raise _bad("pages 1-5 only (e.g. 1-5 or 2)")
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
    key = _view_key(res["doc_id"], main_text, files, pages)
    hit = _view_cache_get(key)
    if hit is not None:
        return {"pages": [base64.b64encode(b).decode() for b in hit["pngs"]],
                "count": len(hit["pngs"]), "cache_hit": True, "last_seen": row["updated_at"]}
    pngs = await asyncio.to_thread(_compile_pngs, main_text, files, pages)
    _view_cache_put(key, {"pngs": pngs})
    return {"pages": [base64.b64encode(b).decode() for b in pngs],
            "count": len(pngs), "cache_hit": False, "last_seen": row["updated_at"]}
