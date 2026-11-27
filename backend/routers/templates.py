"""Account-global resources: .typ templates, .bib libraries, .csv tables.

One table, extension decides the kind (see services/resources.py). Old
.typ-only clients keep working: the list just carries extra kinds/fields.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from backend import db, deps
from backend.constants import FOLDER_MAX, MAX_TXT
from backend.schemas import FolderRename, FolderSet, TplDuplicate, TplRename, TplSave
from backend.services import quota as quota_svc
from backend.services import resources as res
from backend.services import trash
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
    lang = deps.req_lang(req)
    src = _gone_404(name)
    dst = res.res_name(b.name) if b.name else res.copy_name(src, lang=lang)
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
                            dst = res.copy_name(src, number, lang)
                    if con.execute("SELECT 1 FROM templates WHERE owner=? AND name=?",
                                   (user, dst)).fetchone():
                        raise HTTPException(409, "Name already exists")
                    con.execute("INSERT INTO templates (owner, name, content, line, folder, updated_at) "
                                "VALUES (?,?,?,?,?,?)",
                                (user, dst, row["content"] or "", res.insert_line(dst),
                                 row["folder"] or "", db.now_iso()))
                    _box["inserted"] = True
            except sqlite3.IntegrityError as e:
                raise HTTPException(409, "Name already exists") from e
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
        raise HTTPException(400, "Rename keeps the file type and cannot use a reserved name")
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
    except sqlite3.IntegrityError as e:
        raise HTTPException(409, "Name already exists") from e
    except sqlite3.OperationalError as e:
        raise deps.busy_503("rename_template", e) from e
    notify_sidebar(user)
    return {"name": new, "version": version}


@router.delete("/api/templates/{name}")
def delete_template(name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    n = _gone_404(name)
    try:
        with db.tx() as con:
            row = con.execute("SELECT * FROM templates WHERE owner=? AND name=?", (user, n)).fetchone()
            if not row:
                raise HTTPException(404, "Template gone")
            trash_id = trash.archive(con, user, "personal", n, (row["content"] or "").encode(),
                          line=row["line"] or "", folder=row["folder"] or "")
            con.execute("DELETE FROM templates WHERE owner=? AND name=?", (user, n))
    except sqlite3.OperationalError as e:
        raise deps.busy_503("delete_template", e) from e
    quota_svc.invalidate_quota_cache(user)
    notify_sidebar(user)
    return {"ok": True, "trash_id": trash_id}


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
    """What one document compiles against: its project, its compile entry (`F/__doc__.typ`) and the
    project files it reaches (`files`, with size and version). `readonly` = no project edit right."""
    from backend.services import fonts as fonts_svc
    from backend.services import project_files, projects

    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    con = db.connect()
    try:
        d = con.execute("SELECT project_id, folder, content FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "Doc gone")
        rows = project_files.listing(con, d["project_id"]) if d["project_id"] else []
        paths = {r["path"] for r in rows}
        reached = res.reachable(paths, project_files.texts(con, d["project_id"]) if rows else {},
                                d["folder"], project_files.doc_text(doc_id, d["content"]))
        reached |= {p for p in paths if fonts_svc.is_font_path(p)}
        try:
            readonly = projects.role(con, d["project_id"], user) not in ("owner", "editor")
        except HTTPException:
            readonly = True
    finally:
        con.close()
    return {"project_id": d["project_id"], "folder": d["folder"], "entry": project_files.entry(d["folder"]),
            "files": [{k: r[k] for k in ("path", "size", "version")} for r in rows if r["path"] in reached], "readonly": readonly}


@router.get("/api/tplfolders")
def list_tpl_folders(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        return {"folders": deps._folder_counts(con, user)}
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
    n = res.clean_segment(Path(name or "").name)
    if not n.endswith(".typ"):
        raise HTTPException(404, "Template gone")
    return n
