"""Project names, copy/move ACLs and collision handling."""
import io
import zipfile

import pytest
from conftest import login, register_user
from pycrdt import Doc, Text

from backend import db, sync


def setup_projects(c):
    register_user(c, 'alice')
    ids = [c.post('/api/docs/create', json={'title': title}).json()['id'] for title in ['A', 'B']]
    pids = [c.get(f'/api/docs/{did}').json()['project_id'] for did in ids]
    return ids, pids


def test_document_names_are_project_local_and_restore_never_overwrites(c):
    ids, pids = setup_projects(c)
    docs = []
    for pid in pids:
        r = c.post(f'/api/projects/{pid}/docs', json={'title': 'main.typ', 'content': pid})
        assert r.status_code == 200, r.text
        docs.append(r.json()['id'])
    assert c.post(f'/api/projects/{pids[0]}/docs', json={'title': 'MAIN.typ'}).status_code == 409
    assert c.delete(f'/api/docs/{docs[0]}').status_code == 200
    replacement = c.post(f'/api/projects/{pids[0]}/docs', json={'title': 'main.typ', 'content': 'keep'})
    assert replacement.status_code == 200, replacement.text
    assert c.post(f'/api/docs/{docs[0]}/restore').status_code == 409
    assert c.get(f'/api/docs/{replacement.json()["id"]}').json()['content'] == 'keep'
    assert c.post(f'/api/docs/{docs[1]}/rename', json={'title': 'A'}).status_code == 200


def test_document_transfer_preserves_resources_files_and_detects_conflicts(c):
    ids, (source, target) = setup_projects(c)
    c.post(f'/api/projects/{source}/resources', json={'name': 'layout.typ', 'content': 'snapshot'})
    did = c.post(f'/api/projects/{source}/docs', json={'title': 'Shared name', 'folder': 'chapters/sub', 'content': '#include "layout.typ"'}).json()['id']
    c.post(f'/api/docs/{did}/files', files={'f': ('pic.png', b'\x89PNG\xff', 'image/png')})
    body = {'kind': 'document', 'doc_id': did, 'target_project_id': target, 'target_name': 'Shared name'}
    url = f'/api/projects/{source}/transfer'
    result = c.post(url, json=body)
    assert result.status_code == 200, result.text
    copied = result.json()['doc_id']
    assert copied != did
    assert c.get(f'/api/docs/{copied}').json()['folder'] == 'chapters/sub'
    assert c.get(f'/api/docs/{copied}/files/pic.png').content == b'\x89PNG\xff'
    assert c.get(f'/api/projects/{target}/resources').json()['resources'][0]['content'] == 'snapshot'
    assert c.post(url, json={**body, 'move': True}).status_code == 409
    moved = c.post(url, json={**body, 'move': True, 'target_name': 'Moved'})
    assert moved.status_code == 200, moved.text
    assert c.get(f'/api/docs/{did}').json()['project_id'] == target
    assert c.get(f'/api/docs/{did}').json()['folder'] == 'chapters/sub'
    assert did not in [d['id'] for d in c.get(f'/api/projects/{source}').json()['documents']]


