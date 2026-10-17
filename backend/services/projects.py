"""Project membership and path-aware shared libraries."""
from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from backend import db


def role(con: sqlite3.Connection, project_id: str, user: str) -> str:
    p = con.execute("SELECT owner,archived FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p or p["archived"]:
        raise HTTPException(404, "Project not found")
    if p["owner"] == user:
        return "owner"
    m = con.execute("SELECT role FROM project_members WHERE project_id=? AND username=?",
                    (project_id, user)).fetchone()
    if not m:
        raise HTTPException(404, "Project not found")
    return m["role"]


def require(con: sqlite3.Connection, project_id: str, user: str, edit: bool = False,
            owner: bool = False) -> str:
    r = role(con, project_id, user)
    if edit and con.execute("SELECT archived FROM projects WHERE id=?", (project_id,)).fetchone()[0]:
        raise HTTPException(410, "Project is in trash; restore a document first")
    if (owner and r != "owner") or (edit and r not in ("owner", "editor")):
        raise HTTPException(403, "Insufficient project permissions")
    return r


def notify(project_id: str) -> None:
    from backend.services.sidebar import emit_doc, notify_sidebar

    con = db.connect()
    try:
        p = con.execute("SELECT owner,archived FROM projects WHERE id=?", (project_id,)).fetchone()
        users = [r[0] for r in con.execute("SELECT username FROM project_members WHERE project_id=?", (project_id,))]
        docs = [r[0] for r in con.execute("SELECT id FROM docs WHERE project_id=?", (project_id,))]
    finally:
        con.close()
    if p:
        from backend.services.project_history import auto
        auto(project_id)
        for user in [p["owner"], *users]:
            notify_sidebar(user)
        for doc_id in docs:
            emit_doc(doc_id, "file")


def create(con, owner: str, title: str, archived: bool = False) -> str:
    base, suffix = title, 2
    while con.execute("SELECT 1 FROM projects WHERE owner=? AND title=? COLLATE NOCASE", (owner, title)).fetchone():
        tail = f" ({suffix})"
        title = base[:100-len(tail)] + tail
        suffix += 1
    pid = db.new_id("p_")
    con.execute("INSERT INTO projects(id,owner,title,created_at,archived) VALUES (?,?,?,?,?)",
                (pid, owner, title, db.now_iso(), int(archived)))
    return pid


def assert_file_name_free(
    con: sqlite3.Connection, project_id: str, name: str, *,
    exempt_files: set[tuple[str, str]] | None = None,
) -> None:
    """#7: one project must never show two entries with the same name in the
    merged attachment namespace - a name may exist in exactly one sibling
    doc (case-insensitive). Rows the write replaces or frees (upload over
    its own row, rename of its own row) are exempt; routes list them.
    Standalone docs (no project) keep the old account-wide freedom; trash
    restore has its own collision flow. A doc-local file shadowing a module
    of the same name stays legal by design ("local wins")."""
    if not project_id:
        return
    own = sorted(exempt_files or set())
    clauses: list[str] = []
    row_params: list[str] = []
    for doc_id, path in own:
        clauses.append("(f.doc_id = ? AND f.path = ?)")
        row_params.extend((doc_id, path))
    sql = (
        "SELECT 1 FROM files f JOIN docs d ON d.id=f.doc_id"
        " WHERE d.project_id=? AND d.trashed=0 AND f.path=? COLLATE NOCASE"
        + (" AND NOT (" + " OR ".join(clauses) + ")" if clauses else "")
        + " LIMIT 1"
    )
    if con.execute(sql, (project_id, name, *row_params)).fetchone():
        raise HTTPException(409, "Name already exists in this project")


def assert_resource_name_free(
    con: sqlite3.Connection, project_id: str, name: str, *, exempt_name: str = "",
) -> None:
    """#7 resource namespace: the project_modules PK is case-sensitive, so
    'Layout.typ' vs 'layout.typ' would still render two rows. The row being
    renamed/replaced (exempt_name) is free."""
    if not project_id:
        return
    sql = "SELECT 1 FROM project_resources WHERE project_id=? AND name=? COLLATE NOCASE"
    args: list[object] = [project_id, name]
    if exempt_name:
        sql += " AND name <> ?"
        args.append(exempt_name)
    sql += " LIMIT 1"
    if con.execute(sql, args).fetchone():
        raise HTTPException(409, "Name already exists in this project")


def local_texts(doc_id: str) -> dict[str, str]:
    from backend.services import resources
    from backend.services.docfiles import store
    return {e.path: store.get(doc_id, e.path).decode("utf-8", errors="replace")
            for e in store.list(doc_id) if resources.kind_of(e.path)}


def attach_doc(con, doc_id: str, project_id: str | None = None, *, check_quota: bool = True,
               local: dict | None = None) -> str:
    from backend.services import quota, resources
    d = con.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
    if d["project_id"] and not project_id:
        return d["project_id"]
    if d["project_id"] and d["project_id"] != project_id:
        raise HTTPException(409, "Document belongs to another project")
    pid = project_id
    if not pid:
        title = d["folder"].split("/")[0] if d["folder"] else d["title"]
        if d["folder"]:
            row = con.execute("SELECT project_id FROM legacy_project_folders WHERE owner=? AND folder=?",
                              (d["owner"], title)).fetchone()
            pid = row[0] if row else None
        pid = pid or create(con, d["owner"], title, bool(d["trashed"]))
    if d["folder"] and not project_id:
        con.execute("INSERT OR IGNORE INTO legacy_project_folders VALUES (?,?,?)", (d["owner"], d["folder"].split("/")[0], pid))
    local = local_texts(doc_id) if local is None else local
    shelf = {r[0]: r[1] for r in con.execute("SELECT name,content FROM templates WHERE owner=?", (d["owner"],))}
    existing = {r[0]: r[1] for r in con.execute("SELECT name,content FROM project_resources WHERE project_id=?", (pid,))}
    needed = {n: c for n, c in resources.reachable_closure(shelf, local, d["content"]).items() if n not in local}
    added = {n: c for n, c in needed.items() if n not in existing}
    if check_quota:
        quota.check_quota(d["owner"], sum(len(c.encode("utf-8")) for c in added.values()), con)
    # Existing project snapshots remain authoritative over changed private originals.
    con.executemany("INSERT INTO project_resources VALUES (?,?,?,?)",
                    [(pid, n, c, db.now_iso()) for n, c in added.items()])
    folder = d["folder"].partition("/")[2] if not project_id else d["folder"]
    con.execute("UPDATE docs SET project_id=?,folder=? WHERE id=?", (pid, folder, doc_id))
    if not d["trashed"]:
        con.execute("UPDATE projects SET archived=0 WHERE id=?", (pid,))
    return pid


def payload(con, project_id: str, user: str) -> dict:
    from backend.services import resources
    p = con.execute("SELECT * FROM projects WHERE id=? AND archived=0", (project_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Project not found")
    try:
        r = role(con, project_id, user)
    except HTTPException:
        r = "guest"
    docs = [dict(d) for d in con.execute("SELECT id,title,folder,content FROM docs WHERE project_id=? AND trashed=0 ORDER BY folder,title", (project_id,))
            if r != "guest" or db.role_on(con, user, d["id"])]
    if r == "guest" and not docs:
        raise HTTPException(404, "Project not found")
    library = [dict(x) for x in con.execute("SELECT name,content,updated_at FROM project_resources WHERE project_id=? ORDER BY name", (project_id,))]
    if r == "guest":
        shelf = {x["name"]: x["content"] for x in library}
        allowed: set[str] = set()
        for d in docs:
            local = local_texts(d["id"])
            allowed.update(n for n in resources.reachable_closure(shelf, local, d["content"]) if n not in local)
        library = [x for x in library if x["name"] in allowed]
    files: list[dict] = []
    for d in docs:
        files.extend(dict(x) for x in con.execute("SELECT doc_id,path AS name,size FROM files WHERE doc_id=? ORDER BY path", (d["id"],)))
        d.pop("content")
        d["role"] = db.role_on(con, user, d["id"])
    return {**dict(p), "role": r, "can_edit_library": r in ("owner", "editor"),
            "documents": docs, "resources": [{"name": x["name"], "updated_at": x["updated_at"]} for x in library],
            "files": files}
