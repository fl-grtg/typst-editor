"""Project regression cases that gate the first project release candidate."""
import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import login, make_doc, register_user
from fastapi import HTTPException

from backend import db, mcp_tools, ratelimit, sync
from backend.services import project_history, quota


def project(c):
    register_user(c, "alice")
    did = make_doc(c, "First", '#include "layout.typ"')
    return c.get(f"/api/docs/{did}").json()["project_id"], did


def test_concurrent_document_names_are_project_scoped(c):
    pid, _ = project(c)
    other = c.post('/api/projects', json={'title': 'Other'}).json()['id']
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda p: c.post(f'/api/projects/{p}/docs', json={'title': 'Same'}).status_code, [pid, pid]))
    assert sorted(results) == [200, 409]
    assert c.post(f'/api/projects/{other}/docs', json={'title': 'Same'}).status_code == 200
    with db.tx() as con:
        assert not con.execute('SELECT 1 FROM docs WHERE project_id IS NULL').fetchone()


def test_document_guest_cannot_list_project_roster(c):
    pid, did = project(c)
    register_user(c, 'member')
    register_user(c, 'guest')
    login(c, 'alice')
    c.post(f'/api/projects/{pid}/members', json={'username': 'member', 'role': 'editor'})
    c.post(f'/api/docs/{did}/share', json={'username': 'guest', 'role': 'reviewer'})
    login(c, 'guest')
    assert c.get(f'/api/docs/{did}/members').json()['members'] == ['alice', 'guest']
    login(c, 'member')
    assert 'member' in c.get(f'/api/docs/{did}/members').json()['members']


@pytest.mark.parametrize('action,bucket', [('create', 'create'), ('save', 'templates'), ('delete', 'delete')])
def test_project_writes_enforce_rate_limits(c, monkeypatch, action, bucket):
    pid, _ = project(c)
    c.post(f'/api/projects/{pid}/resources', json={'name': 'a.typ', 'content': 'a'})
    real = ratelimit.allow
    monkeypatch.setattr(ratelimit, 'allow', lambda key, *args, **kwargs: False if key.startswith(bucket + ':') else real(key, *args, **kwargs))
    if action == 'create':
        response = c.post(f'/api/projects/{pid}/docs', json={'title': 'Limited'})
    elif action == 'save':
        response = c.post(f'/api/projects/{pid}/resources', json={'name': 'b.typ', 'content': 'b'})
    else:
        response = c.delete(f'/api/projects/{pid}/resources/a.typ?version=stale')
    assert response.status_code == 429, response.text


def test_rename_preview_and_stale_version(c):
    pid, did = project(c)
    c.post(f'/api/projects/{pid}/resources', json={'name': 'layout.typ', 'content': 'before'})
    url = f'/api/projects/{pid}/rename-entry'
    body = {'name': 'layout.typ', 'target': 'renamed.typ'}
    preview = c.post(url + '-preview', json=body).json()
    assert preview['references'] == ['First/main.typ: layout.typ']
    c.post(f'/api/projects/{pid}/resources', json={'name': 'layout.typ', 'content': 'new', 'version': preview['version']})
    assert c.post(url, json={**body, 'version': preview['version']}).status_code == 409
    preview = c.post(url + '-preview', json=body).json()
    assert c.post(url, json={**body, 'version': preview['version']}).status_code == 200
    c.post(f'/api/docs/{did}/files', files={'f': ('a.png', b'picture', 'image/png')})
    body = {'name': 'a.png', 'target': 'b.png', 'doc_id': did}
    preview = c.post(url + '-preview', json=body).json()
    assert preview['version'] == hashlib.sha256(b'picture').hexdigest()
    assert c.post(url, json={**body, 'version': preview['version']}).status_code == 200


def test_checkpoint_capture_does_not_reserve_sqlite_writer(c, monkeypatch):
    pid, _ = project(c)
    capture = project_history.capture

    def checked(con, project_id):
        with db.tx() as writer:
            writer.execute("UPDATE users SET avatar=avatar WHERE name='alice'")
        return capture(con, project_id)

    monkeypatch.setattr(project_history, 'capture', checked)
    response = c.post(f'/api/projects/{pid}/snapshots', json={})
    assert response.status_code == 200, response.text
    sid = response.json()['id']
    assert c.get(f'/api/projects/{pid}/snapshots/{sid}').status_code == 200


