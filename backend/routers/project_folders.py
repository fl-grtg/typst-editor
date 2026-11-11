"""Project folders: nested paths inside one project (modules, document files, documents).

Entries carry their folder in the path ("a/b/x.typ"; documents in `docs.folder`),
so a folder only needs a row of its own while it is empty (`project_folders`).
Depth is capped by MAX_FOLDER_DEPTH; deeper legacy paths stay readable.
"""
from __future__ import annotations

import os
from contextlib import ExitStack

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend import db, deps
from backend.constants import MAX_FOLDER_DEPTH
from backend.services import projects
from backend.services.docfiles import check_depth, file_type, safe_name, store
from backend.services.locks import _named_lock

router = APIRouter()


class FolderPath(BaseModel):
    path: str = Field(min_length=1, max_length=240)


class FolderRename(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    target: str = Field(min_length=1, max_length=240)


class DocFolder(BaseModel):
    folder: str = Field(default="", max_length=240)


def folder_path(raw: str) -> str:
    """Clean folder path ("a/b"), at most MAX_FOLDER_DEPTH levels."""
    n = safe_name((raw or "").strip().strip("/") + "/x")[:-2]
    if n.count("/") + 1 > MAX_FOLDER_DEPTH:
        raise HTTPException(400, f"Folders can be nested at most {MAX_FOLDER_DEPTH} levels deep")
    return n


def _within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


def _moved(path: str, old: str, new: str) -> str:
    return new + path[len(old):]


@router.post("/api/projects/{project_id}/folders")
def create_folder(project_id: str, b: FolderPath, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "create")
    path = folder_path(b.path)
    with db.tx() as con:
        projects.require(con, project_id, user, edit=True)
        # parents are implied, but an explicit row keeps an empty chain visible
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            con.execute("INSERT OR IGNORE INTO project_folders VALUES (?,?,?)", (project_id, "/".join(parts[:i]), db.now_iso()))
    projects.notify(project_id)
    return {"path": path}


@router.post("/api/projects/{project_id}/folders/rename")
def rename_folder(project_id: str, b: FolderRename, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "rename")
    old, new = folder_path(b.path), folder_path(b.target)
    if old == new:
        return {"path": new}
    if _within(new, old):
        raise HTTPException(400, "A folder cannot move into itself")
    pre = db.connect()
    try:
        projects.require(pre, project_id, user, edit=True)
        doc_ids = sorted(r[0] for r in pre.execute("SELECT id FROM docs WHERE project_id=? AND trashed=0", (project_id,)))
    finally:
        pre.close()
    with ExitStack() as stack:
        for d in doc_ids:  # sorted: one fixed lock order
            stack.enter_context(_named_lock(f"upload:{d}"))
        return _rename_locked(project_id, user, old, new, doc_ids)


def _rename_locked(project_id: str, user: str, old: str, new: str, doc_ids: list[str]) -> dict:
    moves: list[tuple[str, str, str]] = []  # (doc_id, old path, new path)
    for d in doc_ids:
        for e in store.list(d):
            if _within(e.path, old):
                target = check_depth(_moved(e.path, old, new))
                moves.append((d, e.path, target))
    moved_src = {(d, o) for d, o, _ in moves}
    with db.tx() as con:
        projects.require(con, project_id, user, edit=True)
        res = [r[0] for r in con.execute("SELECT name FROM project_resources WHERE project_id=?", (project_id,))]
        res_moves = [(n, check_depth(_moved(n, old, new))) for n in res if _within(n, old)]
        docs = [(r[0], r[1]) for r in con.execute("SELECT id,folder FROM docs WHERE project_id=? AND trashed=0", (project_id,))]
        doc_moves = [(i, _moved(f, old, new)) for i, f in docs if f and _within(f, old)]
        for _, f in doc_moves:
            folder_path(f)
        # every name in a project is one namespace: no collisions with what stays behind
        taken = {n.casefold() for n in res if not _within(n, old)}
        for d in doc_ids:
            taken |= {e.path.casefold() for e in store.list(d) if (d, e.path) not in moved_src}
        for target in [t for _, t in res_moves] + [t for _, _, t in moves]:
            if target.casefold() in taken:
                raise HTTPException(409, "Name already exists in this project")
            taken.add(target.casefold())
    done: list[tuple[str, str, str]] = []
    try:
        for d, o, n in moves:
            src, dst = store.doc_path(d, o), store.doc_path(d, n)
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)
            done.append((d, o, n))
        with db.tx() as con:
            projects.require(con, project_id, user, edit=True)
            now = db.now_iso()
            for d, o, n in moves:
                st = store.stat(d, n)
                con.execute("DELETE FROM files WHERE doc_id=? AND path=?", (d, o))
                con.execute("INSERT OR REPLACE INTO files(doc_id,path,size,mtime,type) VALUES (?,?,?,?,?)",
                            (d, n, st.size if st else 0, st.mtime if st else 0, file_type(n)))
            for o, n in res_moves:
                con.execute("UPDATE project_resources SET name=?,updated_at=? WHERE project_id=? AND name=?", (n, now, project_id, o))
            for i, f in doc_moves:
                con.execute("UPDATE docs SET folder=? WHERE id=?", (f, i))
            rows = [r[0] for r in con.execute("SELECT path FROM project_folders WHERE project_id=?", (project_id,))]
            for p in rows:
                if _within(p, old):
                    con.execute("DELETE FROM project_folders WHERE project_id=? AND path=?", (project_id, p))
            parts = new.split("/")
            for p in ["/".join(parts[:i]) for i in range(1, len(parts) + 1)] + [_moved(p, old, new) for p in rows if _within(p, old)]:
                con.execute("INSERT OR IGNORE INTO project_folders VALUES (?,?,?)", (project_id, p, now))
    except Exception:
        for d, o, n in reversed(done):
            try:
                os.rename(store.doc_path(d, n), store.doc_path(d, o))
            except OSError:
                pass
        raise
    projects.notify(project_id)
    return {"path": new}


