"""Project folders: nested paths inside one project (project files and documents).

Entries carry their folder in the path ("a/b/x.typ"; documents in `docs.folder`),
so a folder only needs a row of its own while it is empty (`project_folders`).
Depth is capped by MAX_FOLDER_DEPTH; deeper legacy paths stay readable.
"""
from __future__ import annotations

import asyncio
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend import db, deps, sync
from backend.constants import MAX_FOLDER_DEPTH
from backend.services import project_files, projects, quota, trash
from backend.services.docfiles import safe_name
from backend.services.sidebar import notify_sidebar

router = APIRouter()


class FolderPath(BaseModel):
    path: str = Field(min_length=1, max_length=240)


class FolderRename(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    target: str = Field(min_length=1, max_length=240)
    fix_refs: bool = True


class DocFolder(BaseModel):
    folder: str = Field(default="", max_length=240)
    fix_refs: bool = True


def folder_path(raw: str, *, new: bool = True) -> str:
    """Clean folder path ("a/b"). New paths are capped at MAX_FOLDER_DEPTH;
    existing deeper legacy paths stay usable for rename and delete."""
    n = safe_name((raw or "").strip().strip("/") + "/x")[:-2]
    if not n:
        raise HTTPException(400, "Folder path is empty")
    if new and n.count("/") + 1 > MAX_FOLDER_DEPTH:
        raise HTTPException(400, f"Folders can be nested at most {MAX_FOLDER_DEPTH} levels deep")
    return n


def _within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


def _moved(path: str, old: str, new: str) -> str:
    return new + path[len(old):]


def _moved_depth(path: str, old: str, new: str, *, folder: bool = False) -> str:
    """Moving an entry inside a renamed folder may keep a legacy depth, but
    never adds a level beyond MAX_FOLDER_DEPTH relative to where it came from.
    File paths carry their name in the last segment; folder paths do not."""
    target = _moved(path, old, new)
    extra = 1 if folder else 0  # a folder path of n segments is n levels, a file path n-1
    if target.strip("/").count("/") + extra > max(MAX_FOLDER_DEPTH, path.strip("/").count("/") + extra):
        raise HTTPException(400, f"Folders can be nested at most {MAX_FOLDER_DEPTH} levels deep")
    return target


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
async def rename_folder(project_id: str, b: FolderRename, req: Request, user: str = Depends(deps.me)) -> dict:
    """Everything inside moves along; every quoted reference in the project keeps reaching its file."""
    deps.limited(req, "rename")
    old, new = folder_path(b.path, new=False), folder_path(b.target)
    if old == new:
        return {"path": new, "updated_references": 0}
    if _within(new, old):
        raise HTTPException(400, "A folder cannot move into itself")
    docs, paths, moves = await asyncio.to_thread(_rename_folder, project_id, old, new, user, b.fix_refs)
    changed = await project_files.relocate_docs(docs, moves, paths, "folder move")
    # notify() -> auto() -> prepared() takes the files lock; call it after release.
    await asyncio.to_thread(projects.notify, project_id)
    return {"path": new, "updated_references": changed}


def _folder_moves(con: sqlite3.Connection, project_id: str, old: str, new: str) -> tuple[dict[str, str], dict[str, str]]:
    """Files (old -> new path) and documents (id -> new folder) a folder rename moves."""
    files = {p: _moved_depth(p, old, new) for (p,) in con.execute("SELECT path FROM project_files WHERE project_id=?", (project_id,)) if _within(p, old)}
    docs = {i: _moved_depth(f, old, new, folder=True) for i, f in con.execute("SELECT id,folder FROM docs WHERE project_id=? AND trashed=0", (project_id,))
            if f and _within(f, old)}
    return files, docs


@router.post("/api/projects/{project_id}/folders/rename-preview")
def rename_folder_preview(project_id: str, b: FolderRename, req: Request, user: str = Depends(deps.me)) -> dict:
    """The quoted references a folder rename would update (the dialog lists them)."""
    deps.limited(req, "files_list")
    old, new = folder_path(b.path, new=False), folder_path(b.target)
    con = db.connect()
    try:
        projects.require(con, project_id, user, edit=True)
        files, docs = _folder_moves(con, project_id, old, new)
        return {"path": new, "changes": project_files.ref_changes(con, project_id, files, docs)}
    finally:
        con.close()


def _rename_folder(project_id: str, old: str, new: str, user: str, fix_refs: bool = True) -> tuple[list[tuple[str, str, str]], set[str], dict[str, str]]:
    backups: project_files.Backups = {}
    docs: list[tuple[str, str, str]] = []
    with project_files.lock(project_id):
        try:
            with db.tx() as con:
                projects.require(con, project_id, user, edit=True)
                now = db.now_iso()
                moves = {p: _moved_depth(p, old, new) for (p,) in con.execute("SELECT path FROM project_files WHERE project_id=?", (project_id,)) if _within(p, old)}
                for i, f, title in con.execute("SELECT id,folder,title FROM docs WHERE project_id=? AND trashed=0", (project_id,)).fetchall():
                    target = _moved_depth(f, old, new, folder=True) if f and _within(f, old) else f
                    docs.append((i, f, target))
                    if target != f:
                        # Titles are unique per folder, so a rename can collide only here.
                        if con.execute("SELECT 1 FROM docs WHERE project_id=? AND folder=? AND title=? COLLATE NOCASE AND trashed=0 AND id<>?",
                                       (project_id, target, title, i)).fetchone():
                            raise HTTPException(409, "Document title already exists in target folder")
                        con.execute("UPDATE docs SET folder=? WHERE id=?", (target, i))
                staying = {p.casefold() for (p,) in con.execute("SELECT path FROM project_files WHERE project_id=?", (project_id,)) if not _within(p, old)}
                if any(n.casefold() in staying for n in moves.values()):
                    raise HTTPException(409, "Name already exists in this project")
                paths = project_files.relocate_files(con, project_id, moves, backups, fix_refs)
                if not fix_refs:
                    docs = []
                rows = [r[0] for r in con.execute("SELECT path FROM project_folders WHERE project_id=?", (project_id,))]
                for p in rows:
                    if _within(p, old):
                        con.execute("DELETE FROM project_folders WHERE project_id=? AND path=?", (project_id, p))
                parts = new.split("/")
                for p in ["/".join(parts[:i]) for i in range(1, len(parts) + 1)] + [_moved_depth(p, old, new, folder=True) for p in rows if _within(p, old)]:
                    con.execute("INSERT OR IGNORE INTO project_folders VALUES (?,?,?)", (project_id, p, now))
        except Exception:
            project_files.undo(backups)
            raise
    return docs, paths, moves


@router.delete("/api/projects/{project_id}/folders")
async def delete_folder(project_id: str, path: str, req: Request, user: str = Depends(deps.me)) -> dict:
    """The folder goes with everything below it: documents and files move to the trash."""
    import asyncio

    deps.limited(req, "delete")
    folder = folder_path(path, new=False)

    def run() -> tuple[list[str], list[str], list[str], str]:
        backups: project_files.Backups = {}
        trash_ids: list[str] = []
        folders: list[str] = []
        with project_files.lock(project_id):
            try:
                with db.tx() as con:
                    projects.require(con, project_id, user, edit=True)
                    owner = project_files.owner_of(con, project_id)
                    docs = [r[0] for r in con.execute("SELECT id,folder FROM docs WHERE project_id=? AND trashed=0", (project_id,)) if r[1] and _within(r[1], folder)]
                    for did in docs:
                        con.execute("UPDATE docs SET trashed=1,updated_at=? WHERE id=?", (db.now_iso(), did))
                    for (p,) in con.execute("SELECT path FROM project_files WHERE project_id=?", (project_id,)).fetchall():
                        if _within(p, folder):
                            trash_ids.append(trash.archive(con, owner, "file", p, project_files.remove(con, project_id, p, backups), project_id=project_id))
                    for r in con.execute("SELECT path FROM project_folders WHERE project_id=?", (project_id,)).fetchall():
                        if _within(r[0], folder):
                            folders.append(r[0])
                            con.execute("DELETE FROM project_folders WHERE project_id=? AND path=?", (project_id, r[0]))
            except Exception:
                project_files.undo(backups)
                raise
        return docs, trash_ids, folders, owner

    docs, trash_ids, folders, owner = await asyncio.to_thread(run)
    for did in docs:
        await sync.drop(did)
    quota.invalidate_quota_cache(owner)
    await asyncio.to_thread(projects.notify, project_id)
    for u in {user, owner}:
        notify_sidebar(u)
    return {"ok": True, "documents": docs, "trash_ids": trash_ids, "folders": folders}


@router.post("/api/projects/{project_id}/docs/{doc_id}/folder-preview")
def move_document_preview(project_id: str, doc_id: str, b: DocFolder, req: Request, user: str = Depends(deps.me)) -> dict:
    """The quoted references of the document that a move to `folder` would update."""
    deps.limited(req, "files_list")
    folder = folder_path(b.folder) if b.folder.strip("/") else ""
    con = db.connect()
    try:
        projects.require(con, project_id, user, edit=True)
        return {"folder": folder, "changes": project_files.ref_changes(con, project_id, {}, {doc_id: folder})}
    finally:
        con.close()


@router.post("/api/projects/{project_id}/docs/{doc_id}/folder")
async def move_document(project_id: str, doc_id: str, b: DocFolder, req: Request, user: str = Depends(deps.me)) -> dict:
    """The document moves to another folder; its relative references keep reaching their files."""
    deps.limited(req, "move")
    folder = folder_path(b.folder) if b.folder.strip("/") else ""

    def run() -> tuple[str, set[str]]:
        try:
            with db.tx() as con:
                projects.require(con, project_id, user, edit=True)
                row = con.execute("SELECT folder FROM docs WHERE id=? AND project_id=? AND trashed=0", (doc_id, project_id)).fetchone()
                if not row:
                    raise HTTPException(404, "Document not found")
                con.execute("UPDATE docs SET folder=? WHERE id=?", (folder, doc_id))
                return row[0], {r[0] for r in con.execute("SELECT path FROM project_files WHERE project_id=?", (project_id,))}
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, "Document title already exists in this folder") from e

    old, paths = await asyncio.to_thread(run)
    changed = await project_files.relocate_docs([(doc_id, old, folder)], {}, paths, "move") if old != folder and b.fix_refs else 0
    await asyncio.to_thread(projects.notify, project_id)
    return {"folder": folder, "updated_references": changed}