def test_checkpoint_rejects_changes_during_capture(c, monkeypatch):
    pid, did = project(c)
    capture = project_history.capture

    def changed(con, project_id):
        state = capture(con, project_id)
        with db.tx() as writer:
            writer.execute("UPDATE docs SET content='new' WHERE id=?", (did,))
        return state

    monkeypatch.setattr(project_history, 'capture', changed)
    assert c.post(f'/api/projects/{pid}/snapshots', json={}).status_code == 409


def test_failed_restore_retains_sources_files_and_history(c, monkeypatch):
    pid, did = project(c)
    sid = c.post(f'/api/projects/{pid}/snapshots', json={}).json()['id']
    c.post(f'/api/docs/{did}/files', files={'f': ('a.png', b'keep', 'image/png')})
    before = quota.user_bytes('alice')
    history = c.get(f'/api/projects/{pid}/snapshots').json()
    monkeypatch.setattr(quota, 'quota_cap', lambda: before)
    assert c.post(f'/api/projects/{pid}/snapshots/{sid}/restore', json={}).status_code == 413
    assert c.get(f'/api/docs/{did}/files/a.png').content == b'keep'
    assert c.get(f'/api/projects/{pid}/snapshots').json() == history


def test_migration_allowance_and_case_collisions(c):
    pid, _ = project(c)
    c.post(f'/api/projects/{pid}/resources', json={'name': 'a.typ', 'content': 'copied'})
    with db.tx() as con:
        con.execute('DROP INDEX idx_projects_owner_title_nocase')
        con.execute('ALTER TABLE users DROP COLUMN migration_bytes')
        con.execute("INSERT INTO projects VALUES ('legacy','alice','first','now',0)")
        db._migrate_v19(con)
        assert con.execute("SELECT migration_bytes FROM users WHERE name='alice'").fetchone()[0] == 6
        names = [r[0] for r in con.execute("SELECT title FROM projects WHERE owner='alice'")]
        assert len({n.lower() for n in names}) == len(names)
    info = c.get('/api/me').json()['storage']
    assert info['limit'] == quota.quota_cap() + 6
    assert info['migration_allowance'] == 6


def test_mcp_shared_listing_uses_project_role_without_per_doc_queries(c, monkeypatch):
    pid, did = project(c)
    register_user(c, 'bob')
    login(c, 'alice')
    c.post(f'/api/projects/{pid}/members', json={'username': 'bob', 'role': 'reviewer'})
    monkeypatch.setattr(db, 'role_on', lambda *args: pytest.fail('per-document role query'))
    shared = mcp_tools.op_ls('bob', 'editor')['shared']
    assert [(d['id'], d['role']) for d in shared] == [(did, 'reviewer')]


def test_hard_delete_invalidates_quota_cache(c):
    _, did = project(c)
    c.delete(f'/api/docs/{did}')
    sync._quota_cache['alice'] = (True, 0)
    assert c.delete(f'/api/docs/{did}').status_code == 200
    assert 'alice' not in sync._quota_cache


def test_legacy_snapshot_delete_invalidates_quota_cache(c):
    _, did = project(c)
    sid = c.post(f'/api/docs/{did}/snapshots', json={}).json()['id']
    sync._quota_cache['alice'] = (True, 0)
    assert c.delete(f'/api/docs/{did}/snapshots/{sid}').status_code == 200
    assert 'alice' not in sync._quota_cache


def test_live_save_checks_final_quota_in_transaction(c, monkeypatch):
    _, did = project(c)
    before = c.get(f'/api/docs/{did}').json()['content']
    used = quota.user_bytes('alice')
    monkeypatch.setattr(quota, 'quota_cap', lambda: used)
    with pytest.raises(HTTPException) as error:
        db.save_room(did, b'new yjs', before + 'more')
    assert error.value.status_code == 413
    assert c.get(f'/api/docs/{did}').json()['content'] == before


