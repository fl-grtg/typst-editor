"""Attachment editors must not silently overwrite a newer shared edit."""
from conftest import login, make_doc, register_user


def test_shared_file_stale_version_preserves_newer_content(c):
    register_user(c, "alice")
    did = make_doc(c)
    url = f"/api/docs/{did}/files/chapter.typ/text"
    assert c.post(url, json={"content": "Original"}).status_code == 200
    version = c.get(url).json()["version"]
    register_user(c, "bob")
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    assert c.post(url, json={"content": "Bob edit", "version": version}).status_code == 200
    login(c, "alice")
    stale = c.post(url, json={"content": "Alice stale edit", "version": version})
    assert stale.status_code == 409
    assert c.get(url).json()["content"] == "Bob edit"
    fresh = c.get(url).json()["version"]
    response = c.post(url, json={"content": "Alice resolved edit", "version": fresh})
    assert response.status_code == 200
    assert response.json()["version"] != fresh


def test_version_guard_detects_deleted_file(c):
    register_user(c, "alice")
    did = make_doc(c)
    url = f"/api/docs/{did}/files/chapter.typ/text"
    assert c.post(url, json={"content": "Original"}).status_code == 200
    version = c.get(url).json()["version"]
    assert c.delete(f"/api/docs/{did}/files/chapter.typ").status_code == 200
    assert c.post(url, json={"content": "Zombie edit", "version": version}).status_code == 409
