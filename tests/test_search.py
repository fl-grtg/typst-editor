from conftest import login, make_doc, register_user


def test_short_query_empty(c):
    register_user(c, "alice")
    assert c.get("/api/search", params={"q": "x"}).json() == {"hits": []}


def test_hit_found(c):
    register_user(c, "alice")
    did = make_doc(c, "Suche", content="Zebrafruechte sind lecker")
    hits = c.get("/api/search", params={"q": "zebrafr"}).json()["hits"]
    assert [h["id"] for h in hits] == [did]


def test_no_foreign_hits(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    make_doc(c, "Geheim", content="Quastenflosser schwimmt")
    login(c, "bob")
    assert c.get("/api/search", params={"q": "quasten"}).json()["hits"] == []


def test_no_trashed_hits(c):
    register_user(c, "alice")
    did = make_doc(c, "Weg", content="Marmeladenglasdeckel")
    c.delete(f"/api/docs/{did}")
    assert c.get("/api/search", params={"q": "marmelade"}).json()["hits"] == []
