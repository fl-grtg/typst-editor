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


def test_query_truncated_50(c):
    register_user(c, "alice")
    prefix = "q" * 50
    make_doc(c, "Lang", content=prefix + " extra")
    long_q = prefix + "ZZZ_nicht_im_doc_12345"
    assert len(long_q) > 50
    hits = c.get("/api/search", params={"q": long_q}).json()["hits"]
    assert [h["title"] for h in hits] == ["Lang"]


def test_shared_visible(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Geteilt", content="GemeinsamXYZ123 geheim")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    hits = c.get("/api/search", params={"q": "gemeinsamxyz"}).json()["hits"]
    assert [h["id"] for h in hits] == [did]


def test_fts_table_and_triggers(c):
    from backend import db as _db

    register_user(c, "alice")
    con = _db.connect()
    try:
        kind = con.execute(
            "SELECT sql FROM sqlite_master WHERE name='docs_fts'").fetchone()
        assert kind and "using fts5" in kind["sql"].lower()
        trigs = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'docs_fts_%'").fetchall()}
        assert trigs == {"docs_fts_ai", "docs_fts_ad", "docs_fts_au"}
    finally:
        con.close()


def test_fts_updates_on_edit(c):
    register_user(c, "alice")
    did = make_doc(c, "FTS", content="Ananas Kompott")
    assert c.get("/api/search", params={"q": "ananas"}).json()["hits"]
    assert c.post(f"/api/docs/{did}/save",
                  json={"content": "Birnen Kompott"}).status_code == 200
    assert c.get("/api/search", params={"q": "ananas"}).json()["hits"] == []
    hits = c.get("/api/search", params={"q": "birnen"}).json()["hits"]
    assert [h["id"] for h in hits] == [did]


def test_snippet_from_fts(c):
    register_user(c, "alice")
    make_doc(c, "Schnipsel", content="Vorsatz Augenbrauenstift Nachsatz")
    hits = c.get("/api/search", params={"q": "augenbrauen"}).json()["hits"]
    assert len(hits) == 1
    assert "augenbrauen" in hits[0]["snippet"].lower()
    assert hits[0]["pos"] >= 0


def test_search_filename(c):
    register_user(c, "alice")
    did = make_doc(c, "Dateisuche", content="ganz normaler Inhalt")
    assert c.post(f"/api/docs/{did}/files",
                  files={"f": ("literaturverzeichnis.bib",
                                b"@book{AnderesWerk, author={X}}")}).status_code == 200
    hits = c.get("/api/search", params={"q": "literaturverz"}).json()["hits"]
    assert [h["id"] for h in hits] == [did]
    assert "literaturverzeichnis.bib" in hits[0]["snippet"]


def test_search_bib_key(c):
    register_user(c, "alice")
    did = make_doc(c, "Bibsuche", content="ganz normaler Inhalt")
    assert c.post(f"/api/docs/{did}/files",
                  files={"f": ("refs.bib",
                                b"@article{Mueller2024quantenphysik, author={M}}")}).status_code == 200
    hits = c.get("/api/search", params={"q": "mueller2024quanten"}).json()["hits"]
    assert [h["id"] for h in hits] == [did]
    assert "mueller2024quantenphysik" in hits[0]["snippet"].lower()


def test_search_live_room_preferred(c):
    from pycrdt import Text

    from backend import sync as _sync

    register_user(c, "alice")
    did = make_doc(c, "Live", content="persistierter Basisinhalt")
    room = _sync.room(did)
    with room["doc"].transaction():
        room["doc"].get("typst", type=Text).__iadd__(" liveeinmalwort")
    room["dirty"] = True
    hits = c.get("/api/search", params={"q": "liveeinmalwort"}).json()["hits"]
    assert [h["id"] for h in hits] == [did]
    assert "liveeinmalwort" in hits[0]["snippet"].lower()