@router.delete("/api/projects/{project_id}/folders")
def delete_folder(project_id: str, path: str, req: Request, user: str = Depends(deps.me)) -> dict:
    """Only empty folders go; moving or deleting the contents stays an explicit act."""
    deps.limited(req, "delete")
    folder = folder_path(path)
    with db.tx() as con:
        projects.require(con, project_id, user, edit=True)
        busy = any(_within(r[0], folder) for r in con.execute("SELECT name FROM project_resources WHERE project_id=?", (project_id,)))
        for did, docfolder in con.execute("SELECT id,folder FROM docs WHERE project_id=? AND trashed=0", (project_id,)):
            busy = busy or bool(docfolder and _within(docfolder, folder)) or any(_within(e.path, folder) for e in store.list(did))
        if busy:
            raise HTTPException(409, "Folder is not empty")
        for r in con.execute("SELECT path FROM project_folders WHERE project_id=?", (project_id,)).fetchall():
            if _within(r[0], folder):
                con.execute("DELETE FROM project_folders WHERE project_id=? AND path=?", (project_id, r[0]))
    projects.notify(project_id)
    return {"ok": True}


@router.post("/api/projects/{project_id}/docs/{doc_id}/folder")
def move_document(project_id: str, doc_id: str, b: DocFolder, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "move")
    folder = folder_path(b.folder) if b.folder.strip("/") else ""
    with db.tx() as con:
        projects.require(con, project_id, user, edit=True)
        if not con.execute("SELECT 1 FROM docs WHERE id=? AND project_id=? AND trashed=0", (doc_id, project_id)).fetchone():
            raise HTTPException(404, "Document not found")
        con.execute("UPDATE docs SET folder=? WHERE id=?", (folder, doc_id))
    projects.notify(project_id)
    return {"folder": folder}
