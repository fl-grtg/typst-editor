import pytest
from conftest import register_user
from fastapi import HTTPException

from backend import db
from backend import mcp_tools as tools


@pytest.fixture
def project(c):
    for user in ('project_owner', 'project_editor', 'project_reader', 'outsider'):
        register_user(c, user)
    with db.tx() as con:
        con.execute("INSERT INTO projects(id,owner,title,created_at) VALUES ('p_test','project_owner','Project',?)", (db.now_iso(),))
        con.executemany("INSERT INTO project_members VALUES ('p_test',?,?)",
                        [('project_editor', 'editor'), ('project_reader', 'reviewer')])
    return '/projects/p_test'


@pytest.mark.anyio
async def test_project_paths_and_nested_local_files(c, project):
    with pytest.raises(HTTPException) as e:
        tools.op_create('project_editor', 'reviewer', project + '/docs/Blocked', 'hello')
    assert e.value.status_code == 403
    tools.op_create('project_editor', 'editor', project + '/docs/Report', 'hello needle')
    path = project + '/docs/Report/chapters/part.typ'
    tools.op_create('project_editor', 'editor', path, 'nested old')
    assert tools.op_read('project_editor', 'editor', path)['content'] == 'nested old'
    await tools.op_edit('project_editor', 'editor', path, 'old', 'new')
    assert tools.op_read('project_owner', 'editor', '/docs/Report/chapters/part.typ')['content'] == 'nested new'
    assert tools.op_read('project_reader', 'reviewer', '/shared/project_owner/Report/chapters/part.typ')['content'] == 'nested new'
    assert tools.op_ls('project_reader', 'editor', '/shared')['shared'][0]['title'] == 'Report'
    assert tools.op_search('project_reader', 'editor', 'needle')['hits']
    assert tools.op_search('outsider', 'editor', 'needle')['hits'] == []
    await tools.op_edit('project_editor', 'editor', project + '/docs/Report', 'hello', 'goodbye')
    assert tools.op_read('project_editor', 'editor', project + '/docs/Report')['content'] == 'goodbye needle'


@pytest.mark.anyio
async def test_project_resources_permissions_conflicts_and_search(c, project, monkeypatch):
    path = project + '/resources/nested/library.typ'
    tools.op_create('project_editor', 'editor', path, 'secret needle')
    assert tools.op_ls('project_reader', 'reviewer', project + '/resources')['resources'][0]['name'] == 'nested/library.typ'
    assert tools.op_search('project_reader', 'reviewer', 'needle')['hits'][0]['path'] == path
    assert tools.op_search('outsider', 'editor', 'needle')['hits'] == []
    with pytest.raises(HTTPException) as e:
        tools.op_create('project_editor', 'editor', path, 'overwrite')
    assert e.value.status_code == 409
    for user, cap in [('project_reader', 'editor'), ('project_editor', 'reviewer')]:
        with pytest.raises(HTTPException) as e:
            await tools.op_edit(user, cap, path, 'secret', 'public')
        assert e.value.status_code == 403
    await tools.op_edit('project_editor', 'editor', path, 'secret', 'updated')
    assert tools.op_read('project_reader', 'reviewer', path)['content'] == 'updated needle'
    original = tools._current_text
    def revoke(user, res):
        result = original(user, res)
        with db.tx() as con:
            con.execute("DELETE FROM project_members WHERE username='project_editor'")
        return result
    monkeypatch.setattr(tools, '_current_text', revoke)
    with pytest.raises(HTTPException) as e:
        await tools.op_edit('project_editor', 'editor', path, 'updated', 'revoked')
    assert e.value.status_code == 404
    assert tools.op_read('project_owner', 'editor', path)['content'] == 'updated needle'


@pytest.mark.anyio
async def test_project_path_trashed_doc_answers_410_and_active_namesake_wins(c, project):
    tools.op_create('project_editor', 'editor', project + '/docs/Shelf', 'old text')
    with db.tx() as con:
        did = con.execute("SELECT id FROM docs WHERE project_id='p_test' AND title='Shelf'").fetchone()["id"]
        con.execute("UPDATE docs SET trashed=1, updated_at=? WHERE id=?", (db.now_iso(), did))
    with pytest.raises(HTTPException) as e:
        tools.op_read('project_editor', 'editor', project + '/docs/Shelf')
    assert e.value.status_code == 410 and 'trash' in e.value.detail.lower()
    # A fresh doc may reuse the trashed title (the partial unique index only
    # covers trashed=0): the project path then serves the active namesake.
    tools.op_create('project_editor', 'editor', project + '/docs/Shelf', 'fresh text')
    assert tools.op_read('project_owner', 'editor', project + '/docs/Shelf')['content'] == 'fresh text'


@pytest.mark.anyio
async def test_mcp_can_read_and_edit_copy_names_with_spaces(c):
    register_user(c, 'alice')
    c.post('/api/templates', json={'name': 'module.typ', 'content': 'original'})
    c.post('/api/templates/module.typ/duplicate', json={})
    path = '/templates/module (copy).typ'
    assert tools.op_read('alice', 'editor', path)['content'] == 'original'
    await tools.op_edit('alice', 'editor', path, 'original', 'changed')
    assert tools.op_read('alice', 'editor', path)['content'] == 'changed'
    did = c.post('/api/docs/create', json={'title': 'Doc'}).json()['id']
    c.post(f'/api/docs/{did}/files', files={'f': ('data (copy).csv', b'old', 'text/csv')})
    local = '/docs/Doc/data (copy).csv'
    assert tools.op_read('alice', 'editor', local)['content'] == 'old'
    await tools.op_edit('alice', 'editor', local, 'old', 'new')
    assert tools.op_read('alice', 'editor', local)['content'] == 'new'
