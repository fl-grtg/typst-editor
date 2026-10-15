"""Project-wide history and file actions."""
from conftest import login, register_user

from backend import db


def test_checkpoint_restores_documents_modules_and_binary_attachments(c):
    register_user(c, 'alice')
    did = c.post('/api/docs/create', json={'title': 'First', 'content': 'first source'}).json()['id']
    pid = c.get(f'/api/docs/{did}').json()['project_id']
    other = c.post(f'/api/projects/{pid}/docs', json={'title': 'Second', 'content': 'second source'}).json()['id']
    assert c.post(f'/api/projects/{pid}/resources', json={'name': 'data.csv', 'content': 'a,b\n1,2'}).status_code == 200
    assert c.post(f'/api/docs/{did}/files', files={'f': ('image.png', b'\x89PNG\x00\xff', 'image/png')}).status_code == 200
    snap = c.post(f'/api/projects/{pid}/snapshots', json={'label': 'Whole project'})
    assert snap.status_code == 200, snap.text
    sid = snap.json()['id']
    version = c.get(f'/api/projects/{pid}/resources').json()['resources'][0]['updated_at']
    c.post(f'/api/projects/{pid}/resources', json={'name': 'data.csv', 'content': 'changed', 'version': version})
    c.delete(f'/api/docs/{did}/files/image.png')
    c.delete(f'/api/docs/{other}')
    added = c.post(f'/api/projects/{pid}/docs', json={'title': 'Added later'}).json()['id']
    diff = c.get(f'/api/projects/{pid}/snapshots/{sid}').json()
    assert 'Second' in diff['content'] and 'image.png' in diff['content']
    assert diff['content'] != diff['current_content']
    result = c.post(f'/api/projects/{pid}/snapshots/{sid}/restore', json={})
    assert result.status_code == 200, result.text
    assert c.get(f'/api/docs/{other}').json()['content'] == 'second source'
    assert c.get(f'/api/docs/{did}/files/image.png').content == b'\x89PNG\x00\xff'
    assert c.get(f'/api/projects/{pid}/resources').json()['resources'][0]['content'] == 'a,b\n1,2'
    with db.tx() as con:
        assert con.execute('SELECT trashed FROM docs WHERE id=?', (added,)).fetchone()[0] == 1
    history = c.get(f'/api/projects/{pid}/snapshots').json()['snapshots']
    assert any(s['label'] == 'Before restore' for s in history)


def test_project_rename_entries_and_editor_delete(c):
    register_user(c, 'alice')
    did = c.post('/api/docs/create', json={'title': 'Rename'}).json()['id']
    pid = c.get(f'/api/docs/{did}').json()['project_id']
    c.post(f'/api/projects/{pid}/resources', json={'name': 'old.typ', 'content': 'original'})
    c.post(f'/api/projects/{pid}/resources', json={'name': 'occupied.typ', 'content': 'keep'})
    url = f'/api/projects/{pid}/rename-entry'
    assert c.post(url, json={'name': 'old.typ', 'target': 'occupied.typ'}).status_code == 409
    assert c.post(url, json={'name': 'old.typ', 'target': 'new.typ'}).status_code == 200
    c.post(f'/api/docs/{did}/files', files={'f': ('a.png', b'image', 'image/png')})
    assert c.post(url, json={'name': 'a.png', 'target': 'nested/b.png', 'doc_id': did}).status_code == 200
    assert c.get(f'/api/docs/{did}/files/nested/b.png').content == b'image'
    register_user(c, 'bob')
    login(c, 'alice')
    c.post(f'/api/projects/{pid}/members', json={'username': 'bob', 'role': 'editor'})
    login(c, 'bob')
    assert c.post(f'/api/docs/{did}/rename', json={'title': 'Renamed by editor'}).status_code == 200
    assert c.delete(f'/api/docs/{did}').status_code == 200
    assert c.delete(f'/api/docs/{did}').status_code == 403
    assert c.get(f'/api/projects/{pid}').json()['documents'] == []
    login(c, 'alice')
    c.post(f'/api/projects/{pid}/members', json={'username': 'bob', 'role': 'reviewer'})
    login(c, 'bob')
    assert c.post(url, json={'name': 'new.typ', 'target': 'bad.typ'}).status_code == 403
    assert c.post(f'/api/projects/{pid}/snapshots', json={}).status_code == 403
