"""Project files: one file tree per project, next to its documents.

Bytes live at <files>/<project_id>/<path> (docfiles.store keyed by the project id), one row per file in
project_files (quota and listings read the rows). A document in folder F compiles as F/__doc__.typ inside
that tree, so quoted references resolve like Typst does: relative to the quoting file, "/x" from the root.
Mutations hold the named lock "files:<project_id>" and call projects.notify only after releasing it
(the checkpoint in notify takes the same lock).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import posixpath
import re
import sqlite3
import time

from fastapi import HTTPException
from pycrdt import Doc, Text

from backend import config, db, deps, sync
from backend.constants import ENTRY, MAX_TXT, TITLE_MAX, UPLOAD_MAX
from backend.services import fonts as fonts_svc
from backend.services import projects, quota, resources, trash
from backend.services.docfiles import check_depth, file_type, safe_name, safe_rename_target, store
from backend.services.locks import _named_lock
from backend.services.sidebar import notify_sidebar

log = logging.getLogger("typst.main")

Backups = dict[tuple[str, str], bytes | None]


def version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def lock(project_id: str):
    return _named_lock(f"files:{project_id}")


def clean(path: str, *, new: bool = True) -> str:
    p = safe_name(path, new=new)
    if any(s.lower() == ENTRY for s in p.split("/")):
        raise HTTPException(400, f"The name {ENTRY} is reserved")
    return p


def is_text(path: str) -> bool:
    return posixpath.splitext(path)[1].lower() in deps.TEXT_SUFFIX


def listing(con: sqlite3.Connection, project_id: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT path,size,version,updated_at FROM project_files WHERE project_id=? ORDER BY path", (project_id,))]


def read(project_id: str, path: str) -> bytes:
    try:
        return store.get(project_id, path)
    except FileNotFoundError:
        raise HTTPException(404, "File not found") from None


def texts(con: sqlite3.Connection, project_id: str, suffixes: tuple[str, ...] = (".typ",)) -> dict[str, str]:
    out = {}
    for (path,) in con.execute("SELECT path FROM project_files WHERE project_id=?", (project_id,)):
        if path.lower().endswith(suffixes):
            try:
                out[path] = store.get(project_id, path).decode("utf-8", errors="replace")
            except OSError:
                continue
    return out


def doc_text(doc_id: str, stored: str) -> str:
    live = sync.room_text(doc_id)
    return stored if live is None else live


def entry(folder: str) -> str:
    """Compile path of a document in `folder`."""
    return posixpath.join(folder, ENTRY) if folder else ENTRY


def visible(con: sqlite3.Connection, project_id: str, user: str) -> set[str] | None:
    """Paths the user may see: None = every file (owner, member); a guest of single documents sees what those reach."""
    try:
        projects.role(con, project_id, user)
        return None
    except HTTPException:
        pass
    docs = [d for d in con.execute("SELECT id,folder,content FROM docs WHERE project_id=? AND trashed=0", (project_id,))
            if db.role_on(con, user, d["id"])]
    if not docs:
        raise HTTPException(404, "Project not found")
    paths = {r[0] for r in con.execute("SELECT path FROM project_files WHERE project_id=?", (project_id,))}
    typ = texts(con, project_id)
    got: set[str] = {p for p in paths if fonts_svc.is_font_path(p)}
    for d in docs:
        got |= resources.reachable(paths, typ, d["folder"], doc_text(d["id"], d["content"]))
    return got


def _old(project_id: str, path: str) -> bytes | None:
    try:
        return store.get(project_id, path)
    except FileNotFoundError:
        return None


def put(con: sqlite3.Connection, project_id: str, path: str, data: bytes, backups: Backups) -> str:
    """Write one file inside the caller's transaction (no permission or quota check); backups keeps the old bytes for undo()."""
    if len(data) > (MAX_TXT if is_text(path) else UPLOAD_MAX):
        raise HTTPException(413, "File too large (text 200 KB, other files 10 MB)")
    row = con.execute("SELECT path FROM project_files WHERE project_id=? AND path=? COLLATE NOCASE", (project_id, path)).fetchone()
    if row and row[0] != path:
        raise HTTPException(409, f"Name already exists in this project: {row[0]}")
    if not row:
        if con.execute("SELECT COUNT(*) FROM project_files WHERE project_id=?", (project_id,)).fetchone()[0] >= config.load().MAX_FILES_PER_DOC:
            raise HTTPException(400, "Too many files in this project")
        # A file cannot sit where a folder of other files is, nor below another file.
        if con.execute("SELECT 1 FROM project_files WHERE project_id=? AND (substr(lower(path),1,?)=lower(?)||'/' OR substr(lower(?),1,length(path)+1)=lower(path)||'/')",
                       (project_id, len(path) + 1, path, path)).fetchone():
            raise HTTPException(409, "A file and a folder cannot share a name")
    v = version(data)
    con.execute("INSERT INTO project_files(project_id,path,size,mtime,type,version,updated_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(project_id,path) DO UPDATE SET size=excluded.size,mtime=excluded.mtime,version=excluded.version,updated_at=excluded.updated_at",
                (project_id, path, len(data), time.time(), file_type(path), v, db.now_iso()))
    backups.setdefault((project_id, path), _old(project_id, path))
    store.put(project_id, path, data)
    return v


