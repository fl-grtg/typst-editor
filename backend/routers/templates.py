"""Account-global resources: .typ templates, .bib libraries, .csv tables.

One table, extension decides the kind (see services/resources.py). Old
.typ-only clients keep working: the list just carries extra kinds/fields.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from backend import db, deps, sync
from backend.constants import FOLDER_MAX, MAX_TXT
from backend.schemas import FolderRename, FolderSet, TplDuplicate, TplRename, TplSave
from backend.services import quota as quota_svc
from backend.services import resources as res
from backend.services.docfiles import store
from backend.services.sidebar import notify_sidebar

router = APIRouter()


def _gone_404(raw: str) -> str:
    try:
        return res.res_name(raw)
    except HTTPException:
        raise HTTPException(404, "Template gone") from None


@router.get("/api/templates")
def list_templates(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        return {"templates": res.list_resources(con, user)}
    finally:
        con.close()


@router.get("/api/resources")
def list_resources(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        return {"resources": res.list_resources(con, user)}
    finally:
        con.close()


@router.get("/api/templates/{name}")
def get_template(name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    n = _gone_404(name)
    con = db.connect()
    try:
        r = con.execute("SELECT name, content, line, folder, updated_at FROM templates "
                        "WHERE owner=? AND name=?", (user, n)).fetchone()
    finally:
        con.close()
    if not r:
        raise HTTPException(404, "Template gone")
    return {"name": r["name"], "content": r["content"] or "", "line": r["line"] or "",
            "folder": r["folder"] or "", "kind": res.kind_of(r["name"]),
            "version": r["updated_at"] or ""}


@router.post("/api/templates")
def save_template(b: TplSave, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    n = res.res_name(b.name)
    if res.is_reserved(n):
        raise HTTPException(400, "Reserved name")
    if len(b.content.encode("utf-8")) > MAX_TXT:
        raise HTTPException(400, "Text resource exceeds 200 KB")
    folder = (b.folder or "").strip()[:FOLDER_MAX]
    # Fail-fast quota estimate from a stale read; the authoritative old row
    # (and the version check) happen inside db.tx below.
    try:
        _c = db.connect()
        try:
            _stale = _c.execute("SELECT content FROM templates WHERE owner=? AND name=?",
                                (user, n)).fetchone()
        finally:
            _c.close()
    except sqlite3.OperationalError as e:
        raise deps.busy_503("save_template", e) from e
    _stale_len = len(((_stale["content"] or "") if _stale else "").encode("utf-8"))
    _box: dict = {"old": None}

    def _restore_tpl() -> None:
        old = _box.get("old")
        _rb = db.connect()
        try:
            if old is None:
                _rb.execute("DELETE FROM templates WHERE owner=? AND name=?", (user, n))
            else:
                _rb.execute("UPDATE templates SET content=?, folder=?, updated_at=? WHERE owner=? AND name=?",
                            (old["content"], old["folder"], old["updated_at"], user, n))
            _rb.commit()
        finally:
            _rb.close()

    now = ""
    try:
        with quota_svc.quota_guard(user, max(0, len(b.content.encode("utf-8")) - _stale_len),
                                   rollback=_restore_tpl):
            try:
                with db.tx() as con:
                    cur = con.execute("SELECT content, folder, updated_at FROM templates "
                                      "WHERE owner=? AND name=?", (user, n)).fetchone()
                    if b.folder is None and cur:
                        folder = cur["folder"] or ""
                    if b.version:
                        if not cur:
                            raise HTTPException(404, "Template gone")
                        if (cur["updated_at"] or "") != b.version:
                            raise HTTPException(409, {"message": "Changed elsewhere - reload first",
                                                      "current": {"content": cur["content"] or "",
                                                                  "version": cur["updated_at"] or ""}})
                    # Authoritative pre-write state for a correct quota rollback
                    # (the stale read above is fail-fast only).
                    _box["old"] = ({"content": cur["content"] or "", "folder": cur["folder"] or "",
                                    "updated_at": cur["updated_at"] or ""} if cur else None)
                    now = db.now_iso()
                    con.execute("INSERT INTO templates (owner, name, content, line, folder, updated_at) VALUES (?,?,?,?,?,?) "
                                "ON CONFLICT (owner, name) DO UPDATE SET content=excluded.content, line=excluded.line, "
                                "folder=excluded.folder, updated_at=excluded.updated_at",
                                (user, n, b.content, res.insert_line(n), folder, now))
                    deps.ensure_folder(con, user, "tpl", folder)
            except sqlite3.OperationalError as e:
                raise deps.busy_503("save_template", e) from e
    except sqlite3.OperationalError as e:
        raise deps.busy_503("save_template", e) from e
    quota_svc.invalidate_quota_cache(user)
    notify_sidebar(user)  # content + folder changes reach other tabs (list repaint never touches editors)
    return {"name": n, "version": now}


@router.post("/api/templates/{name}/duplicate")
def duplicate_template(name: str, b: TplDuplicate, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    src = _gone_404(name)
    dst = res.res_name(b.name) if b.name else res.copy_name(src)
    if res.is_reserved(dst):
        raise HTTPException(400, "Reserved name")
    if res.kind_of(src) != res.kind_of(dst):
        raise HTTPException(400, "Duplicate keeps the file type")
    try:
        _c = db.connect()
        try:
            _stale = _c.execute("SELECT content FROM templates WHERE owner=? AND name=?",
                                (user, src)).fetchone()
        finally:
            _c.close()
    except sqlite3.OperationalError as e:
        raise deps.busy_503("duplicate_template", e) from e
    if not _stale:
        raise HTTPException(404, "Template gone")
    _pre_len = len(((_stale["content"] or "")).encode("utf-8"))
    _box: dict = {"inserted": False}

    def _restore_dup() -> None:
        if not _box.get("inserted"):
            return
        try:
            _rb = db.connect()
            try:
                _rb.execute("DELETE FROM templates WHERE owner=? AND name=?", (user, dst))
                _rb.commit()
            finally:
                _rb.close()
        except Exception:
            pass

    try:
        with quota_svc.quota_guard(user, _pre_len, rollback=_restore_dup):
            try:
                with db.tx() as con:
                    row = con.execute("SELECT content, folder FROM templates WHERE owner=? AND name=?",
                                      (user, src)).fetchone()
                    if not row:
                        raise HTTPException(404, "Template gone")
                    if not b.name:
                        number = 1
                        while con.execute('SELECT 1 FROM templates WHERE owner=? AND name=?', (user, dst)).fetchone():
                            number += 1
                            dst = res.copy_name(src, number)
                    if con.execute("SELECT 1 FROM templates WHERE owner=? AND name=?",
                                   (user, dst)).fetchone():
                        raise HTTPException(400, "Name already exists")
                    con.execute("INSERT INTO templates (owner, name, content, line, folder, updated_at) "
                                "VALUES (?,?,?,?,?,?)",
                                (user, dst, row["content"] or "", res.insert_line(dst),
                                 row["folder"] or "", db.now_iso()))
                    _box["inserted"] = True
            except sqlite3.IntegrityError as e:
                raise HTTPException(400, "Name already exists") from e
            except sqlite3.OperationalError as e:
                raise deps.busy_503("duplicate_template", e) from e
    except sqlite3.OperationalError as e:
        raise deps.busy_503("duplicate_template", e) from e
    quota_svc.invalidate_quota_cache(user)
    notify_sidebar(user)
    return {"name": dst}


@router.post("/api/templates/{name}/rename")
def rename_template(name: str, b: TplRename, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    old, new = _gone_404(name), res.res_name(b.name)
    if res.is_reserved(new) or res.kind_of(old) != res.kind_of(new):
        raise HTTPException(400, "Rename keeps the file type and cannot use main.typ")
    try:
        with db.tx() as con:
            row = con.execute("SELECT updated_at FROM templates WHERE owner=? AND name=?", (user, old)).fetchone()
            if not row:
                raise HTTPException(404, "Template gone")
            if b.version and b.version != row["updated_at"]:
                raise HTTPException(409, "Changed elsewhere - reload first")
            if old == new:
                return {"name": old, "version": row["updated_at"]}
            if con.execute("SELECT 1 FROM templates WHERE owner=? AND name=?", (user, new)).fetchone():
                raise HTTPException(409, "Name already exists")
            version = db.now_iso()
            con.execute("UPDATE templates SET name=?, line=?, updated_at=? WHERE owner=? AND name=?",
                        (new, res.insert_line(new), version, user, old))
    except sqlite3.OperationalError as e:
        raise deps.busy_503("rename_template", e) from e
    notify_sidebar(user)
    return {"name": new, "version": version}


@router.delete("/api/templates/{name}")
def delete_template(name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    n = _gone_404(name)
    con = db.connect()
    try:
        cur = con.execute("DELETE FROM templates WHERE owner=? AND name=?", (user, n))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Template gone")
        quota_svc.invalidate_quota_cache(user)
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@router.post("/api/templates/{name}/folder")
def move_template(name: str, b: FolderSet, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    n = _gone_404(name)
    con = db.connect()
    try:
        cur = con.execute("UPDATE templates SET folder=?, updated_at=? WHERE owner=? AND name=?",
                    (b.folder.strip()[:FOLDER_MAX], db.now_iso(), user, n))
        deps.ensure_folder(con, user, "tpl", b.folder)
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Template gone")
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@router.get("/api/docs/{doc_id}/resources")
def doc_resources(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    """Effective compile resources for one doc: owner's reachable set only.

    Any role with doc access may read (reviewer incl.). `resources` holds
    just the reachable names (never the whole owner library); `local`
    lists doc-local text files (nested paths included), which win on exact
    path collisions. `versions` carries updated_at per reachable resource
    so owner tabs can show staleness. `readonly` tells the viewer the
    shelf is not theirs. Project members may browse their whole shared library;
    individual document guests still receive only reachable project resources.
    """
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    role = deps.need_access(user, doc_id)
    con = db.connect()
    try:
        d = con.execute("SELECT owner, content FROM docs WHERE id=?", (doc_id,)).fetchone()
    finally:
        con.close()
    if not d:
        raise HTTPException(404, "Doc gone")
    owner = d["owner"]
    live = sync.room_text(doc_id)
    main_text = live if live is not None else (d["content"] or "")
    local: dict[str, str] = {}
    try:
        for e in store.list(doc_id):
            if res.kind_of(e.path):
                try:
                    local[e.path] = store.get(doc_id, e.path).decode("utf-8", errors="replace")
                except (OSError, ValueError):
                    continue
    except (OSError, ValueError):
        pass
    out = res.doc_effective(owner, main_text, local, doc_id)
    out["readonly"] = role != "owner"
    if out["project_id"]:
        from backend.services import projects
        con = db.connect()
        try:
            try:
                project_role = projects.role(con, out["project_id"], user)
            except HTTPException:
                project_role = ""
            if project_role:
                rows = con.execute("SELECT name,content,updated_at FROM project_resources WHERE project_id=?", (out["project_id"],)).fetchall()
                out["resources"] = {r["name"]: r["content"] for r in rows if r["name"] not in local}
                out["versions"] = {r["name"]: r["updated_at"] for r in rows if r["name"] not in local}
            out["readonly"] = project_role not in ("owner", "editor")
        finally:
            con.close()
    return out


@router.get("/api/tplfolders")
def list_tpl_folders(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        return {"folders": deps._folder_counts(con, user, "tpl")}
    finally:
        con.close()


@router.post("/api/tplfolders")
def make_tpl_folder(b: FolderSet, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "folders")
    n = deps.check_folder_name(b.folder)
    con = db.connect()
    try:
        deps.ensure_folder(con, user, "tpl", n)
        con.commit()
        notify_sidebar(user)
        return {"folder": n}
    finally:
        con.close()


@router.post("/api/tplfolders/rename")
def rename_tpl_folder(b: FolderRename, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "tplfolders")
    old, new = b.old.strip()[:FOLDER_MAX], b.new.strip()[:FOLDER_MAX]
    if not old or not new or old == new:
        raise HTTPException(400, "Empty folder name")
    con = db.connect()
    try:
        con.execute("UPDATE templates SET folder=?, updated_at=? WHERE owner=? AND folder=?",
                    (new, db.now_iso(), user, old))
        con.execute("UPDATE OR IGNORE folders SET name=? WHERE owner=? AND kind='tpl' AND name=?",
                    (new, user, old))
        con.commit()
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@router.delete("/api/tplfolders/{name}")
def drop_tpl_folder(name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "tplfolders")
    n = name.strip()[:FOLDER_MAX]
    con = db.connect()
    try:
        con.execute("UPDATE templates SET folder='' WHERE owner=? AND folder=?", (user, n))
        con.execute("DELETE FROM folders WHERE owner=? AND kind='tpl' AND name=?", (user, n))
        con.commit()
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


def tpl_name(name: str) -> str:
    """Backwards-compat name (old UI/MCP import it); .typ-only like before."""
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "").name.strip().lstrip("."))[:100]
    if not n.endswith(".typ"):
        raise HTTPException(404, "Template gone")
    return n
