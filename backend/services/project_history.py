"""Project checkpoints include document sources, shared modules and binary files."""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from fastapi import HTTPException

from backend import db, sync
from backend.constants import SNAP_MAX
from backend.services import quota
from backend.services.docfiles import store
from backend.services.locks import _named_lock


def stamp(con: sqlite3.Connection, project_id: str) -> tuple:
    docs = tuple(tuple(r) for r in con.execute("SELECT id,owner,title,folder,content,yjs,trashed,updated_at FROM docs WHERE project_id=? ORDER BY id", (project_id,)))
    modules = tuple(tuple(r) for r in con.execute("SELECT name,content,updated_at FROM project_resources WHERE project_id=? ORDER BY name", (project_id,)))
    return docs, modules


def unchanged(con: sqlite3.Connection, project_id: str, expected: tuple) -> None:
    if stamp(con, project_id) != expected:
        raise HTTPException(409, "Project changed; retry checkpoint operation")


@contextmanager
def prepared(project_id: str, user: str) -> Iterator[tuple[dict, tuple]]:
    from backend.services import projects

    con = db.connect()
    try:
        projects.require(con, project_id, user)
        ids = [r[0] for r in con.execute("SELECT id FROM docs WHERE project_id=? ORDER BY id", (project_id,))]
    finally:
        con.close()
    with ExitStack() as locks:
        for did in ids:
            locks.enter_context(_named_lock(f"upload:{did}"))
        con = db.connect()
        try:
            con.execute("BEGIN")
            projects.require(con, project_id, user)
            expected = stamp(con, project_id)
            if [r[0] for r in expected[0]] != ids:
                raise HTTPException(409, "Project changed; retry checkpoint operation")
            state = capture(con, project_id)
        finally:
            con.close()
        yield state, expected


def capture(con: sqlite3.Connection, project_id: str) -> dict:
    documents = []
    for row in con.execute("SELECT id,title,folder,content,created_at FROM docs WHERE project_id=? AND trashed=0 ORDER BY id", (project_id,)):
        doc = dict(row)
        live = sync.room_text(doc['id'])
        if live is not None:
            doc['content'] = live
        doc['files'] = {f.path: base64.b64encode(store.get(doc['id'], f.path)).decode('ascii') for f in store.list(doc['id'])}
        documents.append(doc)
    resources = {r['name']: r['content'] for r in con.execute("SELECT name,content FROM project_resources WHERE project_id=? ORDER BY name", (project_id,))}
    return {'documents': documents, 'resources': resources}


def save(con: sqlite3.Connection, project_id: str, state: dict, label: str = '') -> str:
    content = json.dumps(state, ensure_ascii=False, sort_keys=True)
    owner = con.execute('SELECT owner FROM projects WHERE id=?', (project_id,)).fetchone()[0]
    sid = db.new_id('ps_')
    con.execute('INSERT INTO project_snapshots VALUES (?,?,?,?,?)', (sid, project_id, content, label, db.now_iso()))
    con.execute('DELETE FROM project_snapshots WHERE project_id=? AND id NOT IN (SELECT id FROM project_snapshots WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?)', (project_id, project_id, SNAP_MAX))
    quota.check_quota(owner, 0, con)
    return sid


def diff_files(state: dict) -> dict[str, str]:
    files = {}
    for d in state['documents']:
        prefix = f"{d['title']} [{d['id']}]"
        files[prefix + '/main.typ'] = d['content']
        for name, encoded in d['files'].items():
            data = base64.b64decode(encoded)
            try:
                value = data.decode('utf-8')
            except UnicodeDecodeError:
                value = f"Binary: {len(data)} bytes, SHA256 {hashlib.sha256(data).hexdigest()}"
            files[prefix + '/' + name] = value
    for name, content in state['resources'].items():
        files['Modules/' + name] = content
    return files


def diff_text(state: dict) -> str:
    return '\n\n'.join(f'=== {name} ===\n{content}' for name, content in sorted(diff_files(state).items()))


def auto(project_id: str) -> None:
    import logging
    from datetime import UTC, datetime, timedelta

    from backend.constants import SNAP_EVERY

    try:
        con = db.connect()
        try:
            p = con.execute('SELECT owner,archived FROM projects WHERE id=?', (project_id,)).fetchone()
            if not p or p['archived']:
                return
            last = con.execute('SELECT created_at FROM project_snapshots WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (project_id,)).fetchone()
            if last and last[0] >= (datetime.now(UTC) - timedelta(seconds=SNAP_EVERY)).isoformat():
                return
        finally:
            con.close()
        with prepared(project_id, p['owner']) as (state, expected), db.tx() as con:
            from backend.services import projects

            projects.require(con, project_id, p['owner'], edit=True)
            last = con.execute('SELECT created_at FROM project_snapshots WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (project_id,)).fetchone()
            if last and last[0] >= (datetime.now(UTC) - timedelta(seconds=SNAP_EVERY)).isoformat():
                return
            unchanged(con, project_id, expected)
            save(con, project_id, state)
        quota.invalidate_quota_cache(p['owner'])
    except (HTTPException, sqlite3.Error, OSError) as e:
        logging.getLogger('typst.main').warning('Project auto checkpoint skipped: %s', e)


def auto_document(doc_id: str) -> None:
    con = db.connect()
    try:
        row = con.execute('SELECT project_id FROM docs WHERE id=?', (doc_id,)).fetchone()
    finally:
        con.close()
    if row and row[0]:
        auto(row[0])