def remove(con: sqlite3.Connection, project_id: str, path: str, backups: Backups) -> bytes:
    """Delete one file inside the caller's transaction; returns its bytes."""
    data = read(project_id, path)
    con.execute("DELETE FROM project_files WHERE project_id=? AND path=?", (project_id, path))
    backups.setdefault((project_id, path), data)
    store.delete(project_id, path)
    return data


def undo(backups: Backups) -> None:
    for (project_id, path), data in backups.items():
        try:
            if data is None:
                store.delete(project_id, path)
            else:
                store.put(project_id, path, data)
        except OSError as e:
            log.warning("project file undo %s/%s failed: %s", project_id, path, e)


def owner_of(con: sqlite3.Connection, project_id: str) -> str:
    return con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()[0]


def _current(con: sqlite3.Connection, project_id: str, path: str, version_: str | None, force: bool) -> sqlite3.Row:
    row = con.execute("SELECT path,version FROM project_files WHERE project_id=? AND path=?", (project_id, path)).fetchone()
    if not row:
        raise HTTPException(404, "File not found")
    if not force and version_ != row["version"]:
        raise HTTPException(409, "File changed meanwhile; reload it")
    return row


def write(project_id: str, path: str, data: bytes, user: str, *, version_: str | None = None, force: bool = False) -> dict:
    """Create or overwrite a file. Overwriting needs the current version unless forced."""
    path = clean(path, new=False)
    backups: Backups = {}
    with lock(project_id):
        try:
            with db.tx() as con:
                projects.require(con, project_id, user, edit=True)
                row = con.execute("SELECT version FROM project_files WHERE project_id=? AND path=?", (project_id, path)).fetchone()
                if row and not force and version_ != row["version"]:
                    raise HTTPException(409, "File exists or changed meanwhile; reload it or choose another name")
                if not row:
                    if version_ and not force:
                        raise HTTPException(409, "File removed meanwhile; keep your draft")
                    check_depth(path)
                v = put(con, project_id, path, data, backups)
                owner = owner_of(con, project_id)
                quota.check_quota(owner, 0, con)
        except Exception:
            undo(backups)
            raise
    quota.invalidate_quota_cache(owner)
    projects.notify(project_id)
    return {"path": path, "version": v}