def test_edit_arriving_during_flush_remains_dirty(c, monkeypatch):
    from pycrdt import Text

    _, did = project(c)
    room = sync.room(did)
    room['dirty'] = True
    save = db.save_room

    def concurrent(doc_id, yjs, text):
        save(doc_id, yjs, text)
        with sync._doc_lock(room), room['doc'].transaction():
            room['doc'].get('typst', type=Text).__iadd__('later')

    monkeypatch.setattr(db, 'save_room', concurrent)
    assert asyncio.run(sync._flush_one(did, room))
    assert room['dirty']
    assert sync.room_text(did).endswith('later')


def test_unicode_limits_measure_utf8_bytes(c):
    pid, did = project(c)
    text = '\U0001f600' * 50001
    assert c.post(f'/api/projects/{pid}/docs', json={'title': 'Large', 'content': text}).status_code == 400
    assert c.post(f'/api/docs/{did}/save', json={'content': text}).status_code == 400
    assert c.post(f'/api/projects/{pid}/resources', json={'name': 'large.typ', 'content': text}).status_code == 413


def test_legacy_duplicate_copies_dependencies_without_mutating_source(c):
    _, did = project(c)
    c.post('/api/templates', json={'name': 'layout.typ', 'content': 'keep dependency'})
    with db.tx() as con:
        con.execute('UPDATE docs SET project_id=NULL WHERE id=?', (did,))
    response = c.post(f'/api/docs/{did}/duplicate')
    assert response.status_code == 200, response.text
    with db.tx() as con:
        assert con.execute('SELECT project_id FROM docs WHERE id=?', (did,)).fetchone()[0] is None
    copied = response.json()['id']
    assert c.get(f'/api/docs/{copied}/resources').json()['resources']['layout.typ'] == 'keep dependency'


def test_project_suffix_keeps_title_length_limit(c):
    register_user(c, 'alice')
    title = 'A' * 100
    first = c.post('/api/projects', json={'title': title}).json()['id']
    second = c.post('/api/projects', json={'title': title}).json()['id']
    assert c.get(f'/api/projects/{first}').json()['title'] == title
    assert c.get(f'/api/projects/{second}').json()['title'] == 'A' * 96 + ' (2)'


@pytest.mark.parametrize('failure', ['copy', 'quota'])
def test_failed_legacy_duplicate_removes_new_project(c, monkeypatch, failure):
    _, did = project(c)
    c.post('/api/templates', json={'name': 'layout.typ', 'content': 'dependency'})
    c.post(f'/api/docs/{did}/files', files={'f': ('a.png', b'keep', 'image/png')})
    with db.tx() as con:
        con.execute('UPDATE docs SET project_id=NULL WHERE id=?', (did,))
    before = quota.user_bytes('alice')
    projects = {p['id'] for p in c.get('/api/projects').json()['projects']}
    if failure == 'copy':
        def broken(*args, **kwargs):
            raise OSError('copy failed')
        monkeypatch.setattr('shutil.copytree', broken)
    else:
        monkeypatch.setattr(quota, 'is_over_quota', lambda user: True)
    result = c.post(f'/api/docs/{did}/duplicate')
    assert result.status_code == (500 if failure == 'copy' else 413), result.text
    assert quota.user_bytes('alice') == before
    assert {p['id'] for p in c.get('/api/projects').json()['projects']} == projects


def test_rename_preview_file_race_returns_conflict(c, monkeypatch):
    from backend.services import projects

    pid, did = project(c)
    c.post(f'/api/projects/{pid}/resources', json={'name': 'layout.typ', 'content': 'a'})

    def disappeared(*args):
        raise FileNotFoundError('concurrent delete')

    monkeypatch.setattr(projects, 'local_texts', disappeared)
    result = c.post(f'/api/projects/{pid}/rename-entry-preview', json={'name': 'layout.typ', 'target': 'new.typ'})
    assert result.status_code == 409
