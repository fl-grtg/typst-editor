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


def _content(c, q):
    r = c.get("/api/search/content", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()["entries"]


def _one(entries, kind, **fields):
    rows = [e for e in entries if e["kind"] == kind
            and all(e.get(k) == v for k, v in fields.items())]
    assert len(rows) == 1, entries
    return rows[0]


def test_content_one_char_query(c):
    register_user(c, "alice")
    did = make_doc(c, "Kurz", content="Zebra")
    rows = _content(c, "z")
    assert _one(rows, "doc", doc_id=did)["count"] == 1
    assert _content(c, "☃") == []


def test_content_doc_counts_occurrences(c):
    register_user(c, "alice")
    did = make_doc(c, "Suche", content="Zebra zebra ZEBRA und mehr")
    rows = _content(c, "zebra")
    assert _one(rows, "doc", doc_id=did)["count"] == 3
    assert _content(c, "nichtvorhanden") == []


def test_content_file_counts_text_only(c):
    register_user(c, "alice")
    did = make_doc(c, "Datei", content="ohne Treffer")
    assert c.post(f"/api/docs/{did}/files",
                  files={"f": ("assets/notizen.typ", b"alpha Alpha ALPHA")}).status_code == 200
    assert c.post(f"/api/docs/{did}/files",
                  files={"f": ("assets/bild.png", b"alpha alpha")}).status_code == 200
    rows = _content(c, "alpha")
    assert _one(rows, "file", doc_id=did, name="assets/notizen.typ")["count"] == 3
    assert [e for e in rows if e["kind"] == "file" and e["name"].endswith(".png")] == []


def test_content_project_resource(c):
    register_user(c, "alice")
    pid = c.post("/api/projects", json={"title": "Projekt"}).json()["id"]
    assert c.post(f"/api/projects/{pid}/resources",
                  json={"name": "lib/data.csv", "content": "eins,zwei\neins,drei"}).status_code == 200
    rows = _content(c, "eins")
    assert _one(rows, "resource", project_id=pid, name="lib/data.csv")["count"] == 2


def test_content_template_and_trash(c):
    register_user(c, "alice")
    assert c.post("/api/templates", json={"name": "layout.typ", "content": "Modul Modul"}).status_code == 200
    assert c.delete("/api/templates/layout.typ").status_code == 200
    did = make_doc(c, "Weg", content="Trashwort")
    c.delete(f"/api/docs/{did}")
    rows = _content(c, "modul")
    assert _one(rows, "trash", name="layout.typ")["count"] == 2
    assert [e for e in rows if e["kind"] == "template"] == []
    rows = _content(c, "trashwort")
    assert _one(rows, "trash_doc", doc_id=did)["count"] == 1
    assert [e for e in rows if e["kind"] == "doc"] == []


def test_content_visibility_shared_and_project(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    own = make_doc(c, "Eigen", content="Geheimwort")
    direct = make_doc(c, "Direkt", content="Direktwort")
    c.post(f"/api/docs/{direct}/share", json={"username": "bob", "role": "reviewer"})
    pid = c.post("/api/projects", json={"title": "Team"}).json()["id"]
    project_doc = c.post(f"/api/projects/{pid}/docs",
                         json={"title": "Teamdokument", "content": "Projektwort"}).json()["id"]
    c.post(f"/api/projects/{pid}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    assert [e for e in _content(c, "geheimwort")] == []
    rows = _content(c, "direktwort")
    assert _one(rows, "doc", doc_id=direct)["count"] == 1
    rows = _content(c, "projektwort")
    assert _one(rows, "doc", doc_id=project_doc, project_id=pid)["count"] == 1
    assert [e for e in rows if e["doc_id"] == own] == []


def test_content_after_edit_uses_live_text(c):
    from pycrdt import Text

    from backend import sync as _sync

    register_user(c, "alice")
    did = make_doc(c, "Live", content="alterstand")
    room = _sync.room(did)
    with room["doc"].transaction():
        room["doc"].get("typst", type=Text).__iadd__(" neuerstand")
    room["dirty"] = True
    assert _one(_content(c, "neuerstand"), "doc", doc_id=did)["count"] == 1


def test_content_requires_login(c):
    assert c.get("/api/search/content", params={"q": "x"}).status_code == 401


def test_content_private_entries_stay_private(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    assert c.post("/api/templates", json={"name": "mine.typ", "content": "Privatwort"}).status_code == 200
    gone = make_doc(c, "Weg", content="Privatwort")
    c.delete(f"/api/docs/{gone}")
    shared = make_doc(c, "Geteilt", content="leer")
    assert c.post(f"/api/docs/{shared}/files",
                  files={"f": ("notes.txt", b"Privatwort Privatwort")}).status_code == 200
    c.post(f"/api/docs/{shared}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    rows = _content(c, "privatwort")
    assert [e for e in rows if e["kind"] in ("template", "trash", "trash_doc")] == []
    # attachments of a document that is shared with bob are searchable for bob
    assert _one(rows, "file", doc_id=shared, name="notes.txt")["count"] == 2
    login(c, "alice")
    assert _one(_content(c, "privatwort"), "template", name="mine.typ")["count"] == 1


def test_file_text_rejects_escaping_paths(tmp_path):
    from backend import search

    (tmp_path / "d").mkdir()
    (tmp_path / "secret.txt").write_text("geheim")
    (tmp_path / "d" / "ok.txt").write_text("fein")
    assert search._file_text(tmp_path, "d", "ok.txt") == "fein"
    assert search._file_text(tmp_path, "d", "../secret.txt") is None
    assert search._file_text(tmp_path, "d", "/etc/passwd.txt") is None
    assert search._file_text(tmp_path, "d", "bild.png") is None


def test_content_result_is_capped(c, monkeypatch):
    from backend import search

    monkeypatch.setattr(search, "CONTENT_MAX_ENTRIES", 3)
    register_user(c, "alice")
    for i in range(6):
        make_doc(c, f"Doc {i}", content="kappwort")
    assert len(_content(c, "kappwort")) == 3