def test_resource_and_binary_transfer_acl_and_snapshot_independence(c):
    ids, (source, target) = setup_projects(c)
    c.post(f'/api/projects/{source}/resources', json={'name': 'sub/root.typ', 'content': '#include "leaf.typ"'})
    c.post(f'/api/projects/{source}/resources', json={'name': 'sub/leaf.typ', 'content': 'original'})
    url = f'/api/projects/{source}/transfer'
    body = {'kind': 'resource', 'name': 'sub/root.typ', 'target_project_id': target, 'target_name': 'copy/root.typ'}
    result = c.post(url, json=body)
    assert result.status_code == 200, result.text
    library = {r['name']: r['content'] for r in c.get(f'/api/projects/{target}/resources').json()['resources']}
    assert library == {'copy/root.typ': '#include "leaf.typ"', 'copy/leaf.typ': 'original'}
    assert c.post(url, json=body).status_code == 409
    c.post(f'/api/docs/{ids[0]}/files', files={'f': ('photo.png', b'bytes', 'image/png')})
    binary = {'kind': 'file', 'doc_id': ids[0], 'name': 'photo.png', 'target_project_id': target, 'target_doc_id': ids[1], 'target_name': 'photo.png', 'move': True}
    assert c.post(url, json=binary).status_code == 200
    assert c.get(f'/api/docs/{ids[0]}/files/photo.png').status_code == 404
    assert c.get(f'/api/docs/{ids[1]}/files/photo.png').content == b'bytes'
    register_user(c, 'bob')
    login(c, 'alice')
    c.post(f'/api/projects/{source}/members', json={'username': 'bob', 'role': 'reviewer'})
    c.post(f'/api/projects/{target}/members', json={'username': 'bob', 'role': 'editor'})
    login(c, 'bob')
    assert c.post(url, json={**body, 'target_name': 'reader/root.typ', 'move': True}).status_code == 403
    assert c.post(url, json={**body, 'target_name': 'reader/root.typ'}).status_code == 200


def test_zip_import_into_shared_project_bills_and_scopes_to_project_owner(c):
    ids, (source, target) = setup_projects(c)
    register_user(c, 'bob')
    login(c, 'alice')
    c.post(f'/api/projects/{target}/members', json={'username': 'bob', 'role': 'editor'})
    login(c, 'bob')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('main.typ', '#include "module.typ"')
        archive.writestr('module.typ', 'ZIP module')
    r = c.post(f'/api/projects/{target}/import-zip', data={'title': 'main.typ'}, files={'f': ('source.zip', data.getvalue(), 'application/zip')})
    assert r.status_code == 200, r.text
    did = r.json()['id']
    with db.tx() as con:
        row = con.execute('SELECT owner,project_id FROM docs WHERE id=?', (did,)).fetchone()
        assert tuple(row) == ('alice', target)
    assert c.get(f'/api/docs/{did}/files/module.typ/text').json()['content'] == 'ZIP module'


def test_direct_duplicates_choose_copy_names_without_overwriting(c):
    ids, (source, _) = setup_projects(c)
    c.post(f'/api/projects/{source}/resources', json={'name': 'layout.typ', 'content': 'original'})
    c.post(f'/api/docs/{ids[0]}/files', files={'f': ('image.png', b'image', 'image/png')})
    for kind, name, did in [('resource', 'layout.typ', ''), ('document', 'A', ids[0]), ('file', 'image.png', ids[0])]:
        body = {'kind': kind, 'name': name, 'doc_id': did, 'target_project_id': source, 'duplicate': True}
        first = c.post(f'/api/projects/{source}/transfer', json=body)
        second = c.post(f'/api/projects/{source}/transfer', json=body)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert '(copy)' in first.json()['name']
        assert '(copy 2)' in second.json()['name']
    assert c.get(f'/api/docs/{ids[0]}/files/image%20(copy).png').content == b'image'
    resources = {r['name']: r['content'] for r in c.get(f'/api/projects/{source}/resources').json()['resources']}
    assert resources['layout (copy).typ'] == resources['layout (copy 2).typ'] == resources['layout.typ'] == 'original'


def test_private_module_copy_name_remains_usable_in_document_references(c):
    register_user(c, 'alice')
    c.post('/api/templates', json={'name': 'module.typ', 'content': 'Copied module'})
    for expected in ['module (copy).typ', 'module (copy 2).typ']:
        result = c.post('/api/templates/module.typ/duplicate', json={})
        assert result.status_code == 200, result.text
        assert result.json()['name'] == expected
        assert c.get('/api/templates/' + expected).json()['content'] == 'Copied module'
    result = c.post('/api/docs/create', json={'title': 'Uses copy', 'content': '#include "module (copy).typ"'})
    assert result.status_code == 200, result.text
    resources = c.get(f'/api/docs/{result.json()["id"]}/resources').json()['resources']
    assert resources['module (copy).typ'] == 'Copied module'


