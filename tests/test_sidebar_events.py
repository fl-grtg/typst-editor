"""Sidebar live refresh: /api/events pushes on list mutations."""
import asyncio

import pytest
from conftest import login, make_doc, register_user

import backend.main as main


def _watch(user):
    entry = (asyncio.get_running_loop(), asyncio.Queue())
    main._SIDEBAR_Q.setdefault(user, set()).add(entry)
    return entry


@pytest.mark.anyio
async def test_notify_on_create(c):
    register_user(c, "u1")
    entry = _watch("u1")
    try:
        r = c.post("/api/docs/create", json={"title": "N", "content": "x"})
        assert r.status_code == 200, r.text
        assert await asyncio.wait_for(entry[1].get(), timeout=5) == "sidebar"
    finally:
        main._SIDEBAR_Q.get("u1", set()).discard(entry)


@pytest.mark.anyio
async def test_notify_on_delete_restore(c):
    register_user(c, "uD")
    did = make_doc(c, title="Gone")
    entry = _watch("uD")
    try:
        assert c.delete(f"/api/docs/{did}").status_code == 200
        assert await asyncio.wait_for(entry[1].get(), timeout=5) == "sidebar"
        assert c.post(f"/api/docs/{did}/restore").status_code == 200
        assert await asyncio.wait_for(entry[1].get(), timeout=5) == "sidebar"
    finally:
        main._SIDEBAR_Q.get("uD", set()).discard(entry)


@pytest.mark.anyio
async def test_notify_on_mutations(c):
    register_user(c, "uM")
    did = make_doc(c, title="Mut")
    entry = _watch("uM")

    async def _one(call):
        r = call()
        assert r.status_code == 200, r.text
        assert await asyncio.wait_for(entry[1].get(), timeout=5) == "sidebar"

    try:
        await _one(lambda: c.post(f"/api/docs/{did}/rename", json={"title": "Mut2"}))
        await _one(lambda: c.post(f"/api/docs/{did}/folder", json={"folder": "F"}))
        await _one(lambda: c.post(f"/api/docs/{did}/duplicate"))
        await _one(lambda: c.post("/api/folders", json={"folder": "G"}))
        await _one(lambda: c.post("/api/templates", json={"name": "t.typ", "content": "x"}))
    finally:
        main._SIDEBAR_Q.get("uM", set()).discard(entry)


@pytest.mark.anyio
async def test_cross_user_isolation(c):
    register_user(c, "uA")
    register_user(c, "uB")  # now acting as uB
    ea, eb = _watch("uA"), _watch("uB")
    try:
        r = c.post("/api/docs/create", json={"title": "B-doc", "content": "x"})
        assert r.status_code == 200, r.text
        assert await asyncio.wait_for(eb[1].get(), timeout=5) == "sidebar"
        await asyncio.sleep(0.2)  # grace: a late stray event must still fail this
        assert ea[1].empty(), "uA got uB's event"
    finally:
        main._SIDEBAR_Q.get("uA", set()).discard(ea)
        main._SIDEBAR_Q.get("uB", set()).discard(eb)


@pytest.mark.anyio
async def test_notify_sharee(c):
    register_user(c, "owner")
    did = make_doc(c, title="Shared")
    register_user(c, "guest")
    entry = _watch("guest")
    try:
        login(c, "owner")
        r = c.post(f"/api/docs/{did}/share", json={"username": "guest", "role": "reviewer"})
        assert r.status_code == 200, r.text
        assert await asyncio.wait_for(entry[1].get(), timeout=5) == "sidebar"
    finally:
        main._SIDEBAR_Q.get("guest", set()).discard(entry)


def test_events_route_beats_fallback():
    paths = [r.path for r in main.app.routes]
    assert "/api/events" in paths
    assert paths.index("/api/events") < paths.index("/api/{full_path:path}")


def test_events_unauthed(c):
    c.post("/api/logout")
    assert c.get("/api/events").status_code == 401
