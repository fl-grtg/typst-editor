import base64
import sqlite3

import pytest
from conftest import login, make_doc, register_user
from fastapi import HTTPException
from pycrdt import Text

from backend import sync
from backend.services import quota
from backend.services.change_packages import csv_cell_content


@pytest.mark.parametrize('base,proposed,row,column,expected', [
    ('a,b\r\n"keep",old\r\nx,y\r\n', 'a,b\r\nkeep,new\r\nx,other\r\n', 1, 1, 'a,b\r\n"keep",new\r\nx,y\r\n'),
    ('a,b\n', 'a,b,new\nx,y,last\n', 0, 2, 'a,b,new\n'),
    ('a,b\n', 'a,b\n\n,,new\n,,,last\n', 2, 2, 'a,b\n\n,,new\n'),
    ('a,b\nx,y\n', 'a,b\n', 1, 0, 'a,b\n,y\n'),
    ('a,b\n,y\n', 'a,b\n', 1, 1, 'a,b\n'),
    ('a,b\nold,z\n', 'a,b\n"new,\nvalue",other\n', 1, 0, 'a,b\n"new,\nvalue",z\n'),
])
def test_csv_cell_accept_preserves_other_values_and_raw_format(base, proposed, row, column, expected):
    assert csv_cell_content(base, proposed, row, column, ',') == expected


def test_csv_cell_accept_keeps_other_proposals_pending(c):
    project, _ = setup(c)
    base, proposed = 'a,b\nold,keep\n', 'a,b\nnew,changed\n'
    assert c.post(f'/api/projects/{project}/resources', json={'name': 'data.csv', 'content': base}).status_code == 200
    package = submit(c, project, [{'kind': 'resource', 'path': 'data.csv', 'action': 'modify', 'base': base, 'content': proposed,
                                  'changes': [{'old_string': base, 'new_string': proposed}]}])
    file = package['files'][0]
    response = accept(c, project, package, file_id=file['id'], cell={'row': 1, 'column': 0})
    assert response.status_code == 200, response.text
    partial = response.json()
    assert partial['files'][0]['base'] == 'a,b\nnew,keep\n'
    assert partial['files'][0]['content'] == proposed
    resources = c.get(f'/api/projects/{project}/resources').json()['resources']
    assert next(r for r in resources if r['name'] == 'data.csv')['content'] == 'a,b\nnew,keep\n'
    assert accept(c, project, package, file_id=file['id'], cell={'row': 1, 'column': 1}).status_code == 409
    assert accept(c, project, partial, file_id=file['id'], cell={'row': 1, 'column': 0}).status_code == 409
    assert accept(c, project, partial, file_id=file['id'], cell={'row': 1, 'column': 1}).json()['files'] == []


def test_csv_added_file_cell_accept_and_permission_validation(c):
    project, _ = setup(c)
    package = submit(c, project, [{'kind': 'resource', 'path': 'new.tsv', 'action': 'add', 'content': 'first\tsecond\n'}])
    file = package['files'][0]
    assert accept(c, project, package, cell={'row': 0, 'column': 0}).status_code == 400
    assert accept(c, project, package, file_id=file['id'], cell={'row': -1, 'column': 0}).status_code == 400
    register_user(c, 'bob')
    login(c, 'alice')
    c.post(f'/api/projects/{project}/members', json={'username': 'bob', 'role': 'reviewer'})
    login(c, 'bob')
    assert accept(c, project, package, file_id=file['id'], cell={'row': 0, 'column': 0}).status_code == 403
    login(c, 'alice')
    response = accept(c, project, package, file_id=file['id'], cell={'row': 0, 'column': 0})
    assert response.status_code == 200, response.text
    partial = response.json()
    assert partial['files'][0]['action'] == 'modify'
    assert partial['files'][0]['base'] == 'first'
    assert accept(c, project, partial, file_id=file['id'], cell={'row': 0, 'column': 1}).json()['files'] == []


