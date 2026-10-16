"""Shared project folders, membership and libraries."""
from __future__ import annotations

import asyncio
import hashlib
import json
import posixpath
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from backend import config, db, deps, sync
from backend.constants import MAX_TXT
from backend.schemas import Share
from backend.services import projects, quota, resources
from backend.services.docfiles import safe_name, store
from backend.services.sidebar import notify_sidebar

router = APIRouter()


class Convert(BaseModel):
    folder: str = Field(min_length=1, max_length=40)
    preview: str = ""


class ResourceSave(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=200001)
    version: str | None = None


class ProjectDoc(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    folder: str = Field(default="", max_length=240)
    content: str = Field(default="", max_length=200001)


def resource_name(name: str) -> str:
    n = safe_name(name)
    if not resources.kind_of(n) or resources.is_reserved(n):
        raise HTTPException(400, "Unsupported or reserved resource name")
    return n


def preview(con: sqlite3.Connection, user: str, folder: str) -> dict:
    existing = con.execute("SELECT project_id FROM legacy_project_folders WHERE owner=? AND folder=?", (user, folder.split("/")[0])).fetchone()
    if existing:
        p = projects.payload(con, existing[0], user)
        return {"id": existing[0], "documents": p["documents"], "resources": {}, "preview": existing[0]}
    docs = [dict(d) for d in con.execute("SELECT id, title, content, folder, updated_at, project_id FROM docs "
                                       "WHERE owner=? AND trashed=0 AND project_id IS NULL ORDER BY id", (user,))
            if d["folder"] == folder or d["folder"].startswith(folder + "/")]
    if not docs and not con.execute("SELECT 1 FROM folders WHERE owner=? AND kind='doc' AND name=?",
                                    (user, folder)).fetchone():
        raise HTTPException(404, "Folder not found")
    shelf = {r["name"]: r["content"] for r in con.execute("SELECT name, content FROM templates WHERE owner=?", (user,))}
    required: dict[str, str] = {}
    for d in docs:
        local = {e.path: store.get(d["id"], e.path).decode("utf-8", errors="replace")
                 for e in store.list(d["id"]) if resources.kind_of(e.path)}
        text = sync.room_text(d["id"])
        d["content"] = text if text is not None else d["content"]
        required.update({n: c for n, c in resources.reachable_closure(shelf, local, d["content"]).items() if n not in local})
    token = hashlib.sha256(json.dumps([docs, required], sort_keys=True).encode()).hexdigest()
    return {"documents": docs, "resources": required, "preview": token,
            "warning": "Only statically detectable references are included. Check dynamic file paths manually."}


@router.get("/api/projects")
def list_projects(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "sidebar")
    con = db.connect()
    try:
        ids = con.execute("SELECT DISTINCT p.id FROM projects p LEFT JOIN project_members m ON m.project_id=p.id AND m.username=? LEFT JOIN docs d ON d.project_id=p.id LEFT JOIN shares s ON s.doc_id=d.id AND s.username=? WHERE p.archived=0 AND (p.owner=? OR m.username IS NOT NULL OR (s.username IS NOT NULL AND d.trashed=0)) ORDER BY p.title", (user, user, user)).fetchall()
        return {"projects": [projects.payload(con, r[0], user) for r in ids]}
    finally:
        con.close()


@router.post("/api/projects/preview")
def conversion_preview(b: Convert, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        return preview(con, user, b.folder)
    finally:
        con.close()


@router.post("/api/projects/convert")
def convert_folder(b: Convert, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "create")
    pid = db.new_id("p_")
    with db.tx() as con:
        p = preview(con, user, b.folder)
        if p.get("id"):
            return {"id": p["id"]}
        if b.preview != p["preview"]:
            raise HTTPException(409, "Folder changed; review the conversion preview again")
        quota.check_quota(user, sum(len(c.encode("utf-8")) for c in p["resources"].values()), con)
        if con.execute("SELECT 1 FROM projects WHERE owner=? AND title=? COLLATE NOCASE", (user, b.folder)).fetchone():
            raise HTTPException(409, "Project name already exists")
        now = db.now_iso()
        con.execute("INSERT INTO projects(id,owner,title,created_at) VALUES (?,?,?,?)", (pid, user, b.folder, now))
        con.execute("INSERT INTO legacy_project_folders VALUES (?,?,?)", (user, b.folder.split("/")[0], pid))
        for d in p["documents"]:
            sub = d["folder"][len(b.folder):].lstrip("/")
            con.execute("UPDATE docs SET project_id=?, folder=? WHERE id=?", (pid, sub, d["id"]))
        for name, content in p["resources"].items():
            con.execute("INSERT INTO project_resources VALUES (?,?,?,?)", (pid, name, content, now))
        for f in con.execute("SELECT name FROM folders WHERE owner=? AND kind='doc'", (user,)).fetchall():
            if f[0] == b.folder or f[0].startswith(b.folder + "/"):
                con.execute("DELETE FROM folders WHERE owner=? AND kind='doc' AND name=?", (user, f[0]))
    quota.invalidate_quota_cache(user)
    projects.notify(pid)
    return {"id": pid}


@router.get("/api/projects/{project_id}")
def get_project(project_id: str, user: str = Depends(deps.me)) -> dict:
    con = db.connect()
    try:
        p = projects.payload(con, project_id, user)
        p["members"] = ([dict(x) for x in con.execute("SELECT username,role FROM project_members WHERE project_id=?", (project_id,))] if p["role"] != "guest" else [])
        return p
    finally:
        con.close()


@router.post("/api/projects/{project_id}/members")
async def set_member(project_id: str, b: Share, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "share")
    if b.role not in ("editor", "reviewer"):
        raise HTTPException(400, "Role must be editor or reviewer")
    with db.tx() as con:
        projects.require(con, project_id, user, owner=True)
        if b.username == user or not con.execute("SELECT 1 FROM users WHERE name=?", (b.username,)).fetchone():
            raise HTTPException(400, "Invalid member")
        con.execute("INSERT INTO project_members VALUES (?,?,?) ON CONFLICT(project_id,username) DO UPDATE SET role=excluded.role",
                    (project_id, b.username, b.role))
        ids = [r[0] for r in con.execute("SELECT id FROM docs WHERE project_id=?", (project_id,))]
    sync.drop_role_cache(b.username)
    for did in ids:
        await sync.kick_user(did, b.username)
    projects.notify(project_id)
    return {"ok": True}


@router.delete("/api/projects/{project_id}/members/{username}")
async def remove_member(project_id: str, username: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "share")
    with db.tx() as con:
        projects.require(con, project_id, user, owner=True)
        removed = con.execute("DELETE FROM project_members WHERE project_id=? AND username=?", (project_id, username))
        if not removed.rowcount:
            raise HTTPException(404, "Not a project member")
        ids = [r[0] for r in con.execute("SELECT id FROM docs WHERE project_id=?", (project_id,))]
        # Removing a member revokes their access throughout this project.
        for did in ids:
            con.execute("DELETE FROM shares WHERE doc_id=? AND username=?", (did, username))
            con.execute("DELETE FROM invites WHERE doc_id=?", (did,))
    sync.drop_role_cache(username)
    for did in ids:
        await sync.kick_user(did, username)
    notify_sidebar(username)
    projects.notify(project_id)
    return {"ok": True}


@router.get("/api/projects/{project_id}/resources")
def list_resources(project_id: str, user: str = Depends(deps.me)) -> dict:
    con = db.connect()
    try:
        p = projects.payload(con, project_id, user)
        allowed = {r["name"] for r in p["resources"]}
        return {"resources": [dict(x) for x in con.execute("SELECT name,content,updated_at FROM project_resources WHERE project_id=? ORDER BY name", (project_id,)) if x["name"] in allowed], "readonly": not p["can_edit_library"]}
    finally:
        con.close()


@router.post("/api/projects/{project_id}/resources")
def save_resource(project_id: str, b: ResourceSave, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    name = resource_name(b.name)
    size = len(b.content.encode("utf-8"))
    if size > MAX_TXT:
        raise HTTPException(413, "Text resource exceeds 200 KB")
    with db.tx() as con:
        projects.require(con, project_id, user, edit=True)
        owner = con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()[0]
        old = con.execute("SELECT content, updated_at FROM project_resources WHERE project_id=? AND name=?", (project_id, name)).fetchone()
        if old and (b.version is None or b.version != old["updated_at"]):
            raise HTTPException(409, "Name exists or resource changed; reload or choose another name")
        if not old and b.version is not None:
            raise HTTPException(409, "Resource removed; keep your draft")
        quota.check_quota(owner, size - (len(old["content"].encode("utf-8")) if old else 0), con)
        now = db.now_iso()
        con.execute("INSERT INTO project_resources VALUES (?,?,?,?) ON CONFLICT(project_id,name) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at", (project_id, name, b.content, now))
    quota.invalidate_quota_cache(owner)
    projects.notify(project_id)
    return {"name": name, "version": now}


@router.delete("/api/projects/{project_id}/resources/{name:path}")
def delete_resource(project_id: str, name: str, version: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "delete")
    name = resource_name(name)
    with db.tx() as con:
        projects.require(con, project_id, user, edit=True)
        row = con.execute("SELECT updated_at FROM project_resources WHERE project_id=? AND name=?", (project_id, name)).fetchone()
        if not row:
            raise HTTPException(404, "Resource not found")
        if not version or row["updated_at"] != version:
            raise HTTPException(409, "Resource changed; reload before deleting")
        owner = con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()[0]
        con.execute("DELETE FROM project_resources WHERE project_id=? AND name=?", (project_id, name))
    quota.invalidate_quota_cache(owner)
    projects.notify(project_id)
    return {"ok": True}


@router.post("/api/projects/{project_id}/docs")
def create_document(project_id: str, b: ProjectDoc, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "create")
    folder = safe_name(b.folder + "/placeholder.typ").rsplit("/", 1)[0] if b.folder else ""
    if not b.title.strip() or len(b.content.encode("utf-8")) > MAX_TXT:
        raise HTTPException(400, "Invalid title or content too large")
    with db.tx() as con:
        projects.require(con, project_id, user, edit=True)
        owner = con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()[0]
        quota.check_quota(owner, len(b.content.encode("utf-8")), con)
        if con.execute("SELECT COUNT(*) FROM docs WHERE owner=?", (owner,)).fetchone()[0] >= config.load().MAX_DOCS_PER_USER:
            raise HTTPException(400, "Too many docs")
        if con.execute("SELECT 1 FROM docs WHERE project_id=? AND title=? COLLATE NOCASE AND trashed=0", (project_id, b.title.strip())).fetchone():
            raise HTTPException(409, "Document title already exists")
        did, now = db.new_id("d_"), db.now_iso()
        try:
            con.execute("INSERT INTO docs(id,owner,title,content,folder,project_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                        (did, owner, b.title.strip(), b.content, folder, project_id, now, now))
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, "Document title already exists") from e
        projects.attach_doc(con, did, project_id)
    quota.invalidate_quota_cache(owner)
    projects.notify(project_id)
    return {"id": did}


@router.delete("/api/projects/{project_id}")
async def trash_project_documents(project_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "delete")
    with db.tx() as con:
        projects.require(con, project_id, user, owner=True)
        ids = [r[0] for r in con.execute("SELECT id FROM docs WHERE project_id=? AND trashed=0", (project_id,))]
        con.execute("UPDATE docs SET trashed=1,updated_at=? WHERE project_id=?", (db.now_iso(), project_id))
        con.execute("UPDATE projects SET archived=1 WHERE id=?", (project_id,))
        # Keep the library and membership while trashed documents can be restored.
        if not con.execute("SELECT 1 FROM docs WHERE project_id=?", (project_id,)).fetchone():
            con.execute("DELETE FROM projects WHERE id=?", (project_id,))
    for did in ids:
        await sync.drop(did)
    projects.notify(project_id)
    notify_sidebar(user)
    return {"ok": True, "trashed": len(ids)}


class ProjectTitle(BaseModel):
    title: str = Field(min_length=1, max_length=100)


@router.post("/api/projects")
def create_project(b: ProjectTitle, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "create")
    if not b.title.strip():
        raise HTTPException(400, "Title is required")
    with db.tx() as con:
        pid = projects.create(con, user, b.title.strip())
    projects.notify(pid)
    return {"id": pid}


@router.post("/api/projects/{project_id}/rename")
def rename_project(project_id: str, b: ProjectTitle, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "move")
    if not b.title.strip():
        raise HTTPException(400, "Title is required")
    with db.tx() as con:
        projects.require(con, project_id, user, owner=True)
        if con.execute("SELECT 1 FROM projects WHERE owner=? AND title=? COLLATE NOCASE AND id<>?", (user, b.title.strip(), project_id)).fetchone():
            raise HTTPException(409, "Project title already exists")
        con.execute("UPDATE projects SET title=? WHERE id=?", (b.title.strip(), project_id))
    projects.notify(project_id)
    return {"ok": True}


class EntryRename(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    target: str = Field(min_length=1, max_length=240)
    doc_id: str = ""
    version: str = ""


@router.post("/api/projects/{project_id}/rename-entry-preview")
def rename_entry_preview(project_id: str, b: EntryRename, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    name, target = safe_name(b.name), safe_name(b.target)
    con = db.connect()
    try:
        projects.require(con, project_id, user, edit=True)
        docs = con.execute("SELECT id,title,content FROM docs WHERE project_id=? AND trashed=0", (project_id,)).fetchall()
        if b.doc_id:
            if b.doc_id not in {d['id'] for d in docs}:
                raise HTTPException(404, "Document not found")
            try:
                version = hashlib.sha256(store.get(b.doc_id, name)).hexdigest()
            except FileNotFoundError:
                raise HTTPException(404, "File not found") from None
        else:
            target = resource_name(target)
            row = con.execute("SELECT updated_at FROM project_resources WHERE project_id=? AND name=?", (project_id, name)).fetchone()
            if not row:
                raise HTTPException(404, "Resource not found")
            version = row[0]
        references = []
        library = {r[0]: r[1] for r in con.execute("SELECT name,content FROM project_resources WHERE project_id=?", (project_id,))}
        for d in docs:
            if b.doc_id and d['id'] != b.doc_id:
                continue
            local = projects.local_texts(d['id'])
            local_names = {f.path for f in store.list(d['id'])}
            live = sync.room_text(d['id'])
            for path, content in {**library, **local, 'main.typ': live if live is not None else d['content']}.items():
                if not path.lower().endswith('.typ'):
                    continue
                for match in resources.REF_RE.finditer(content):
                    ref = match.group(1).replace('\\', '/')
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), ref)) if not ref.startswith('/') else ref.lstrip('/')
                    if resolved == name and (b.doc_id or name not in local_names):
                        references.append(f"{d['title']}/{path}: {ref}")
        return {"name": target, "version": version, "references": sorted(set(references))}
    except OSError as e:
        raise HTTPException(409, "Files changed or could not be read; retry rename preview") from e
    finally:
        con.close()


@router.post("/api/projects/{project_id}/rename-entry")
def rename_entry(project_id: str, b: EntryRename, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services.docfiles import file_type
    from backend.services.locks import _named_lock

    deps.limited(req, "rename")
    old, target = safe_name(b.name), safe_name(b.target)
    with _named_lock(f"upload:{b.doc_id}"):
        renamed = False
        try:
            with db.tx() as con:
                projects.require(con, project_id, user, edit=True)
                if not b.doc_id:
                    target = resource_name(target)
                    if con.execute("SELECT 1 FROM project_resources WHERE project_id=? AND name=?", (project_id, target)).fetchone():
                        raise HTTPException(409, "Name already exists")
                    row = con.execute("SELECT updated_at FROM project_resources WHERE project_id=? AND name=?", (project_id, old)).fetchone()
                    if not row:
                        raise HTTPException(404, "Resource not found")
                    if b.version != row[0]:
                        raise HTTPException(409, "Resource changed; review rename again")
                    version = db.now_iso()
                    con.execute("UPDATE project_resources SET name=?,updated_at=? WHERE project_id=? AND name=?", (target, version, project_id, old))
                else:
                    if not con.execute("SELECT 1 FROM docs WHERE id=? AND project_id=? AND trashed=0", (b.doc_id, project_id)).fetchone():
                        raise HTTPException(404, "Document not found")
                    source, destination = store.doc_path(b.doc_id, old), store.doc_path(b.doc_id, target)
                    if destination.exists():
                        raise HTTPException(409, "Name already exists")
                    if not source.is_file():
                        raise HTTPException(404, "File not found")
                    if b.version != hashlib.sha256(store.get(b.doc_id, old)).hexdigest():
                        raise HTTPException(409, "File changed; review rename again")
                    version = b.version
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source.rename(destination)
                    renamed = True
                    try:
                        stat = destination.stat()
                        con.execute("DELETE FROM files WHERE doc_id=? AND path=?", (b.doc_id, old))
                        con.execute("INSERT INTO files(doc_id,path,size,mtime,type) VALUES (?,?,?,?,?)", (b.doc_id, target, stat.st_size, stat.st_mtime, file_type(target)))
                    except Exception:
                        destination.rename(source)
                        raise
        except Exception as e:
            if renamed and destination.exists() and not source.exists():
                destination.rename(source)
            if isinstance(e, OSError):
                raise HTTPException(409, "File changed or could not be renamed; retry rename preview") from e
            raise
    projects.notify(project_id)
    return {"name": target, "version": version}


class TransferEntry(BaseModel):
    target_project_id: str
    kind: Literal['document', 'resource', 'file']
    doc_id: str = ''
    name: str = ''
    target_doc_id: str = ''
    target_name: str = Field(default='', max_length=240)
    move: bool = False
    duplicate: bool = False


@router.post('/api/projects/{project_id}/transfer')
async def transfer_entry(project_id: str, b: TransferEntry, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services.project_transfer import transfer
    from backend.services.sidebar import doc_users

    deps.limited(req, 'move')
    if b.duplicate and (b.move or b.target_project_id != project_id):
        raise HTTPException(400, 'Duplicate stays in the source project')
    audience = doc_users(b.doc_id) if b.kind == 'document' else []
    result = await asyncio.to_thread(transfer, project_id, b.target_project_id, b.kind, b.doc_id, b.name, b.target_doc_id, b.target_name, b.move, user, b.duplicate)
    if b.move and b.kind == 'document':
        for username in audience:
            sync.drop_role_cache(username)
            if not db.doc_role(username, b.doc_id):
                await sync.kick_user(b.doc_id, username)
            notify_sidebar(username)
    return result


@router.post('/api/projects/{project_id}/import-zip')
def import_project_source(project_id: str, f: UploadFile, req: Request, title: str = Form(...), user: str = Depends(deps.me)) -> dict:
    from backend.constants import UPLOAD_MAX
    from backend.services.projectzip import import_project_zip

    deps.limited(req, 'create')
    data = f.file.read(UPLOAD_MAX + 1)
    return import_project_zip(user, title, '', data, project_id)


@router.get('/api/projects/{project_id}/export-zip')
def export_project_zip(project_id: str, req: Request, user: str = Depends(deps.me)):
    import io
    import zipfile

    from fastapi.responses import Response

    from backend import mcp_tools
    from backend.constants import EXPORT_MAX

    deps.limited(req, 'export_doc', user)
    con = db.connect()
    try:
        project = projects.payload(con, project_id, user)
        allowed = {r['name'] for r in project['resources']}
        library = {r['name']: r['content'] for r in con.execute('SELECT name,content FROM project_resources WHERE project_id=?', (project_id,)) if r['name'] in allowed}
    finally:
        con.close()
    output = io.BytesIO()
    total = 0
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        def write(name: str, content: bytes) -> None:
            nonlocal total
            total += len(content)
            if total > EXPORT_MAX:
                raise HTTPException(413, 'Project export too large (max 100 MB)')
            archive.writestr(name, content)

        write('project.json', json.dumps({'title': project['title'], 'documents': [{k: d[k] for k in ('id', 'title', 'folder')} for d in project['documents']]}, ensure_ascii=False, indent=2).encode())
        for name, content in library.items():
            write('modules/' + name, content.encode())
        for doc in project['documents']:
            deps.need_access(user, doc['id'])
            main, files, skipped = mcp_tools._collect_export_source(doc['id'])
            prefix = 'documents/' + doc['id'] + '/'
            write(prefix + 'main.typ', main.encode())
            for name, content in files:
                write(prefix + name, content)
            if skipped:
                write(prefix + 'skipped.json', json.dumps(skipped).encode())
    return Response(output.getvalue(), media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="project-{project_id}.zip"', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
