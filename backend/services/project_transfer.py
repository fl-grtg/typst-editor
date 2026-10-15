"""Explicit copies and moves between project namespaces."""
from __future__ import annotations

from contextlib import ExitStack

from fastapi import HTTPException

from backend import config, db, sync
from backend.services import projects, quota, resources
from backend.services.docfiles import file_type, safe_name, store
from backend.services.locks import _named_lock


def transfer(source: str, target: str, kind: str, doc_id: str, name: str,
             target_doc: str, target_name: str, move: bool, user: str, duplicate: bool = False) -> dict:
    new_id = db.new_id('d_') if kind == 'document' and not move else doc_id
    backups: dict[tuple[str, str], bytes | None] = {}
    source_owner = target_owner = ''
    with ExitStack() as locks:
        for did in sorted({doc_id, target_doc, new_id} - {''}):
            locks.enter_context(_named_lock(f'upload:{did}'))
        try:
            with db.tx() as con:
                projects.require(con, source, user, edit=move)
                projects.require(con, target, user, edit=True)
                source_owner = con.execute('SELECT owner FROM projects WHERE id=?', (source,)).fetchone()[0]
                target_owner = con.execute('SELECT owner FROM projects WHERE id=?', (target,)).fetchone()[0]
                if move and source_owner != target_owner and user != source_owner:
                    raise HTTPException(403, 'Only the source owner can move content to another owner')
                shelf = {r[0]: r[1] for r in con.execute('SELECT name,content FROM project_resources WHERE project_id=?', (source,))}
                copies = {}
                writes: dict[tuple[str, str], bytes] = {}
                deletes: list[tuple[str, str]] = []
                now = db.now_iso()
                if kind == 'document':
                    d = con.execute('SELECT * FROM docs WHERE id=? AND project_id=? AND trashed=0', (doc_id, source)).fetchone()
                    if not d:
                        raise HTTPException(404, 'Document not found')
                    if duplicate:
                        number = 1
                        target_name = resources.copy_name(d['title'], number)
                        while con.execute('SELECT 1 FROM docs WHERE project_id=? AND title=? COLLATE NOCASE AND trashed=0', (target, target_name)).fetchone():
                            number += 1
                            target_name = resources.copy_name(d['title'], number)
                    title = target_name.strip()
                    if not title or len(title) > 100:
                        raise HTTPException(400, 'Invalid document name')
                    if con.execute('SELECT 1 FROM docs WHERE project_id=? AND title=? COLLATE NOCASE AND trashed=0 AND id<>?', (target, title, doc_id if move else '')).fetchone():
                        raise HTTPException(409, 'Name already exists in target project')
                    live = sync.room_snapshot(doc_id)
                    yjs, text = live if live is not None else (d['yjs'], d['content'])
                    local = projects.local_texts(doc_id)
                    copies = {n: c for n, c in resources.reachable_closure(shelf, local, text).items() if n not in local}
                    if not move:
                        writes = {(new_id, f.path): store.get(doc_id, f.path) for f in store.list(doc_id)}
                    extra = len(text.encode()) + sum(len(v) for v in writes.values())
                    if move:
                        extra = len(text.encode()) + len(yjs or b'') - len(d['content'].encode()) - len(d['yjs'] or b'') if source_owner == target_owner else len(text.encode()) + sum(f.size for f in store.list(doc_id)) + len(yjs or b'') + con.execute('SELECT COALESCE(SUM(LENGTH(CAST(content AS BLOB))),0) FROM snapshots WHERE doc_id=?', (doc_id,)).fetchone()[0]
                    if (not move or source_owner != target_owner) and con.execute('SELECT COUNT(*) FROM docs WHERE owner=?', (target_owner,)).fetchone()[0] >= config.load().MAX_DOCS_PER_USER:
                        raise HTTPException(400, 'Too many docs')
                elif kind == 'resource':
                    from backend.routers.projects import resource_name
                    name = resource_name(name)
                    if duplicate:
                        number = 1
                        target_name = resources.copy_name(name, number)
                        while con.execute('SELECT 1 FROM project_resources WHERE project_id=? AND name=?', (target, target_name)).fetchone():
                            number += 1
                            target_name = resources.copy_name(name, number)
                    target_name = resource_name(target_name)
                    if name not in shelf:
                        raise HTTPException(404, 'Module not found')
                    if source == target and move and name == target_name:
                        return {'name': name, 'doc_id': doc_id}
                    # Reuse dependency mapping and relative reference rewriting from library pulls.
                    from backend.routers.library_copy import Pull, inspect_pull
                    inspected = inspect_pull(con, user, Pull(source_scope='project', source_project_id=source, source=name, scope='project', project_id=target, name=target_name))
                    if target_name in inspected['collisions']:
                        raise HTTPException(409, 'Module or dependency name exists in target project')
                    copies = inspected['content']
                    extra = 0
                    if move:
                        con.execute('DELETE FROM project_resources WHERE project_id=? AND name=?', (source, name))
                else:
                    name = safe_name(name)
                    if duplicate:
                        target_doc = doc_id
                        number = 1
                        target_name = resources.copy_name(name, number)
                        while store.stat(target_doc, target_name):
                            number += 1
                            target_name = resources.copy_name(name, number)
                    target_name = safe_name(target_name)
                    if not con.execute('SELECT 1 FROM docs WHERE id=? AND project_id=? AND trashed=0', (doc_id, source)).fetchone() or not con.execute('SELECT 1 FROM docs WHERE id=? AND project_id=? AND trashed=0', (target_doc, target)).fetchone():
                        raise HTTPException(404, 'Source or target document not found')
                    if (doc_id, name) == (target_doc, target_name):
                        raise HTTPException(409, 'Choose another target name')
                    if store.stat(target_doc, target_name):
                        raise HTTPException(409, 'Name already exists in target project')
                    try:
                        data = store.get(doc_id, name)
                    except FileNotFoundError:
                        raise HTTPException(404, 'File not found') from None
                    if len(store.list(target_doc)) >= config.load().MAX_FILES_PER_DOC:
                        raise HTTPException(400, 'Too many files')
                    writes[(target_doc, target_name)] = data
                    extra = len(data) if not move or source_owner != target_owner else 0
                    if move:
                        deletes.append((doc_id, name))
                additions = {}
                for n, content in copies.items():
                    old = con.execute('SELECT content FROM project_resources WHERE project_id=? AND name=?', (target, n)).fetchone()
                    if old and old[0] != content:
                        raise HTTPException(409, f'Module name conflict: {n}')
                    if not old:
                        additions[n] = content
                quota.check_quota(target_owner, extra + sum(len(v.encode()) for v in additions.values()), con)
                for n, content in additions.items():
                    con.execute('INSERT INTO project_resources VALUES (?,?,?,?)', (target, n, content, now))
                if kind == 'document':
                    if move:
                        con.execute('UPDATE docs SET project_id=?,owner=?,title=?,folder=?,content=?,yjs=?,updated_at=? WHERE id=?', (target, target_owner, title, d['folder'], text, yjs, now, doc_id))
                        if source != target:
                            con.execute('DELETE FROM invites WHERE doc_id=?', (doc_id,))
                    else:
                        con.execute('INSERT INTO docs(id,owner,title,content,folder,project_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)', (new_id, target_owner, title, text, d['folder'], target, now, now))
                for (did, path), data in writes.items():
                    backups[(did, path)] = None
                    store.put(did, path, data)
                    f = store.stat(did, path)
                    assert f is not None
                    con.execute('INSERT INTO files(doc_id,path,size,mtime,type) VALUES (?,?,?,?,?)', (did, path, f.size, f.mtime, file_type(path)))
                for did, path in deletes:
                    backups[(did, path)] = store.get(did, path)
                    store.delete(did, path)
                    con.execute('DELETE FROM files WHERE doc_id=? AND path=?', (did, path))
        except Exception:
            for (did, path), original in backups.items():
                if original is None:
                    store.delete(did, path)
                else:
                    store.put(did, path, original)
            raise
    quota.invalidate_quota_cache(source_owner)
    quota.invalidate_quota_cache(target_owner)
    projects.notify(source)
    if target != source:
        projects.notify(target)
    return {'doc_id': new_id if kind == 'document' else target_doc, 'name': target_name}
