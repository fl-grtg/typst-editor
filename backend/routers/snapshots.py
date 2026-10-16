"""Version snapshot routes."""
from __future__ import annotations

import asyncio
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from backend import config, db, deps, sync
from backend.schemas import SnapNew, SnapRestore
from backend.services import quota
from backend.services.snapshots import prune_snaps

router = APIRouter()


@router.get("/api/docs/{doc_id}/snapshots")
def list_snaps(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    con = db.connect()
    try:
        rows = con.execute("SELECT id, label, created_at, LENGTH(content) AS size FROM snapshots "
                           "WHERE doc_id=? ORDER BY created_at DESC, rowid DESC", (doc_id,)).fetchall()
        return {"snapshots": [dict(r) for r in rows]}
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/snapshots")
def make_snap(doc_id: str, b: SnapNew, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "snapshots")
    deps.need_edit(user, doc_id)
    live = sync.room_text(doc_id)
    with db.tx() as con:
        if deps._tx_role(con, user, doc_id) not in ("owner", "editor"):
            raise HTTPException(403, "Reviewer can only comment")
        row = con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Doc gone")
        cur = live if live is not None else row["content"]
        owner = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()[0]
        sid = db.new_id("s_")
        con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                    (sid, doc_id, cur, b.label.strip()[:80], db.now_iso()))
        prune_snaps(con, doc_id)
        quota.check_quota(owner, 0, con)
    quota.invalidate_quota_cache(owner)
    return {"id": sid}