def test_project_zip_contains_all_documents_modules_and_binary_files_for_readers(c):
    ids, (source, _) = setup_projects(c)
    other = c.post(f'/api/projects/{source}/docs', json={'title': 'Second', 'content': 'second'}).json()['id']
    c.post(f'/api/projects/{source}/resources', json={'name': 'unused.typ', 'content': 'unused'})
    c.post(f'/api/docs/{ids[0]}/files', files={'f': ('image.png', b'image', 'image/png')})
    register_user(c, 'bob')
    login(c, 'alice')
    c.post(f'/api/projects/{source}/members', json={'username': 'bob', 'role': 'reviewer'})
    login(c, 'bob')
    result = c.get(f'/api/projects/{source}/export-zip')
    assert result.status_code == 200, result.text
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert archive.read(f'documents/{other}/main.typ') == b'second'
        assert archive.read(f'documents/{ids[0]}/image.png') == b'image'
        assert archive.read('modules/unused.typ') == b'unused'
    login(c, 'alice')
    c.delete(f'/api/projects/{source}/members/bob')
    c.post(f'/api/docs/{ids[0]}/share', json={'username': 'bob', 'role': 'reviewer'})
    login(c, 'bob')
    result = c.get(f'/api/projects/{source}/export-zip')
    assert result.status_code == 200, result.text
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert f'documents/{other}/main.typ' not in archive.namelist()
        assert 'modules/unused.typ' not in archive.namelist()


@pytest.mark.parametrize('kind', ['document', 'resource', 'file'])
def test_cross_owner_move_requires_source_owner_but_copy_is_allowed(c, kind):
    ids, (source, _) = setup_projects(c)
    c.post(f'/api/projects/{source}/resources', json={'name': 'module.typ', 'content': 'shared'})
    c.post(f'/api/docs/{ids[0]}/files', files={'f': ('photo.png', b'image', 'image/png')})
    register_user(c, 'bob')
    target_doc = c.post('/api/docs/create', json={'title': 'Bob'}).json()['id']
    target = c.get(f'/api/docs/{target_doc}').json()['project_id']
    login(c, 'alice')
    c.post(f'/api/projects/{source}/members', json={'username': 'bob', 'role': 'editor'})
    login(c, 'bob')
    body = {'kind': kind, 'doc_id': ids[0], 'name': 'module.typ' if kind == 'resource' else 'photo.png',
            'target_project_id': target, 'target_doc_id': target_doc, 'target_name': 'copied.typ' if kind != 'file' else 'copied.png'}
    url = f'/api/projects/{source}/transfer'
    assert c.post(url, json={**body, 'move': True}).status_code == 403
    assert c.post(url, json=body).status_code == 200
    # Owner can explicitly move the original into an editable foreign project.
    c.post(f'/api/projects/{target}/members', json={'username': 'alice', 'role': 'editor'})
    login(c, 'alice')
    result = c.post(url, json={**body, 'move': True, 'target_name': 'moved.typ' if kind != 'file' else 'moved.png'})
    assert result.status_code == 200, result.text


def test_move_persists_live_text_and_matching_yjs_before_room_restart(c):
    ids, (source, target) = setup_projects(c)
    did = ids[0]
    old = Doc()
    old.get('typst', type=Text).insert(0, 'old')
    db.save_room(did, old.get_update(), 'old')
    room = sync.room(did)
    room['doc'].get('typst', type=Text).insert(3, ' live edits')
    result = c.post(f'/api/projects/{source}/transfer', json={'kind': 'document', 'doc_id': did,
                    'target_project_id': target, 'target_name': 'Moved', 'move': True})
    assert result.status_code == 200, result.text
    assert c.get(f'/api/docs/{did}').json()['content'] == 'old live edits'
    sync.rooms.pop(did)
    assert str(sync.room(did)['doc'].get('typst', type=Text)) == 'old live edits'