def test_bib_field_edit_accept_preserves_other_pending_fields(c):
    project, _ = setup(c)
    base = '@book{key, title={Old 😀}, author={Jane}}\n'
    proposed = base.replace('Old 😀', 'New 😀').replace('Jane', 'Joan')
    selected = base.replace('Old 😀', 'New 😀')
    assert c.post(f'/api/projects/{project}/resources', json={'name': 'sources.bib', 'content': base}).status_code == 200
    package = submit(c, project, [{'kind': 'resource', 'path': 'sources.bib', 'action': 'modify', 'base': base, 'content': proposed,
                                  'changes': [{'old_string': base, 'new_string': proposed}]}])
    file = package['files'][0]
    response = accept(c, project, package, file_id=file['id'], field_edit={'old_string': base, 'new_string': selected})
    assert response.status_code == 200, response.text
    partial = response.json()
    assert partial['files'][0]['base'] == selected
    assert partial['files'][0]['content'] == proposed
    resources = c.get(f'/api/projects/{project}/resources').json()['resources']
    assert next(r for r in resources if r['name'] == 'sources.bib')['content'] == selected
    assert accept(c, project, partial, file_id=file['id'], field_edit={'old_string': base, 'new_string': selected}).status_code == 409
    assert accept(c, project, partial, file_id=file['id'], field_edit={'old_string': selected, 'new_string': proposed}).json()['files'] == []


def test_document_delete_proposal_is_recoverable_and_keeps_live_text_and_attachments(c):
    project, document = setup(c, 'Original')
    current = 'Latest live text'
    with sync._doc_lock(sync.room(document)):
        text = sync.room(document)['doc'].get('typst', type=Text)
        del text[:]
        text.insert(0, current)
    assert c.post(f'/api/docs/{document}/files', files={'f': ('image.png', b'image')}).status_code == 200
    package = submit(c, project, [{'kind': 'document', 'doc_id': document, 'path': 'main.typ', 'action': 'delete', 'base': current}])
    assert c.get(f'/api/docs/{document}').status_code == 200
    assert accept(c, project, package).status_code == 200
    assert c.get(f'/api/docs/{document}').status_code == 410
    assert any(d['id'] == document for d in c.get('/api/docs').json()['trash'])
    assert c.post(f'/api/docs/{document}/restore').status_code == 200
    assert c.get(f'/api/docs/{document}').json()['content'] == current
    assert c.get(f'/api/docs/{document}/files/image.png').content == b'image'


def test_document_delete_with_pending_children_requires_combined_acceptance(c):
    project, document = setup(c, '#image("image.png")')
    assert c.post(f'/api/docs/{document}/files', files={'f': ('image.png', b'old')}).status_code == 200
    package = submit(c, project, [
        {'kind': 'document', 'doc_id': document, 'path': 'main.typ', 'action': 'delete', 'base': '#image("image.png")'},
        {'kind': 'file', 'doc_id': document, 'path': 'image.png', 'action': 'delete', 'base': base64.b64encode(b'old').decode(), 'binary': True},
    ])
    assert accept(c, project, package, file_id=package['files'][0]['id']).status_code == 409
    assert c.get(f'/api/docs/{document}').status_code == 200
    assert accept(c, project, package).status_code == 200
    assert c.post(f'/api/docs/{document}/restore').status_code == 200
    assert c.get(f'/api/docs/{document}/files/image.png').status_code == 404
    assert any(d['title'] == 'image.png' for d in c.get('/api/docs').json()['trash'])


def setup(c, content="first old\nlast old\n"):
    register_user(c, "alice")
    document = make_doc(c, "Packages", content)
    project = c.get(f"/api/docs/{document}").json()["project_id"]
    return project, document


def test_new_document_and_title_rename_stay_in_package_until_acceptance(c):
    project, document = setup(c, "old")
    package = submit(c, project, [
        {"kind": "document", "path": "main.typ", "action": "add", "target": "New document", "content": "New text"},
        {"kind": "document", "doc_id": document, "path": "main.typ", "action": "rename", "target": "Renamed",
         "original_title": "Packages", "base": "old", "content": "edited"},
    ])
    added = package["files"][0]["doc_id"]
    assert c.get(f"/api/docs/{added}").status_code == 404
    assert c.get(f"/api/docs/{document}").json()["title"] == "Packages"
    assert accept(c, project, package).status_code == 200
    assert c.get(f"/api/docs/{added}").json()["content"] == "New text"
    renamed = c.get(f"/api/docs/{document}").json()
    assert (renamed["title"], renamed["content"]) == ("Renamed", "edited")