@router.get("/api/docs/{doc_id}/snapshots/{sid}")
def get_snap(doc_id: str, sid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    con = db.connect()
    try:
        r = con.execute("SELECT content, label, created_at FROM snapshots WHERE id=? AND doc_id=?",
                        (sid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Snapshot gone")
        return dict(r)
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/snapshots/{sid}/restore")
async def restore_snap(doc_id: str, sid: str, req: Request, user: str = Depends(deps.me),
                       force: bool = False, b: SnapRestore | None = None) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "snapshots")
    deps.need_edit(user, doc_id)
    eff = force or (b.force if b else False)  # query or body flag, default safe
    auto = sync.room_text(doc_id)
    try:
        with db.tx() as con:
            # B5: outer need_edit is a fast-path only; re-check on the tx
            # connection before restoring (role may change in the gap).
            if deps._tx_role(con, user, doc_id) not in ("owner", "editor"):
                raise HTTPException(403, "Reviewer can only comment")
            s = con.execute("SELECT content FROM snapshots WHERE id=? AND doc_id=?", (sid, doc_id)).fetchone()
            if not s:
                raise HTTPException(404, "Snapshot gone")
            cur = con.execute("SELECT content, trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
            if not cur:
                raise HTTPException(404, "Doc gone")
            if cur["trashed"]:
                raise HTTPException(410, "In trash - restore first")
            if auto is not None and auto != (cur["content"] or "") and not eff:
                raise HTTPException(409, "Document changed meanwhile, retry with force")
            before = auto if auto is not None else cur["content"]
            owner = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()[0]
            con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                        (db.new_id("s_"), doc_id, before, "Before restore", db.now_iso()))
            prune_snaps(con, doc_id)
            quota.check_quota(owner, max(0, len((s["content"] or "").encode("utf-8")) - len((cur["content"] or "").encode("utf-8"))), con)
            con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?", (s["content"], db.now_iso(), doc_id))
    except sqlite3.OperationalError as e:
        raise deps.busy_503("restore_snap", e) from e
    await sync.replace_text(doc_id, s["content"])
    quota.invalidate_quota_cache(owner)
    return {"ok": True}


@router.delete("/api/docs/{doc_id}/snapshots/{sid}")
def delete_snap(doc_id: str, sid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "snapshots")
    with db.tx() as con:
        if deps._tx_role(con, user, doc_id) != "owner":
            raise HTTPException(403, "Only owner can delete snapshots")
        con.execute("DELETE FROM snapshots WHERE id=? AND doc_id=?", (sid, doc_id))
    quota.invalidate_quota_cache(user)
    return {"ok": True}


@router.get("/api/projects/{project_id}/snapshots")
def list_project_snaps(project_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services import projects
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        projects.require(con, project_id, user)
        return {"snapshots": [dict(r) for r in con.execute("SELECT id,label,created_at,LENGTH(CAST(content AS BLOB)) AS size FROM project_snapshots WHERE project_id=? ORDER BY created_at DESC,rowid DESC", (project_id,))]}
    finally:
        con.close()


@router.post("/api/projects/{project_id}/snapshots")
def make_project_snap(project_id: str, b: SnapNew, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services import project_history, projects, quota
    deps.limited(req, "snapshots")
    with project_history.prepared(project_id, user) as (state, expected), db.tx() as con:
        projects.require(con, project_id, user, edit=True)
        project_history.unchanged(con, project_id, expected)
        sid = project_history.save(con, project_id, state, b.label.strip())
        owner = con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()[0]
    quota.invalidate_quota_cache(owner)
    return {"id": sid}


@router.get("/api/projects/{project_id}/snapshots/{sid}")
def get_project_snap(project_id: str, sid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    import json

    from backend.services import project_history, projects
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        projects.require(con, project_id, user)
        row = con.execute("SELECT content,label,created_at FROM project_snapshots WHERE id=? AND project_id=?", (sid, project_id)).fetchone()
        if not row:
            raise HTTPException(404, "Checkpoint not found")
        saved = json.loads(row["content"])
        with project_history.prepared(project_id, user) as (current, _):
            pass
        old_files, new_files = project_history.diff_files(saved), project_history.diff_files(current)
        changes = [{"name": name, "before": old_files.get(name, ""), "after": new_files.get(name, ""),
                    "status": "added" if name not in old_files else "deleted" if name not in new_files else "modified"}
                   for name in sorted(old_files.keys() | new_files.keys()) if old_files.get(name) != new_files.get(name)]
        return {**dict(row), "content": project_history.diff_text(saved), "current_content": project_history.diff_text(current), "changes": changes}
    finally:
        con.close()


@router.delete("/api/projects/{project_id}/snapshots/{sid}")
def delete_project_snap(project_id: str, sid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services import projects, quota
    deps.limited(req, "snapshots")
    with db.tx() as con:
        projects.require(con, project_id, user, owner=True)
        owner = con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()[0]
        con.execute("DELETE FROM project_snapshots WHERE project_id=? AND id=?", (project_id, sid))
    quota.invalidate_quota_cache(owner)
    return {"ok": True}


def _restore_project_state(project_id: str, sid: str, b: SnapRestore, user: str) -> tuple[dict, list[str], str]:
    import base64
    import json
    from contextlib import ExitStack

    from backend.services import project_history, projects, quota
    from backend.services.docfiles import file_type, store
    from backend.services.locks import _named_lock

    before = None
    file_backup: dict[str, dict[str, bytes]] = {}
    con = db.connect()
    try:
        projects.require(con, project_id, user, edit=True)
        row = con.execute('SELECT content FROM project_snapshots WHERE id=? AND project_id=?', (sid, project_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Checkpoint not found')
        expected = json.loads(row['content'])
        touched = sorted({r[0] for r in con.execute('SELECT id FROM docs WHERE project_id=?', (project_id,))} | {d['id'] for d in expected['documents']})
    finally:
        con.close()
    with ExitStack() as locks:
        for did in touched:
            locks.enter_context(_named_lock(f'upload:{did}'))
        con = db.connect()
        try:
            con.execute('BEGIN')
            projects.require(con, project_id, user, edit=True)
            expected_stamp = project_history.stamp(con, project_id)
            file_backup = {did: {f.path: store.get(did, f.path) for f in store.list(did)} for did in touched}
            before = project_history.capture(con, project_id)
        finally:
            con.close()
        try:
            with db.tx() as con:
                projects.require(con, project_id, user, edit=True)
                project_history.unchanged(con, project_id, expected_stamp)
                row = con.execute("SELECT content FROM project_snapshots WHERE id=? AND project_id=?", (sid, project_id)).fetchone()
                if not row:
                    raise HTTPException(404, "Checkpoint not found")
                state = json.loads(row['content'])
                owner = con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()[0]
                current = [r[0] for r in con.execute("SELECT id FROM docs WHERE project_id=?", (project_id,))]
                if not (set(current) | {d['id'] for d in state['documents']}).issubset(touched):
                    raise HTTPException(409, 'Project changed; retry restore')
                for d in state['documents']:
                    existing = con.execute('SELECT project_id FROM docs WHERE id=?', (d['id'],)).fetchone()
                    if existing and existing[0] != project_id:
                        raise HTTPException(409, 'Document belongs to another project')
                # A live collaborator must not be silently overwritten.
                for did in current:
                    live = sync.room_text(did)
                    saved = con.execute('SELECT content FROM docs WHERE id=?', (did,)).fetchone()[0]
                    if live is not None and live != saved and not b.force:
                        raise HTTPException(409, 'Project has unsaved live changes; retry with force')
                project_history.save(con, project_id, before, 'Before restore')
                extra = 0
                for d in state['documents']:
                    old = con.execute('SELECT content,yjs FROM docs WHERE id=?', (d['id'],)).fetchone()
                    extra += len(d['content'].encode()) - (len(old[0].encode()) + len(old[1] or b'') if old else 0)
                    extra += sum(len(base64.b64decode(v)) for v in d['files'].values()) - sum(len(v) for v in file_backup[d['id']].values())
                extra += sum(len(v.encode()) for v in state['resources'].values()) - sum(len(v.encode()) for v in before['resources'].values())
                quota.check_quota(owner, max(0, extra), con)
                new_docs = sum(not con.execute('SELECT 1 FROM docs WHERE id=?', (d['id'],)).fetchone() for d in state['documents'])
                if new_docs + con.execute('SELECT COUNT(*) FROM docs WHERE owner=?', (owner,)).fetchone()[0] > config.load().MAX_DOCS_PER_USER:
                    raise HTTPException(400, 'Too many docs')
                con.execute('UPDATE docs SET trashed=1 WHERE project_id=?', (project_id,))
                con.execute('DELETE FROM project_resources WHERE project_id=?', (project_id,))
                for name, content in state['resources'].items():
                    con.execute('INSERT INTO project_resources VALUES (?,?,?,?)', (project_id, name, content, db.now_iso()))
                for d in state['documents']:
                    existing = con.execute('SELECT project_id FROM docs WHERE id=?', (d['id'],)).fetchone()
                    if existing and existing[0] != project_id:
                        raise HTTPException(409, 'Document belongs to another project')
                    if not existing:
                        con.execute('INSERT INTO docs(id,owner,title,folder,content,project_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)', (d['id'], owner, d['title'], d['folder'], d['content'], project_id, d['created_at'], db.now_iso()))
                    else:
                        con.execute('UPDATE docs SET title=?,folder=?,content=?,trashed=0,yjs=NULL,updated_at=? WHERE id=?', (d['title'], d['folder'], d['content'], db.now_iso(), d['id']))
                    for f in store.list(d['id']):
                        store.delete(d['id'], f.path)
                    con.execute('DELETE FROM files WHERE doc_id=?', (d['id'],))
                    for name, encoded in d['files'].items():
                        store.put(d['id'], name, base64.b64decode(encoded))
                        stat = store.stat(d['id'], name)
                        assert stat is not None
                        con.execute('INSERT INTO files(doc_id,path,size,mtime,type) VALUES (?,?,?,?,?)', (d['id'], name, stat.size, stat.mtime, file_type(name)))
        except Exception as error:
            for did, originals in file_backup.items():
                for f in store.list(did):
                    store.delete(did, f.path)
                for name, data in originals.items():
                    store.put(did, name, data)
            if isinstance(error, sqlite3.IntegrityError):
                raise HTTPException(409, "A document name conflicts in this project; rename it before restoring") from error
            raise
    return state, current, owner


@router.post("/api/projects/{project_id}/snapshots/{sid}/restore")
async def restore_project_snap(project_id: str, sid: str, b: SnapRestore, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services import projects, quota

    deps.limited(req, "snapshots")
    state, current, owner = await asyncio.to_thread(_restore_project_state, project_id, sid, b, user)
    for d in state['documents']:
        await sync.replace_text(d['id'], d['content'])
    for did in set(current) - {d['id'] for d in state['documents']}:
        await sync.drop(did)
    quota.invalidate_quota_cache(owner)
    await asyncio.to_thread(projects.notify, project_id)
    return {"ok": True, "documents": [d['id'] for d in state['documents']]}