def delete(project_id: str, path: str, user: str, *, version_: str | None = None, force: bool = False) -> dict:
    """Move a file to the trash of the project owner."""
    path = clean(path, new=False)
    backups: Backups = {}
    with lock(project_id):
        try:
            with db.tx() as con:
                projects.require(con, project_id, user, edit=True)
                _current(con, project_id, path, version_, force)
                owner = owner_of(con, project_id)
                trash_id = trash.archive(con, owner, "file", path, remove(con, project_id, path, backups), project_id=project_id)
        except Exception:
            undo(backups)
            raise
    quota.invalidate_quota_cache(owner)
    projects.notify(project_id)
    for u in {user, owner}:
        notify_sidebar(u)
    return {"ok": True, "trash_id": trash_id}


def relocate_refs(text: str, old_base: str, new_base: str, moves: dict[str, str], paths: set[str]) -> str:
    """References of a text that moves from folder old_base to new_base (or stays: same base) while files move
    per `moves` (old -> new path): each keeps reaching the file it reached. Absolute stays absolute."""
    def fix(m) -> str:
        ref = m.group(1)
        hit = resources.resolve(old_base, ref)
        if hit not in paths:
            return m.group(0)
        target = moves.get(hit, hit)
        if resources.resolve(new_base, ref) == target:
            return m.group(0)
        return '"' + ("/" + target if ref.strip().startswith("/") else posixpath.relpath(target, new_base or ".")) + '"'
    return resources.REF_RE.sub(fix, text)


def rewrite(text: str, base: str, old: str, new: str) -> str:
    """Quoted references from a text in folder `base` to `old` now name `new`."""
    return relocate_refs(text, base, base, {old: new}, {old})


def relocate_files(con: sqlite3.Connection, project_id: str, moves: dict[str, str], backups: Backups, fix_refs: bool = True) -> set[str]:
    """Move files per `moves` inside the caller's transaction. With fix_refs every .typ file (moved or not) keeps
    reaching what it reached. Returns the project paths before the move (the documents' rewrite needs them)."""
    paths = {r[0] for r in con.execute("SELECT path FROM project_files WHERE project_id=?", (project_id,))}
    typ = texts(con, project_id) if fix_refs else {}
    data = {old: remove(con, project_id, old, backups) for old in moves}
    for old, new in moves.items():
        if old in typ:
            data[old] = relocate_refs(typ.pop(old), posixpath.dirname(old), posixpath.dirname(new), moves, paths).encode()
        put(con, project_id, new, data[old], backups)
    for p, text in typ.items():
        if (fixed := relocate_refs(text, posixpath.dirname(p), posixpath.dirname(p), moves, paths)) != text:
            put(con, project_id, p, fixed.encode(), backups)
    return paths


async def relocate_docs(docs: list[tuple[str, str, str]], moves: dict[str, str], paths: set[str], label: str) -> int:
    """Documents (id, old folder, new folder) keep reaching the files they reached; live rooms get minimal edits."""
    changed = 0
    for doc_id, old_folder, new_folder in docs:
        def fn(text: str, old_folder: str = old_folder, new_folder: str = new_folder) -> str:
            return relocate_refs(text, old_folder, new_folder, moves, paths)
        old = await asyncio.to_thread(sync.room_text, doc_id)
        if old is None:
            con = db.connect()
            try:
                old = con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()[0]
            finally:
                con.close()
        if fn(old) != old:
            await edit_doc_refs(doc_id, fn, label)
            changed += 1
    return changed


def referrers(con: sqlite3.Connection, project_id: str, path: str) -> list[str]:
    """Texts quoting `path`: "Folder/Title: ref" for documents, "file/path: ref" for files."""
    out = set()
    for d in con.execute("SELECT id,title,folder,content FROM docs WHERE project_id=? AND trashed=0", (project_id,)):
        for m in resources.REF_RE.finditer(doc_text(d["id"], d["content"])):
            if resources.resolve(d["folder"], m.group(1)) == path:
                out.add(f"{posixpath.join(d['folder'], d['title'])}: {m.group(1)}")
    for p, text in texts(con, project_id).items():
        for m in resources.REF_RE.finditer(text):
            if p != path and resources.resolve(posixpath.dirname(p), m.group(1)) == path:
                out.add(f"{p}: {m.group(1)}")
    return sorted(out)