def test_document_rename_detects_title_changes_and_target_collisions(c):
    project, document = setup(c, "old")
    package = submit(c, project, [{"kind": "document", "doc_id": document, "path": "main.typ", "action": "rename",
                                  "target": "Renamed", "original_title": "Packages", "base": "old", "content": "old"}])
    assert c.post(f"/api/docs/{document}/rename", json={"title": "Changed"}).status_code == 200
    assert accept(c, project, package).status_code == 409
    assert c.post(f"/api/docs/{document}/rename", json={"title": "Packages"}).status_code == 200
    assert c.post(f"/api/projects/{project}/docs", json={"title": "renamed"}).status_code == 200
    assert accept(c, project, package).status_code == 409
    assert c.get(f"/api/docs/{document}").json()["title"] == "Packages"


def test_new_documents_obey_owner_count_and_rollback_together(c, monkeypatch):
    from dataclasses import replace

    from backend import config

    project, _ = setup(c)
    package = submit(c, project, [{"kind": "document", "path": "main.typ", "action": "add", "target": title, "content": "text"}
                                  for title in ("One", "Two")])
    settings = replace(config.load(), MAX_DOCS_PER_USER=2)
    monkeypatch.setattr(config, "load", lambda: settings)
    assert accept(c, project, package).status_code == 400
    for file in package["files"]:
        assert c.get(f"/api/docs/{file['doc_id']}").status_code == 404


def test_added_document_rejects_path_traversal_identity(c):
    project, _ = setup(c)
    response = c.post(f"/api/projects/{project}/proposals", json={"title": "Invalid", "files": [
        {"kind": "document", "doc_id": "../outside", "path": "main.typ", "action": "add", "target": "New", "content": "text"}]})
    assert response.status_code == 404


@pytest.mark.parametrize('selected', ['rename', 'reference'])
def test_related_acceptance_keeps_independent_changes_in_same_document_pending(c, selected):
    base = '#import "old.typ": value\n#value\nUnrelated old text\n'
    project, document = setup(c, base)
    assert c.post(f'/api/projects/{project}/resources', json={'name': 'old.typ', 'content': '#let value = 1'}).status_code == 200
    package = submit(c, project, [
        document_change(document, base, [('"old.typ"', '"new.typ"'), ('Unrelated old text', 'Unrelated new text')]),
        {'kind': 'resource', 'path': 'old.typ', 'action': 'rename', 'target': 'new.typ', 'base': '#let value = 1', 'content': '#let value = 1'},
        {'kind': 'resource', 'path': 'unrelated.txt', 'action': 'add', 'content': 'Keep pending'},
    ])
    text, rename, unrelated = package['files']
    selection = {'file_id': rename['id']} if selected == 'rename' else {'file_id': text['id'], 'change_id': text['changes'][0]['id']}
    response = accept(c, project, package, **selection, include_dependencies=True)
    assert response.status_code == 200, response.text
    assert c.get(f'/api/docs/{document}').json()['content'] == base.replace('old.typ', 'new.typ')
    remaining = response.json()['files']
    assert len(remaining) == 2
    pending_text = next(f for f in remaining if f['id'] == text['id'])
    assert [change['id'] for change in pending_text['changes']] == [text['changes'][1]['id']]
    assert next(f for f in remaining if f['id'] == unrelated['id'])['action'] == 'add'
    assert {f['name'] for f in c.get(f'/api/projects/{project}/resources').json()['resources']} == {'new.typ'}


def test_related_new_file_acceptance_keeps_other_proposals_pending(c):
    base = '= Heading\nOther old text\n'
    project, document = setup(c, base)
    package = submit(c, project, [
        document_change(document, base, [('= Heading', '#include "new.typ"'), ('Other old text', 'Other new text')]),
        {'kind': 'resource', 'path': 'new.typ', 'action': 'add', 'content': '= Included heading'},
    ])
    source = package['files'][0]
    response = accept(c, project, package, file_id=source['id'], change_id=source['changes'][0]['id'], include_dependencies=True)
    assert response.status_code == 200, response.text
    assert c.get(f'/api/docs/{document}').json()['content'] == base.replace('= Heading', '#include "new.typ"')
    assert len(response.json()['files']) == 1
    assert response.json()['files'][0]['changes'][0]['id'] == source['changes'][1]['id']


