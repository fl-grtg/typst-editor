"""Template and template-folder routes."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from backend import db, deps
from backend.constants import FOLDER_MAX, MAX_TXT
from backend.schemas import FolderRename, FolderSet, TplSave
from backend.services import quota as quota_svc
from backend.services.sidebar import notify_sidebar

router = APIRouter()


@router.get("/api/templates")
def list_templates(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        rows = con.execute("SELECT name, content, line, folder FROM templates WHERE owner=? ORDER BY name",
                           (user,)).fetchall()
        return {"templates": [dict(r) for r in rows]}
    finally:
        con.close()


@router.post("/api/templates")
def save_template(b: TplSave, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(b.name or "").name.strip().lstrip("."))[:100]
    if not n.endswith(".typ") or not b.content.strip() or len(b.content) > MAX_TXT:
        raise HTTPException(400, "Only .typ with content (max 200 KB)")
    try:
        _c = db.connect()
        try:
            _old = _c.execute("SELECT content, folder FROM templates WHERE owner=? AND name=?", (user, n)).fetchone()
        finally:
            _c.close()
    except sqlite3.OperationalError as e:
        raise deps.busy_503("save_template", e) from e
    _old_tpl = (_old["content"] or "") if _old else ""
    _old_tpl_len = len(_old_tpl.encode("utf-8"))

    def _restore_tpl() -> None:
        _rb = db.connect()
        try:
            if _old is None:
                _rb.execute("DELETE FROM templates WHERE owner=? AND name=?", (user, n))
            else:
                _rb.execute("UPDATE templates SET content=?, updated_at=? WHERE owner=? AND name=?",
                            (_old_tpl, db.now_iso(), user, n))
            _rb.commit()
        finally:
            _rb.close()

    try:
        with quota_svc.quota_guard(user, max(0, len(b.content.encode("utf-8")) - _old_tpl_len),
                                   rollback=_restore_tpl):
            con = db.connect()
            try:
                con.execute("INSERT INTO templates (owner, name, content, line, folder, updated_at) VALUES (?,?,?,?,?,?) "
                            "ON CONFLICT (owner, name) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
                            (user, n, b.content, f'#include "{n}"', b.folder.strip()[:FOLDER_MAX], db.now_iso()))
                deps.ensure_folder(con, user, "tpl", b.folder)
                con.commit()
            finally:
                con.close()
    except sqlite3.OperationalError as e:
        raise deps.busy_503("save_template", e) from e
    quota_svc.invalidate_quota_cache(user)
    if _old is None or (_old["folder"] or "") != b.folder.strip()[:FOLDER_MAX]:
        notify_sidebar(user)  # content-only updates don't change the list
    return {"name": n}


@router.delete("/api/templates/{name}")
def delete_template(name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    n = tpl_name(name)
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
    n = tpl_name(name)
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
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "").name.strip().lstrip("."))[:100]
    if not n.endswith(".typ"):
        raise HTTPException(404, "Template gone")
    return n