def _target(path: str, target: str) -> str:
    t = safe_rename_target(target, path)
    clean(t, new=False)
    return t


def ref_changes(con: sqlite3.Connection, project_id: str, moves: dict[str, str], doc_moves: dict[str, str] | None = None) -> list[dict]:
    """What moving files (`moves`, old -> new path) and documents (`doc_moves`, id -> new folder) rewrites:
    {"in": text, "old": quoted ref, "new": quoted ref afterwards} for every quoted reference that changes."""
    doc_moves = doc_moves or {}
    paths = {r[0] for r in con.execute("SELECT path FROM project_files WHERE project_id=?", (project_id,))}
    texts_in = [(posixpath.join(d["folder"], d["title"]), d["folder"], doc_moves.get(d["id"], d["folder"]), doc_text(d["id"], d["content"]))
                for d in con.execute("SELECT id,title,folder,content FROM docs WHERE project_id=? AND trashed=0 ORDER BY folder,title", (project_id,))]
    texts_in += [(p, posixpath.dirname(p), posixpath.dirname(moves.get(p, p)), text) for p, text in sorted(texts(con, project_id).items())]
    out = []
    for name, old_base, new_base, text in texts_in:
        for m in resources.REF_RE.finditer(text):
            new = relocate_refs(m.group(0), old_base, new_base, moves, paths)[1:-1]
            if new != m.group(1) and (change := {"in": name, "old": m.group(1), "new": new}) not in out:
                out.append(change)
    return out


def move_preview(project_id: str, path: str, target: str, user: str) -> dict:
    path, target = clean(path, new=False), _target(path, target)
    con = db.connect()
    try:
        projects.require(con, project_id, user, edit=True, note=False)
        row = _current(con, project_id, path, None, True)
        return {"path": target, "version": row["version"], "references": referrers(con, project_id, path),
                "changes": ref_changes(con, project_id, {path: target})}
    finally:
        con.close()


def _move_files(project_id: str, path: str, target: str, user: str, version_: str | None, force: bool, fix_refs: bool) -> tuple[list[tuple[str, str, str]], set[str], str]:
    backups: Backups = {}
    with lock(project_id):
        try:
            with db.tx() as con:
                projects.require(con, project_id, user, edit=True)
                _current(con, project_id, path, version_, force)
                if target.lower() != path.lower() and con.execute(
                        "SELECT 1 FROM project_files WHERE project_id=? AND path=? COLLATE NOCASE", (project_id, target)).fetchone():
                    raise HTTPException(409, "Name already exists in this project")
                paths = relocate_files(con, project_id, {path: target}, backups, fix_refs)
                docs = [(d["id"], d["folder"], d["folder"]) for d in con.execute("SELECT id,folder FROM docs WHERE project_id=? AND trashed=0", (project_id,))] if fix_refs else []
                owner = owner_of(con, project_id)
                quota.check_quota(owner, 0, con)
        except Exception:
            undo(backups)
            raise
    return docs, paths, owner


async def edit_doc_refs(doc_id: str, fn, label: str) -> None:
    from backend.services import snapshots

    old, new = await sync.edit_doc(doc_id, fn)
    if old != new:
        try:
            snapshots.auto_snap(doc_id, old, label=label)
        except HTTPException:
            pass


async def move(project_id: str, path: str, target: str, user: str, *, version_: str | None = None, force: bool = False,
               fix_refs: bool = True) -> dict:
    """Rename or move a file; with fix_refs every text quoting it (and its own relative references) follows."""
    path, target = clean(path, new=False), _target(path, target)
    if target == path:
        return {"path": path, "updated_references": 0}
    docs, paths, owner = await asyncio.to_thread(_move_files, project_id, path, target, user, version_, force, fix_refs)
    changed = await relocate_docs(docs, {path: target}, paths, "move")
    quota.invalidate_quota_cache(owner)
    await asyncio.to_thread(projects.notify, project_id)
    return {"path": target, "updated_references": changed}