def test_related_rename_leaves_renamed_file_contents_pending_at_new_path(c):
    base = '#import "old.typ": value\n#value\nUnrelated old text\n'
    project, document = setup(c, base)
    module = '#let value = 1\n#let footer = "Original"\n'
    proposed_module = module.replace('value = 1', 'value = 2')
    assert c.post(f'/api/projects/{project}/resources', json={'name': 'old.typ', 'content': module}).status_code == 200
    package = submit(c, project, [
        document_change(document, base, [('"old.typ"', '"new.typ"'), ('Unrelated old text', 'Unrelated new text')]),
        {'kind': 'resource', 'path': 'old.typ', 'action': 'rename', 'target': 'new.typ', 'base': module, 'content': proposed_module,
         'changes': [{'old_string': 'value = 1', 'new_string': 'value = 2'}]},
    ])
    source, rename = package['files']
    response = accept(c, project, package, file_id=source['id'], change_id=source['changes'][0]['id'], include_dependencies=True)
    assert response.status_code == 200, response.text
    resources = c.get(f'/api/projects/{project}/resources').json()['resources']
    assert next(f for f in resources if f['name'] == 'new.typ')['content'] == module
    partial = response.json()
    pending_module = next(f for f in partial['files'] if f['id'] == rename['id'])
    assert pending_module['action'] == 'modify' and pending_module['path'] == 'new.typ'
    assert pending_module['base'] == module and pending_module['content'] == proposed_module
    assert c.get(f'/api/docs/{document}').json()['content'] == base.replace('old.typ', 'new.typ')
    final = accept(c, project, partial, file_id=rename['id'])
    assert final.status_code == 200, final.text
    assert len(final.json()['files']) == 1
    resources = c.get(f'/api/projects/{project}/resources').json()['resources']
    assert next(f for f in resources if f['name'] == 'new.typ')['content'] == proposed_module


def test_structural_document_rename_keeps_content_pending_at_main_path(c):
    project, document = setup(c, 'Original text')
    package = submit(c, project, [{'kind': 'document', 'doc_id': document, 'path': 'main.typ', 'action': 'rename',
                                  'target': 'Renamed', 'original_title': 'Packages', 'base': 'Original text', 'content': 'Proposed text'}])
    response = accept(c, project, package, file_id=package['files'][0]['id'], change_id='@action')
    assert response.status_code == 200, response.text
    doc = c.get(f'/api/docs/{document}').json()
    assert (doc['title'], doc['content']) == ('Renamed', 'Original text')
    pending = response.json()['files'][0]
    assert pending['path'] == 'main.typ' and pending['action'] == 'modify'
    correction = c.patch(f"/api/projects/{project}/proposals/{package['id']}", json={
        'title': package['title'], 'revision': response.json()['revision'], 'files': [pending]})
    assert correction.status_code == 200, correction.text
    assert accept(c, project, correction.json()).status_code == 200
    assert c.get(f'/api/docs/{document}').json()['content'] == 'Proposed text'


@pytest.mark.parametrize('kind,binary', [('resource', False), ('document', False), ('file', True)])
def test_structural_add_keeps_later_content_edits_pending(c, kind, binary):
    project, document = setup(c)
    initial, proposed = ('Initial text', 'Proposed text') if not binary else (base64.b64encode(b'initial').decode(), base64.b64encode(b'proposed').decode())
    file = {'kind': kind, 'path': 'main.typ' if kind == 'document' else 'added.png' if binary else 'added.typ',
            'action': 'add', 'initial_content': initial, 'content': proposed, 'binary': binary}
    if kind == 'document':
        file['target'] = 'Added document'
    elif kind == 'file':
        file['doc_id'] = document
    package = submit(c, project, [file])
    saved = package['files'][0]
    response = accept(c, project, package, file_id=saved['id'], change_id='@action')
    assert response.status_code == 200, response.text
    assert response.json()['files'][0]['action'] == 'modify'
    assert response.json()['files'][0]['base'] == initial
    if kind == 'document':
        assert c.get(f"/api/docs/{saved['doc_id']}").json()['content'] == initial
    elif kind == 'resource':
        assert next(f for f in c.get(f'/api/projects/{project}/resources').json()['resources'] if f['name'] == 'added.typ')['content'] == initial
    else:
        assert c.get(f'/api/docs/{document}/files/added.png').content == b'initial'
    assert accept(c, project, response.json()).status_code == 200


def document_change(document, base, changes):
    content = base
    for old, new in changes:
        content = content.replace(old, new)
    return {"kind": "document", "doc_id": document, "path": "main.typ", "action": "modify", "base": base,
            "content": content, "changes": [{"old_string": old, "new_string": new} for old, new in changes]}


