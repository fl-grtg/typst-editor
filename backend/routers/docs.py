"""Document and folder routes."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile

from backend import config, db, deps, search, sync
from backend.constants import FOLDER_MAX, MAX_TXT, TITLE_MAX, UPLOAD_MAX
from backend.schemas import DocCreate, DocSave, FolderRename, FolderSet, TitleSet
from backend.services import projects
from backend.services import quota as quota_svc
from backend.services.docfiles import file_type, store, sync_doc_files
from backend.services.locks import _drop_doc_locks, _named_lock
from backend.services.sidebar import doc_users, notify_sidebar
from backend.services.snapshots import auto_snap

log = logging.getLogger("typst.main")

router = APIRouter()


@router.get("/api/docs")
def list_docs(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "sidebar")
    con = db.connect()
    try:
        own = con.execute("SELECT id, title, folder, project_id, updated_at FROM docs WHERE owner=? AND trashed=0 "
                          "ORDER BY updated_at DESC", (user,)).fetchall()
        shared = con.execute(
            "SELECT d.id,d.title,d.owner,d.folder,d.project_id,d.updated_at,COALESCE(m.role,s.role) AS role FROM docs d "
            "LEFT JOIN shares s ON s.doc_id=d.id AND s.username=? "
            "LEFT JOIN project_members m ON m.project_id=d.project_id AND m.username=? "
            "WHERE (s.username IS NOT NULL OR m.username IS NOT NULL) AND d.owner<>? AND d.trashed=0 ORDER BY d.updated_at DESC", (user,user,user)).fetchall()
        trash = con.execute("SELECT id, title, updated_at FROM docs WHERE owner=? AND trashed=1 "
                            "ORDER BY updated_at DESC", (user,)).fetchall()
        trash_items = con.execute("SELECT id,name AS title,created_at AS updated_at,kind,project_id,doc_id FROM trash_entries WHERE owner=? ORDER BY created_at DESC", (user,)).fetchall()
        return {"own": [dict(r) for r in own],
                "shared": [dict(r) for r in shared],
                "trash": [dict(r) for r in trash] + [dict(r) for r in trash_items]}
    finally:
        con.close()


@router.get("/api/folders")
def list_folders(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        return {"folders": deps._folder_counts(con, user, "doc")}
    finally:
        con.close()


@router.post("/api/folders")
def make_folder(b: FolderSet, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "folders")
    with db.tx() as con:
        title = deps.check_folder_name(b.folder).split("/")[0]
        row = con.execute("SELECT project_id FROM legacy_project_folders WHERE owner=? AND folder=?", (user, title)).fetchone()
        pid = row[0] if row else projects.create(con, user, title)
        con.execute("INSERT OR IGNORE INTO legacy_project_folders VALUES (?,?,?)", (user, title, pid))
    notify_sidebar(user)
    return {"id": pid, "project_id": pid, "folder": title}


@router.post("/api/docs/create")
def create_doc(b: DocCreate, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "create")
    t = b.title.strip()
    if not t or len(t) > TITLE_MAX:
        raise HTTPException(400, f"Title: 1-{TITLE_MAX} chars")
    if len(b.content.encode("utf-8")) > MAX_TXT:
        raise HTTPException(400, "Doc too large (max 200 KB)")
    try:
        deps.check_quota(user, len(b.content.encode("utf-8")))
    except sqlite3.OperationalError as e:
        raise deps.busy_503("create_doc", e) from e
    try:
        max_docs = config.load().MAX_DOCS_PER_USER
    except Exception:
        max_docs = 100
    did, now = db.new_id("d_"), db.now_iso()
    try:
        with db.tx() as con:
            if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?", (user,)).fetchone()["n"] >= max_docs:
                raise HTTPException(400, "Too many docs")
            con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (did, user, t, b.content,
                         b.folder.strip()[:FOLDER_MAX], now, now))
            projects.attach_doc(con, did)
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, "Title already exists") from e
    except sqlite3.OperationalError as e:
        raise deps.busy_503("create_doc", e) from e
    from backend.services.project_history import auto_document
    auto_document(did)
    quota_svc.invalidate_quota_cache(user)
    notify_sidebar(user)
    return {"id": did}



@router.post("/api/docs/import-zip")
def import_zip(req: Request, f: UploadFile, title: str = Form(...), folder: str = Form(""), user: str = Depends(deps.me)) -> dict:
    from backend.services.projectzip import import_project_zip

    deps.limited(req, "create")
    return import_project_zip(user, title, folder, f.file.read(UPLOAD_MAX + 1))


@router.get("/api/docs/{doc_id}")
def get_doc(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    r = deps.need_access(user, doc_id)
    con = db.connect()
    try:
        d = con.execute("SELECT id, owner, title, content, folder, project_id, trashed, updated_at FROM docs WHERE id=?",
                        (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "Doc gone")
        users = con.execute("SELECT username, role FROM shares WHERE doc_id=?", (doc_id,)).fetchall()
        return {**dict(d), "role": r, "shares": [dict(u) for u in users]}
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/save")
async def save_doc(doc_id: str, b: DocSave, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "save")
    deps.need_edit(user, doc_id)
    live = sync.room_text(doc_id)
    if live is not None and live != b.content and not b.force:
        raise HTTPException(409, "Newer live-room state - save with force")
    content = b.content if (live is None or b.force) else live
    if len(content.encode("utf-8")) > MAX_TXT:
        raise HTTPException(400, "Doc too large (max 200 KB)")
    try:
        _c = db.connect()
        try:
            _old = _c.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        finally:
            _c.close()
    except sqlite3.OperationalError as e:
        raise deps.busy_503("save_doc", e) from e
    _old_text = (_old["content"] or "") if _old else ""
    _old_len = len(_old_text.encode("utf-8"))
    _save_owner = deps._owner(doc_id, user)

    def _restore_old() -> None:
        _rb = db.connect()
        try:
            _rb.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                        (_old_text, db.now_iso(), doc_id))
            _rb.commit()
        finally:
            _rb.close()

    try:
        with quota_svc.quota_guard(_save_owner, max(0, len(content.encode("utf-8")) - _old_len),
                                   rollback=_restore_old):
            try:
                with db.tx() as con:
                    trashed = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
                    if not trashed:
                        raise HTTPException(404, "Doc gone")
                    if trashed["trashed"]:
                        raise HTTPException(410, "In trash - restore first")
                    # B5: pre-tx need_edit is a fast-path only; the role must
                    # hold on THIS connection (unshare/downgrade may land in
                    # the gap between check and BEGIN IMMEDIATE).
                    if deps._tx_role(con, user, doc_id) not in ("owner", "editor"):
                        raise HTTPException(403, "Reviewer can only comment")
                    con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                                (content, db.now_iso(), doc_id))
            except sqlite3.OperationalError as e:
                raise deps.busy_503("save_doc", e) from e
    except sqlite3.OperationalError as e:
        raise deps.busy_503("save_doc", e) from e
    except HTTPException as e:
        if e.status_code == 413 and live is not None:
            await sync.replace_text(doc_id, _old_text)
        raise
    if b.force:
        await sync.replace_text(doc_id, content)
    elif live is None:
        if not sync.persist(doc_id):
            db.clear_room_state(doc_id)
    else:
        sync.persist(doc_id)
    try:
        auto_snap(doc_id, content)
    except HTTPException as e:
        log.warning("save_doc snap: %s", e.detail)
    return {"ok": True}


@router.post("/api/docs/{doc_id}/rename")
def rename_doc(doc_id: str, b: TitleSet, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "rename")
    t = b.title.strip()
    if not t or len(t) > TITLE_MAX:
        raise HTTPException(400, f"Title: 1-{TITLE_MAX} chars")
    try:
        with db.tx() as con:
            if deps._tx_role(con, user, doc_id) not in ("owner", "editor"):
                raise HTTPException(403, "Only project editors can rename")
            row = con.execute("SELECT project_id,trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Doc gone")
            if row["trashed"]:
                raise HTTPException(410, "In trash - restore first")
            if row["project_id"]:
                projects.require(con, row["project_id"], user, edit=True)
            con.execute("UPDATE docs SET title=?, updated_at=? WHERE id=?", (t, db.now_iso(), doc_id))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Title already exists") from None
    for recipient in doc_users(doc_id):
        notify_sidebar(recipient)
    return {"ok": True}


@router.delete("/api/docs/{doc_id}")
async def delete_doc(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    return await _delete_doc(doc_id, req, user)


@router.post("/api/docs/{doc_id}/trash")
async def trash_doc(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    return await _delete_doc(doc_id, req, user, trash_only=True)


async def _delete_doc(doc_id: str, req: Request, user: str, trash_only: bool = False) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "delete")
    deps.need_access(user, doc_id, allow_trashed=True)
    audience = doc_users(doc_id)
    with db.tx() as con:
        row = con.execute("SELECT trashed,project_id,owner FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Doc gone")
        role = db.role_on(con, user, doc_id)
        if not role:
            raise HTTPException(404, "Doc gone")
        if role not in ("owner", "editor"):
            raise HTTPException(403, "Only editors can delete")
        trashed = bool(row["trashed"])
        if role != "owner":
            if (trashed and not trash_only) or not row["project_id"]:
                raise HTTPException(403, "Only owner can permanently delete")
            projects.require(con, row["project_id"], user, edit=True)
        if trashed and trash_only:
            return {"trashed": True}
        if not trashed:
            con.execute("UPDATE docs SET trashed=1,updated_at=? WHERE id=?", (db.now_iso(), doc_id))
        else:
            # Permanent delete: files/comments go with the doc (FK
            # cascade), but trash_entries references docs only by id —
            # purge its copies, otherwise every restore attempt dead-ends
            # on "Restore the original document first".
            con.execute("DELETE FROM docs WHERE id=?", (doc_id,))
            con.execute("DELETE FROM trash_entries WHERE doc_id=?", (doc_id,))
            if row["project_id"]:
                con.execute("DELETE FROM projects WHERE id=? AND archived=1 AND NOT EXISTS (SELECT 1 FROM docs WHERE project_id=?)",
                            (row["project_id"], row["project_id"]))
    await sync.drop(doc_id)
    quota_svc.invalidate_quota_cache(row["owner"])
    _drop_doc_locks(doc_id)
    for recipient in audience:
        notify_sidebar(recipient)
    if trashed:
        try:
            shutil.rmtree(deps.get_files_dir() / doc_id, ignore_errors=True)
        except OSError:
            log.warning("delete_doc %s: rmtree failed", doc_id)
    return {"trashed": not trashed}


@router.post("/api/docs/{doc_id}/restore")
def restore_doc(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "restore")
    deps.need_access(user, doc_id, allow_trashed=True)
    try:
        with db.tx() as con:
            cur = con.execute("SELECT folder,project_id,owner FROM docs WHERE id=?", (doc_id,)).fetchone()
            if cur is None:
                raise HTTPException(404, "Doc gone")
            if cur["owner"] != user:
                raise HTTPException(403, "Only owner can restore")
            fld = cur["folder"] or ""
            if fld and not cur["project_id"] and not con.execute("SELECT 1 FROM folders WHERE owner=? AND kind='doc' AND name=?", (user, fld)).fetchone():
                fld = ""
            if cur["project_id"]:
                con.execute("UPDATE projects SET archived=0 WHERE id=?", (cur["project_id"],))
            con.execute("UPDATE docs SET trashed=0,folder=?,updated_at=? WHERE id=?", (fld, db.now_iso(), doc_id))
    except sqlite3.IntegrityError as e:
        raise HTTPException(409, "Name already exists in this project; rename the existing document before restoring") from e
    for recipient in doc_users(doc_id):
        notify_sidebar(recipient)
    return {"ok": True}


@router.post("/api/docs/{doc_id}/folder")
def move_doc(doc_id: str, b: FolderSet, req: Request, user: str = Depends(deps.me)) -> dict:
    raise HTTPException(410, "Document folders were replaced by projects")


@router.delete("/api/folders/{name}")
def drop_folder(name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    raise HTTPException(410, "Document folders were replaced by projects")


@router.post("/api/folders/rename")
def rename_folder(b: FolderRename, req: Request, user: str = Depends(deps.me)) -> dict:
    raise HTTPException(410, "Document folders were replaced by projects")


@router.post("/api/docs/{doc_id}/duplicate")
def duplicate_doc(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "duplicate")
    deps.need_edit(user, doc_id)
    try:
        max_docs = config.load().MAX_DOCS_PER_USER
    except Exception:
        max_docs = 100
    nid, now = db.new_id("d_"), db.now_iso()
    src = deps.get_files_dir() / doc_id
    with _named_lock(f"dup:{user}"):
        try:
            with db.tx() as con:
                # B5: outer need_edit is a fast-path only; re-check on the tx
                # connection before inserting (role may change in the gap).
                if deps._tx_role(con, user, doc_id) not in ("owner", "editor"):
                    raise HTTPException(403, "Reviewer can only comment")
                d = con.execute("SELECT title, content, folder, trashed, owner, project_id FROM docs WHERE id=?",
                                (doc_id,)).fetchone()
                if not d:
                    raise HTTPException(404, "Doc gone")
                if d["trashed"]:
                    raise HTTPException(410, "In trash - restore first")
                target_owner = user
                guest_copy = not d["project_id"] and d["owner"] != user
                if d["project_id"]:
                    try:
                        projects.require(con, d["project_id"], user, edit=True)
                        target_owner = d["owner"]
                    except HTTPException as e:
                        if e.status_code != 404:
                            raise
                        guest_copy = True
                if con.execute("SELECT COUNT(*) FROM docs WHERE owner=?", (target_owner,)).fetchone()[0] >= max_docs:
                    raise HTTPException(400, "Too many docs")
                base = d["title"] + " (copy)"
                title, i = base, 2
                pid = d["project_id"]
                while True:
                    if pid is None:
                        dup = con.execute("SELECT 1 FROM docs WHERE owner=? AND project_id IS NULL AND title=? COLLATE NOCASE AND trashed=0",
                                          (target_owner, title)).fetchone()
                    else:
                        dup = con.execute("SELECT 1 FROM docs WHERE project_id=? AND title=? COLLATE NOCASE AND trashed=0",
                                          (pid, title)).fetchone()
                    if not dup:
                        break
                    title, i = f"{base} {i}", i + 1
                    if i > 99:
                        raise HTTPException(400, "Too many copies")
                live = sync.room_text(doc_id)
                text = live if live is not None else d["content"]
                try:
                    max_files = config.load().MAX_FILES_PER_DOC
                except Exception:
                    max_files = 200
                try:
                    # Recursive live count (subpaths included), same filter
                    # as sync_doc_files: hidden/tmp entries never counted.
                    # Symlink targets count here, like _tree_count for the
                    # sibling writers (fail-closed vs the table, which never
                    # holds links). store.list only guards OSError, hence
                    # ValueError is caught here as well.
                    entries = store.list(doc_id)
                except (OSError, ValueError):
                    entries = []
                if len(entries) > max_files:
                    raise HTTPException(400, "Too many files")
                fbytes = sum(e.size for e in entries)
                quota_svc.check_quota(target_owner, len(text.encode("utf-8")) + fbytes, con)
                source_project = d["project_id"]
                new_project = guest_copy or not source_project
                if new_project:
                    from backend.services import resources
                    if source_project:
                        shelf = {r[0]: r[1] for r in con.execute("SELECT name,content FROM project_resources WHERE project_id=?", (source_project,))}
                    else:
                        shelf = {r[0]: r[1] for r in con.execute("SELECT name,content FROM templates WHERE owner=?", (d['owner'],))}
                    local = projects.local_texts(doc_id)
                    copied = {n: c for n, c in resources.reachable_closure(shelf, local, text).items() if n not in local}
                    quota_svc.check_quota(target_owner, len(text.encode("utf-8")) + fbytes + sum(len(c.encode("utf-8")) for c in copied.values()), con)
                    source_project = projects.create(con, target_owner, title)
                    con.executemany("INSERT INTO project_resources VALUES (?,?,?,?)", [(source_project, n, c, now) for n, c in copied.items()])
                con.execute("INSERT INTO docs (id, owner, title, content, folder, project_id, created_at, updated_at) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (nid, target_owner, title, text, d["folder"], source_project, now, now))
                # Account for attachments with the doc row, even if the later
                # disk reconciliation hits a transient database lock.
                con.executemany("INSERT INTO files (doc_id, path, size, mtime, type) VALUES (?,?,?,?,?)",
                                [(nid, e.path, e.size, e.mtime, file_type(e.path)) for e in entries])
        except sqlite3.IntegrityError as e:
            raise HTTPException(400, "Title already exists") from e
        except sqlite3.OperationalError as e:
            raise deps.busy_503("duplicate_doc", e) from e
    # B9: publish the file tree atomically. copytree straight into the final
    # dir leaves a partial tree visible on crash/failure (and dirs_exist_ok
    # would merge into a pre-existing dir); stage into a hidden tmp sibling
    # (skipped by every files walk via the ".tmp." rule, never quota-counted)
    # and publish with one atomic os.replace.
    if src.is_dir():
        dst = deps.get_files_dir() / nid
        tmpd = deps.get_files_dir() / f".tmp.dup-{nid}"

        def _drop_tmp() -> None:
            # rmtree is a no-op on a file; unlink it instead (practically
            # unreachable with random nids, but cleanup must be total).
            try:
                if tmpd.is_dir() and not tmpd.is_symlink():
                    shutil.rmtree(tmpd, ignore_errors=True)
                else:
                    tmpd.unlink(missing_ok=True)
            except OSError:
                pass

        try:
            if dst.exists():
                raise OSError(f"duplicate target exists: {nid}")
            _drop_tmp()
            shutil.copytree(src, tmpd, ignore=shutil.ignore_patterns(".*", "*.tmp.*"))
            os.replace(tmpd, dst)
        except (OSError, shutil.Error) as e:
            log.warning("duplicate %s -> %s: copy failed: %s", doc_id, nid, e)
            _drop_tmp()
            _rb = db.connect()
            try:
                _rb.execute("DELETE FROM docs WHERE id=?", (nid,))
                if new_project:
                    _rb.execute("DELETE FROM projects WHERE id=? AND NOT EXISTS (SELECT 1 FROM docs WHERE project_id=?)", (source_project, source_project))
                _rb.commit()
                quota_svc.invalidate_quota_cache(target_owner)
            except Exception as e:
                log.warning("duplicate rollback %s failed: %s", nid, e)
            finally:
                _rb.close()
            raise HTTPException(500, "Copy failed") from None
    # Files-table rows for the copied tree (quota/search read the table,
    # never the filesystem). Best-effort: the doc + tree are committed, so
    # even a transient lock must not turn success into a 503 (a failed
    # request would read as "retry" and mint a second copy; the next
    # list_files heals via sync_doc_files anyway).
    try:
        sync_doc_files(nid)
    except HTTPException as e:
        log.warning("duplicate files sync %s failed: %s", nid, e)
    # G4: the copy is committed (doc row + tree + files rows) before the
    # quota verdict is final: a concurrent writer may have filled the quota
    # in the gap since the pre-check. Re-check now and roll the copy back
    # (row via FK-cascade incl. files rows, plus the tree) when over quota,
    # so no orphan doc survives. quota_guard cannot do this: its pre-check
    # raises without rollback once the copy is already counted, hence the
    # explicit post-commit verdict with the same rollback pattern as the
    # other writers (docfiles quota_guard callers). A transient lock anywhere
    # leaves the copy in place (fail-open: the next write re-checks). The
    # Attachment rows were inserted with the doc, so a reconciliation failure
    # still leaves the copied bytes accounted for.
    try:
        _over = quota_svc.is_over_quota(target_owner)
    except sqlite3.Error as e:
        log.warning("duplicate quota post-check %s inconclusive: %s", nid, e)
        _over = False
    if _over:
        try:
            # db.tx gates the rest: deleting the tree while the row survives
            # (transient lock on the DELETE) would orphan exactly the doc
            # this guards against, so a stuck row keeps the copy (fail-open).
            with db.tx() as _con:
                _con.execute("DELETE FROM docs WHERE id=?", (nid,))
                if new_project:
                    _con.execute("DELETE FROM projects WHERE id=? AND NOT EXISTS (SELECT 1 FROM docs WHERE project_id=?)", (source_project, source_project))
        except sqlite3.OperationalError as e:
            log.warning("duplicate quota rollback %s failed: %s", nid, e)
        else:
            try:
                _dst = deps.get_files_dir() / nid
                if _dst.is_dir() and not _dst.is_symlink():
                    shutil.rmtree(_dst, ignore_errors=True)
                else:
                    _dst.unlink(missing_ok=True)
            except OSError:
                pass
            quota_svc.invalidate_quota_cache(target_owner)
            raise HTTPException(413, "Quota exceeded")
    quota_svc.invalidate_quota_cache(target_owner)
    if d["project_id"]:
        projects.notify(d["project_id"])
    else:
        notify_sidebar(user)
    return {"id": nid}


@router.get("/api/search")
def search_docs(req: Request, q: str = "", user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "search")
    con = db.connect()
    try:
        rows = search.search_visible(user, q, con, deps.get_files_dir(), sync.room_text)
    finally:
        con.close()
    return {"hits": [{k: h[k] for k in ("id", "title", "owner", "snippet", "pos")} for h in rows]}


@router.post("/api/trash/{entry_id}/restore")
def restore_trash_entry(entry_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services import trash

    deps.limited(req, "restore")
    return trash.restore(user, entry_id)


@router.delete("/api/trash/{entry_id}")
def delete_trash_entry(entry_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services.locks import _named_lock

    deps.limited(req, "delete")
    with _named_lock("trash:" + entry_id):
        with db.tx() as con:
            row = con.execute("SELECT project_id,doc_id FROM trash_entries WHERE id=? AND owner=?",
                              (entry_id, user)).fetchone()
            if not row:
                raise HTTPException(404, "Trash entry gone")
            con.execute("DELETE FROM trash_entries WHERE id=?", (entry_id,))
    quota_svc.invalidate_quota_cache(user)
    notify_sidebar(user)
    if row["project_id"]:
        projects.notify(row["project_id"])
    if row["doc_id"]:
        from backend.services.sidebar import emit_doc
        emit_doc(row["doc_id"], "file")
    return {"ok": True}