async def doc_to_file(project_id: str, doc_id: str, user: str) -> dict:
    """A document becomes <folder>/<Title>.typ; the document goes to the trash."""
    def run() -> tuple[str, str]:
        backups: Backups = {}
        with lock(project_id):
            try:
                with db.tx() as con:
                    projects.require(con, project_id, user, edit=True)
                    d = con.execute("SELECT title,folder,content FROM docs WHERE id=? AND project_id=? AND trashed=0", (doc_id, project_id)).fetchone()
                    if not d:
                        raise HTTPException(404, "Document not found")
                    path = clean(posixpath.join(d["folder"], d["title"] + ".typ"), new=False)
                    if con.execute("SELECT 1 FROM project_files WHERE project_id=? AND path=? COLLATE NOCASE", (project_id, path)).fetchone():
                        raise HTTPException(409, f"Name already exists in this project: {path}")
                    put(con, project_id, path, doc_text(doc_id, d["content"]).encode(), backups)
                    con.execute("UPDATE docs SET trashed=1,updated_at=? WHERE id=?", (db.now_iso(), doc_id))
                    owner = owner_of(con, project_id)
                    quota.check_quota(owner, 0, con)
            except Exception:
                undo(backups)
                raise
        return path, owner

    path, owner = await asyncio.to_thread(run)
    await sync.drop(doc_id)
    quota.invalidate_quota_cache(owner)
    await asyncio.to_thread(projects.notify, project_id)
    return {"path": path, "broken": []}