def submit(c, project, files):
    response = c.post(f"/api/projects/{project}/proposals", json={"title": "Review me", "files": files})
    assert response.status_code == 200, response.text
    return response.json()


def accept(c, project, package, **selection):
    return c.post(f"/api/projects/{project}/proposals/{package['id']}/accept", json={"revision": package["revision"], **selection})


def test_submission_preserves_independent_source_edits(c):
    project, document = setup(c, "alpha beta gamma\n")
    draft = document_change(document, "alpha beta gamma\n", [("beta", "BETA")])
    current = "new introduction\nalpha beta gamma\n"
    assert c.post(f"/api/docs/{document}/save", json={"content": current, "force": True}).status_code == 200
    package = submit(c, project, [draft])
    assert package["files"][0]["base"] == current
    assert package["files"][0]["content"] == current.replace("beta", "BETA")
    assert c.get(f"/api/docs/{document}").json()["content"] == current
    assert accept(c, project, package).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == current.replace("beta", "BETA")


def test_submission_conflict_keeps_current_source_untouched(c):
    project, document = setup(c, "alpha beta gamma\n")
    draft = document_change(document, "alpha beta gamma\n", [("beta", "BETA")])
    current = "alpha replaced gamma\n"
    assert c.post(f"/api/docs/{document}/save", json={"content": current, "force": True}).status_code == 200
    response = c.post(f"/api/projects/{project}/proposals", json={"title": "Conflict", "files": [draft]})
    assert response.status_code == 409
    assert c.get(f"/api/docs/{document}").json()["content"] == current
    assert c.get(f"/api/projects/{project}/proposals").json()["packages"] == []


@pytest.mark.parametrize("base,changes,current", [
    ("beta", [("beta", "beta version")], "beta version"),
    ("ab something bc", [("ab", "AB"), ("bc", "BC")], "abc"),
])
def test_submission_rebase_rejects_applied_insertions_and_new_overlaps(c, base, changes, current):
    project, document = setup(c, base)
    draft = document_change(document, base, changes)
    assert c.post(f"/api/docs/{document}/save", json={"content": current, "force": True}).status_code == 200
    response = c.post(f"/api/projects/{project}/proposals", json={"title": "Conflict", "files": [draft]})
    assert response.status_code == 409, response.text
    assert response.json()["detail"].startswith("Original passage changed")
    assert c.get(f"/api/docs/{document}").json()["content"] == current
    assert c.get(f"/api/projects/{project}/proposals").json()["packages"] == []


def test_reviewer_submission_is_isolated_and_owner_can_partially_accept(c):
    project, document = setup(c)
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [document_change(document, "first old\nlast old\n", [("first old", "first new"), ("last old", "last new")])])
    assert c.get(f"/api/docs/{document}").json()["content"] == "first old\nlast old\n"
    assert accept(c, project, package).status_code == 403
    login(c, "alice")
    file = package["files"][0]
    response = accept(c, project, package, file_id=file["id"], change_id=file["changes"][0]["id"])
    assert response.status_code == 200, response.text
    partial = response.json()
    assert partial["accepted"] == 1
    assert len(partial["files"][0]["changes"]) == 1
    assert c.get(f"/api/docs/{document}").json()["content"] == "first new\nlast old\n"
    assert str(sync.room(document)["doc"].get("typst", type=Text)) == "first new\nlast old\n"
    assert accept(c, project, package).status_code == 409
    assert accept(c, project, partial, file_id=file["id"]).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == "first new\nlast new\n"


def test_editor_corrects_proposal_but_cannot_delete_another_authors_package(c):
    project, document = setup(c, "old")
    package = submit(c, project, [document_change(document, "old", [("old", "proposed")])])
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "editor"})
    login(c, "bob")
    file = package["files"][0]
    file["content"] = "corrected"
    file["changes"][0]["new_string"] = "corrected"
    response = c.patch(f"/api/projects/{project}/proposals/{package['id']}", json={"title": "Correction", "revision": package["revision"], "files": [file]})
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{document}").json()["content"] == "old"
    assert c.delete(f"/api/projects/{project}/proposals/{package['id']}").status_code == 403
    assert accept(c, project, response.json()).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == "corrected"