def file_to_doc(project_id: str, path: str, user: str) -> dict:
    """A .typ file becomes a document in its folder titled by its stem; the file goes to the trash.
    `broken` lists the texts that still quote it (a document cannot be included)."""
    path = clean(path, new=False)
    if not path.lower().endswith(".typ"):
        raise HTTPException(400, "Only .typ files can become documents")
    folder, title = posixpath.dirname(path), posixpath.splitext(posixpath.basename(path))[0]
    if not title or len(title) > TITLE_MAX:
        raise HTTPException(400, f"Title: 1-{TITLE_MAX} chars")
    backups: Backups = {}
    with lock(project_id):
        try:
            with db.tx() as con:
                projects.require(con, project_id, user, edit=True)
                owner = owner_of(con, project_id)
                broken = referrers(con, project_id, path)
                try:
                    text = read(project_id, path).decode("utf-8")
                except UnicodeDecodeError:
                    raise HTTPException(400, "The file is not UTF-8 text") from None
                if con.execute("SELECT 1 FROM docs WHERE project_id=? AND folder=? AND title=? COLLATE NOCASE AND trashed=0", (project_id, folder, title)).fetchone():
                    raise HTTPException(409, "Document title already exists in this folder")
                if con.execute("SELECT COUNT(*) FROM docs WHERE owner=?", (owner,)).fetchone()[0] >= config.load().MAX_DOCS_PER_USER:
                    raise HTTPException(400, "Too many docs")
                did, now = db.new_id("d_"), db.now_iso()
                con.execute("INSERT INTO docs(id,owner,title,content,folder,project_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                            (did, owner, title, text, folder, project_id, now, now))
                trash.archive(con, owner, "file", path, remove(con, project_id, path, backups), project_id=project_id)
                quota.check_quota(owner, 0, con)
        except Exception:
            undo(backups)
            raise
    quota.invalidate_quota_cache(owner)
    projects.notify(project_id)
    notify_sidebar(owner)
    return {"id": did, "title": title, "broken": broken}


FOLDER_BAD = re.compile(r'[\\:*?"<>|\x00-\x1f]')


def doc_folder(raw: str | None) -> str:
    """A document folder as stored: no empty segments, no outer spaces. ValueError for "..", "." or characters
    a file system cannot hold: the document compiles at <folder>/__doc__.typ inside the compile root."""
    parts = [s.strip() for s in (raw or "").split("/") if s.strip()]
    if any(s in (".", "..") or FOLDER_BAD.search(s) for s in parts):
        raise ValueError(f"bad folder: {raw!r}")
    return "/".join(parts)


# --- the layout before project files (migration v34, old project checkpoints) ---

def _free(path: str, taken: set[str], spelled: dict[str, str]) -> str:
    """A free spot for `path`: a file never sits where a folder is or below another file (casefolded `taken`
    holds files as "a/b.png" and folders as "a/"). A folder keeps the spelling it has; a file in its way makes it
    seg-2. A taken file name gets -2, -3, ... before its suffix."""
    *dirs, leaf = [s for s in path.split("/") if s]
    parent = ""
    for seg in dirs:
        cand, n = seg, 2
        while posixpath.join(parent, cand).casefold() in taken:
            cand, n = f"{seg}-{n}", n + 1
        here = posixpath.join(parent, cand)
        parent = spelled.setdefault(here.casefold(), here)
        taken.add(parent.casefold() + "/")
    stem, suffix = posixpath.splitext(leaf)
    out, n = posixpath.join(parent, leaf), 2
    while out.casefold() in taken or out.casefold() + "/" in taken or posixpath.basename(out).lower() == ENTRY:
        out, n = posixpath.join(parent, f"{stem}-{n}{suffix}"), n + 1
    taken.add(out.casefold())
    return out


def legacy_paths(existing: list[str], modules: list[str], docs: list[tuple[str, str, list[str]]],
                 folders: list[str] | None = None) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Old project modules (at their name) and attachments of each (doc id, folder F, paths) at F/path, one tree
    next to the `existing` project files. Document and empty `folders` stay folders: a file in their way yields.
    Deterministic for the same input."""
    taken: set[str] = set()
    spelled: dict[str, str] = {}
    for folder in sorted({f for f in [*(folders or []), *(d[1] for d in docs)] if f}):
        parent = ""
        for seg in folder.split("/"):
            parent = spelled.setdefault(posixpath.join(parent, seg).casefold(), posixpath.join(parent, seg))
            taken.add(parent.casefold() + "/")
    for path in existing:
        _free(path, taken, spelled)
    module_map = {n: _free(n, taken, spelled) for n in sorted(modules)}
    doc_maps = {did: {p: _free(posixpath.join(folder, p), taken, spelled) for p in sorted(paths)} for did, folder, paths in docs}
    return module_map, doc_maps


def legacy_refs(text: str, old_dir: str, new_dir: str, local: dict[str, str], modules: dict[str, str]) -> str:
    """Old compiles put the document at the root and every module and attachment at /path (attachments won).
    A reference that reached a file then and would miss its new path now becomes "/<new path>"."""
    def fix(m) -> str:
        hit = resources.resolve(old_dir, m.group(1))
        new = local.get(hit or "") or modules.get(hit or "")
        if not new or resources.resolve(new_dir, m.group(1)) == new:
            return m.group(0)
        return f'"/{new}"'
    return resources.REF_RE.sub(fix, text)


def yjs_with(yjs: bytes | None, text: str) -> bytes | None:
    """Stored CRDT state carrying `text`: only the changed spans enter it (never rebuilt from scratch)."""
    if yjs is None:
        return None
    doc: Doc = Doc()
    doc.apply_update(yjs)
    t = doc.get("typst", type=Text)
    old = str(t)
    with doc.transaction():
        sync.apply_spans(t, old, sync.text_spans(old, text))
    return doc.get_update()


def stored_text(content: str, yjs: bytes | None) -> str:
    if yjs is None:
        return content
    doc: Doc = Doc()
    doc.apply_update(yjs)
    return str(doc.get("typst", type=Text))