def test_added_attachment_dependencies_require_combined_acceptance(c):
    project, document = setup(c, "old")
    text = document_change(document, "old", [("old", '#image("plot.png")')])
    image = {"kind": "file", "doc_id": document, "path": "plot.png", "action": "add", "content": base64.b64encode(b"image").decode(), "binary": True}
    package = submit(c, project, [text, image])
    assert c.get(f"/api/docs/{document}/files/plot.png").status_code == 404
    assert accept(c, project, package, file_id=package["files"][0]["id"]).status_code == 409
    response = accept(c, project, package)
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{document}/files/plot.png").content == b"image"


def test_quota_failure_rolls_back_files_database_and_live_document(c, monkeypatch):
    project, document = setup(c, "old")
    text = document_change(document, "old", [("old", "new")])
    attachment = {"kind": "file", "doc_id": document, "path": "new.csv", "action": "add", "content": "a,b\n"}
    package = submit(c, project, [attachment, text])
    monkeypatch.setattr(quota, "check_quota", lambda *args, **kwargs: (_ for _ in ()).throw(HTTPException(413, "quota")))
    assert accept(c, project, package).status_code == 413
    assert c.get(f"/api/docs/{document}/files/new.csv").status_code == 404
    assert c.get(f"/api/docs/{document}").json()["content"] == "old"
    assert str(sync.room(document)["doc"].get("typst", type=Text)) == "old"
    saved = c.get(f"/api/projects/{project}/proposals/{package['id']}").json()
    assert saved["revision"] == package["revision"]


def test_file_acceptance_and_deleting_partial_package_preserve_accepted_changes(c):
    project, document = setup(c, "old")
    c.post(f"/api/projects/{project}/resources", json={"name": "data.csv", "content": "a,b\n1,2\n"})
    file = {"kind": "resource", "path": "data.csv", "action": "modify", "base": "a,b\n1,2\n", "content": "a,b\n3,4\n", "changes": [{"old_string": "1,2", "new_string": "3,4"}]}
    package = submit(c, project, [file, document_change(document, "old", [("old", "new")])])
    response = accept(c, project, package, file_id=package["files"][0]["id"])
    assert response.status_code == 200, response.text
    assert c.delete(f"/api/projects/{project}/proposals/{package['id']}").status_code == 200
    resources = c.get(f"/api/projects/{project}/resources").json()["resources"]
    assert next(r["content"] for r in resources if r["name"] == "data.csv") == "a,b\n3,4\n"
    assert c.get(f"/api/docs/{document}").json()["content"] == "old"


def test_delete_and_rename_file_proposals_are_not_applied_until_acceptance(c):
    project, document = setup(c)
    c.post(f"/api/projects/{project}/resources", json={"name": "unused.bib", "content": "old"})
    package = submit(c, project, [{"kind": "resource", "path": "unused.bib", "action": "rename", "target": "renamed.bib", "base": "old", "content": "old"}])
    assert accept(c, project, package).status_code == 200
    package = submit(c, project, [{"kind": "resource", "path": "renamed.bib", "action": "delete", "base": "old"}])
    assert accept(c, project, package).status_code == 200
    assert any(t["title"] == "renamed.bib" for t in c.get("/api/docs").json()["trash"])


def test_foreign_project_access_and_duplicate_file_ids_are_rejected(c):
    project, document = setup(c, "old")
    package = submit(c, project, [document_change(document, "old", [("old", "new")])])
    register_user(c, "eve")
    assert c.get(f"/api/projects/{project}/proposals").status_code == 404
    assert accept(c, project, package).status_code == 404
    login(c, "alice")
    file = document_change(document, "old", [("old", "new")])
    file["id"] = "duplicate"
    other = {"id": "duplicate", "kind": "resource", "path": "new.typ", "action": "add", "content": "text"}
    assert c.post(f"/api/projects/{project}/proposals", json={"title": "bad", "files": [file, other]}).status_code == 400


def test_account_rename_does_not_wipe_authored_packages(c):
    project, document = setup(c, "old")
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [document_change(document, "old", [("old", "proposal")])])
    # Rename the author account: the package's FK cascaded to NOTHING before
    # the rename moved its author row (delete + insert, no ON UPDATE).
    assert c.post("/api/me/name", json={"name": "bobby", "password": "pass1234"}).status_code == 200
    login(c, "alice")
    rows = c.get(f"/api/projects/{project}/proposals").json()["packages"]
    assert [p["id"] for p in rows] == [package["id"]], rows
    assert rows[0]["author"] == "bobby"
    # It stays fully usable: the new owner can still accept it.
    assert accept(c, project, package).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == "proposal"


def test_correction_can_discard_the_last_pending_change(c):
    project, document = setup(c, "old")
    package = submit(c, project, [document_change(document, "old", [("old", "new")])])
    response = c.patch(f"/api/projects/{project}/proposals/{package['id']}",
                       json={"title": "Correction", "revision": package["revision"], "files": []})
    assert response.status_code == 200, response.text
    saved = c.get(f"/api/projects/{project}/proposals/{package['id']}").json()
    assert saved["revision"] == package["revision"] + 1
    assert saved["files"] == []
    assert c.get(f"/api/docs/{document}").json()["content"] == "old"
    assert c.get(f"/api/projects/{project}/proposals").json()["packages"] == []


def test_partial_accept_keeps_unrebasable_sibling_marked_stale(c):
    project, document = setup(c, "alpha beta gamma\n")
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [document_change(
        document, "alpha beta gamma\n",
        [("beta", "BETA"), ("gamma", "GAMMA")],
    )])
    login(c, "alice")
    # External edit removes the sibling's anchor BEFORE the accept.
    assert c.post(f"/api/docs/{document}/save", json={"content": "alpha beta\n", "force": True}).status_code == 200
    file = package["files"][0]
    response = accept(c, project, package, file_id=file["id"], change_id=file["changes"][0]["id"])
    assert response.status_code == 200, response.text
    partial = response.json()
    sibling = partial["files"][0]
    assert sibling["stale"] is True, sibling
    assert sibling["base"] == "alpha beta gamma\n"  # untouched original state
    assert sibling["content"] == "alpha beta GAMMA\n"
    assert [ch["old_string"] for ch in sibling["changes"]] == ["gamma"]
    # The selected change was applied, the stale sibling was not.
    assert c.get(f"/api/docs/{document}").json()["content"] == "alpha BETA\n"
    assert c.get(f"/api/docs/{document}").json()["content"] != "alpha BETA GAMMA\n"
    saved = c.get(f"/api/projects/{project}/proposals/{package['id']}").json()
    assert saved["files"][0]["stale"] is True
    assert saved["files"][0]["base"] == "alpha beta gamma\n"


def test_accept_rebases_still_matching_sibling_as_before(c):
    project, document = setup(c, "alpha beta gamma\n")
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [document_change(
        document, "alpha beta gamma\n",
        [("beta", "BETA"), ("gamma", "GAMMA")],
    )])
    login(c, "alice")
    file = package["files"][0]
    response = accept(c, project, package, file_id=file["id"], change_id=file["changes"][0]["id"])
    assert response.status_code == 200, response.text
    partial = response.json()
    sibling = partial["files"][0]
    assert "stale" not in sibling, sibling
    assert sibling["base"] == "alpha BETA gamma\n"
    assert accept(c, project, partial, file_id=file["id"]).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == "alpha BETA GAMMA\n"


def test_dependencies_trust_empty_live_room_over_stale_db_text(c, monkeypatch):
    project, document = setup(c, '#image("plot.png")\n')
    register_user(c, "bob")
    login(c, "alice")
    plotdata = b"plotdata-bytes"
    assert c.post(f"/api/docs/{document}/files", files={"f": ("plot.png", plotdata)}).status_code == 200
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [{
        "kind": "file", "doc_id": document, "path": "plot.png",
        "action": "delete", "base": plotdata.decode(),
    }])
    # The live room reports EMPTY text while the DB row is stale and still
    # references plot.png: falling back to the stale text would let the
    # document ref check block this unrelated delete with a 409.
    monkeypatch.setattr(sync, "room_text", lambda doc_id: "" if doc_id == document else None)
    login(c, "alice")
    response = accept(c, project, package)
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{document}/files/plot.png").status_code == 404


def test_proposal_cannot_add_case_variant_of_existing_resource(c):
    project, document = setup(c, "old")
    assert c.post(f"/api/projects/{project}/resources", json={"name": "data.csv", "content": "original"}).status_code == 200
    package = submit(c, project, [{"kind": "resource", "path": "DATA.csv", "action": "add", "content": "proposal"}])
    response = accept(c, project, package)
    assert response.status_code == 409, response.text
    rows = c.get(f"/api/projects/{project}/resources").json()["resources"]
    assert [(row["name"], row["content"]) for row in rows] == [("data.csv", "original")]


def test_failed_undo_snapshot_cannot_desync_a_committed_accept(c, monkeypatch):
    from backend.services import snapshots

    project, document = setup(c, "old")
    package = submit(c, project, [document_change(document, "old", [("old", "new")])])
    monkeypatch.setattr(snapshots, "auto_snap", lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("busy")))
    response = accept(c, project, package)
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{document}").json()["content"] == "new"
    assert str(sync.room(document)["doc"].get("typst", type=Text)) == "new"


def test_acceptance_releases_upload_and_package_locks_before_project_history(c, monkeypatch):
    from backend.services import project_history
    from backend.services.locks import _named_lock

    project, document = setup(c, "Original")
    package = submit(c, project, [document_change(document, "Original", [("Original", "Accepted")])])
    checkpoints = []

    def checkpoint(doc_id):
        for name in ("upload:" + doc_id, "packages:" + project):
            lock = _named_lock(name)
            assert lock.acquire(blocking=False), "History would deadlock on acceptance lock: " + name
            lock.release()
        assert sync.room_text(doc_id) == "Accepted"
        checkpoints.append(doc_id)

    monkeypatch.setattr(project_history, "auto_document", checkpoint)
    response = accept(c, project, package)
    assert response.status_code == 200, response.text
    assert checkpoints == [document]
    assert response.json()["files"] == []
    assert c.get(f"/api/docs/{document}").json()["content"] == "Accepted"


@pytest.mark.parametrize("first", ["module", "hint", "attachment", "reference"])
def test_related_acceptance_can_update_references_inside_a_renamed_document(c, first):
    main = '#import "old.typ": value\nIndependent old\n'
    appendix = '#import "old.typ": value\nAppendix old\n'
    project, document = setup(c, main)
    response = c.post(f"/api/projects/{project}/docs", json={"title": "Appendix", "content": appendix})
    assert response.status_code == 200, response.text
    other = response.json()["id"]
    assert c.post(f"/api/projects/{project}/resources", json={"name": "old.typ", "content": "#let value = 1"}).status_code == 200
    package = submit(c, project, [
        document_change(document, main, [('"old.typ"', '"new.typ"\n#include "hint.typ"'), ('Independent old', 'Independent new')]),
        {"kind": "document", "doc_id": other, "path": "main.typ", "action": "rename", "original_title": "Appendix", "target": "Appendix B",
         "base": appendix, "content": appendix.replace('"old.typ"', '"new.typ"').replace('Appendix old', 'Appendix new'),
         "changes": [{"old_string": '"old.typ"', "new_string": '"new.typ"'}, {"old_string": "Appendix old", "new_string": "Appendix new"}]},
        {"kind": "resource", "path": "old.typ", "action": "rename", "target": "new.typ", "base": "#let value = 1", "content": "#let value = 2",
         "changes": [{"old_string": "value = 1", "new_string": "value = 2"}]},
        {"kind": "resource", "path": "hint.typ", "action": "add", "content": '#import "new.typ": value'},
        {"kind": "file", "doc_id": other, "path": "head.typ", "action": "add", "content": '#import "new.typ": value'},
    ])
    source, renamed_doc, module, hint, attachment = package["files"]
    selected = {"module": module, "hint": hint, "attachment": attachment, "reference": source}[first]
    response = accept(c, project, package, file_id=selected["id"],
                      change_id=source["changes"][0]["id"] if first == "reference" else "@action", include_dependencies=True)
    assert response.status_code == 200, response.text
    partial = response.json()
    current = c.get(f"/api/docs/{other}").json()
    assert current["title"] == "Appendix B"
    assert current["content"] == appendix.replace('"old.typ"', '"new.typ"')
    pending = next(f for f in partial["files"] if f["id"] == renamed_doc["id"])
    assert pending["action"] == "modify"
    assert [change["old_string"] for change in pending["changes"]] == ["Appendix old"]
    assert "Independent old" in c.get(f"/api/docs/{document}").json()["content"]
    resources = c.get(f"/api/projects/{project}/resources").json()["resources"]
    assert next(f for f in resources if f["name"] == "new.typ")["content"] == "#let value = 1"
    assert accept(c, project, partial).status_code == 200
