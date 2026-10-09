"""Document and folder routes."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from backend import config, db, deps, search, sync
from backend.constants import FOLDER_MAX, MAX_TXT, TITLE_MAX
from backend.schemas import DocCreate, DocSave, FolderRename, FolderSet, TitleSet
from backend.services import quota as quota_svc
from backend.services.docfiles import store, sync_doc_files
from backend.services.locks import _drop_doc_locks, _named_lock
from backend.services.sidebar import notify_sidebar
from backend.services.snapshots import auto_snap

log = logging.getLogger("typst.main")

router = APIRouter()


@router.get("/api/docs")
def list_docs(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        own = con.execute("SELECT id, title, folder, updated_at FROM docs WHERE owner=? AND trashed=0 "
                          "ORDER BY updated_at DESC", (user,)).fetchall()
        shared = con.execute(
            "SELECT d.id, d.title, d.owner, d.updated_at, s.role FROM docs d JOIN shares s ON s.doc_id=d.id "
            "WHERE s.username=? AND d.trashed=0 ORDER BY d.updated_at DESC", (user,)).fetchall()
        trash = con.execute("SELECT id, title, updated_at FROM docs WHERE owner=? AND trashed=1 "
                            "ORDER BY updated_at DESC", (user,)).fetchall()
        return {"own": [dict(r) for r in own],
                "shared": [dict(r) for r in shared],
                "trash": [dict(r) for r in trash]}
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
    n = deps.check_folder_name(b.folder)
    con = db.connect()
    try:
        deps.ensure_folder(con, user, "doc", n)
        con.commit()
        notify_sidebar(user)
        return {"folder": n}
    finally:
        con.close()


@router.post("/api/docs/create")
def create_doc(b: DocCreate, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "create")
    t = b.title.strip()
    if not t or len(t) > TITLE_MAX:
        raise HTTPException(400, f"Title: 1-{TITLE_MAX} chars")
    if len(b.content) > MAX_TXT:
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
            deps.ensure_folder(con, user, "doc", b.folder)
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, "Title already exists") from e
    except sqlite3.OperationalError as e:
        raise deps.busy_503("create_doc", e) from e
    notify_sidebar(user)
    return {"id": did}


@router.get("/api/docs/{doc_id}")
def get_doc(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    r = deps.need_access(user, doc_id)
    con = db.connect()
    try:
        d = con.execute("SELECT id, owner, title, content, folder, trashed, updated_at FROM docs WHERE id=?",
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
    if len(content) > MAX_TXT:
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
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can rename")
    t = b.title.strip()
    if not t or len(t) > TITLE_MAX:
        raise HTTPException(400, f"Title: 1-{TITLE_MAX} chars")
    con = db.connect()
    try:
        con.execute("UPDATE docs SET title=?, updated_at=? WHERE id=?", (t, db.now_iso(), doc_id))
        con.commit()
        notify_sidebar(user)
        return {"ok": True}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Title already exists") from None
    finally:
        con.close()


@router.delete("/api/docs/{doc_id}")
async def delete_doc(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "delete")
    r = deps.need_access(user, doc_id, allow_trashed=True)
    if r != "owner":
        raise HTTPException(403, "Only owner can delete")
    con = db.connect()
    try:
        row = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Doc gone")
        trashed = row["trashed"]
        if not trashed:
            con.execute("UPDATE docs SET trashed=1, updated_at=? WHERE id=?", (db.now_iso(), doc_id))
            con.commit()
            await sync.drop(doc_id)
            _drop_doc_locks(doc_id)
            notify_sidebar(user)
            return {"trashed": True}
        con.execute("DELETE FROM docs WHERE id=?", (doc_id,))
        con.commit()
    finally:
        con.close()
    await sync.drop(doc_id)
    _drop_doc_locks(doc_id)
    notify_sidebar(user)
    try:
        shutil.rmtree(deps.get_files_dir() / doc_id, ignore_errors=True)
    except OSError:
        log.warning("delete_doc %s: rmtree failed", doc_id)
    return {"trashed": False}


@router.post("/api/docs/{doc_id}/restore")
def restore_doc(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "restore")
    if deps.need_access(user, doc_id, allow_trashed=True) != "owner":
        raise HTTPException(403, "Only owner can restore")
    con = db.connect()
    try:
        cur = con.execute("SELECT folder FROM docs WHERE id=?", (doc_id,)).fetchone()
        if cur is None:
            raise HTTPException(404, "Doc gone")
        fld = cur["folder"] if cur and cur["folder"] else ""
        if fld and not con.execute("SELECT 1 FROM folders WHERE owner=? AND kind='doc' AND name=?",
                                   (user, fld)).fetchone():
            fld = ""
        con.execute("UPDATE docs SET trashed=0, folder=?, updated_at=? WHERE id=?", (fld, db.now_iso(), doc_id))
        con.commit()
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/folder")
def move_doc(doc_id: str, b: FolderSet, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "move")
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can move")
    if len(b.folder.strip()) > FOLDER_MAX:
        raise HTTPException(400, "Folder name too long")
    con = db.connect()
    try:
        con.execute("UPDATE docs SET folder=?, updated_at=? WHERE id=?",
                    (b.folder.strip()[:FOLDER_MAX], db.now_iso(), doc_id))
        deps.ensure_folder(con, user, "doc", b.folder)
        con.commit()
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@router.delete("/api/folders/{name}")
def drop_folder(name: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "folders")
    n = name.strip()[:FOLDER_MAX]
    con = db.connect()
    try:
        con.execute("UPDATE docs SET folder='' WHERE owner=? AND folder=? AND trashed=0", (user, n))
        con.execute("DELETE FROM folders WHERE owner=? AND kind='doc' AND name=?", (user, n))
        con.commit()
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@router.post("/api/folders/rename")
def rename_folder(b: FolderRename, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "folders")
    if len(b.old.strip()) > FOLDER_MAX or len(b.new.strip()) > FOLDER_MAX:
        raise HTTPException(400, "Folder name too long")
    old, new = b.old.strip()[:FOLDER_MAX], b.new.strip()[:FOLDER_MAX]
    if not old or not new or old == new:
        raise HTTPException(400, "Empty folder name")
    con = db.connect()
    try:
        con.execute("UPDATE docs SET folder=?, updated_at=? WHERE owner=? AND folder=? AND trashed=0",
                    (new, db.now_iso(), user, old))
        con.execute("UPDATE OR IGNORE folders SET name=? WHERE owner=? AND kind='doc' AND name=?",
                    (new, user, old))
        con.commit()
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


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
                if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?", (user,)).fetchone()["n"] >= max_docs:
                    raise HTTPException(400, "Too many docs")
                d = con.execute("SELECT title, content, folder, trashed FROM docs WHERE id=?",
                                (doc_id,)).fetchone()
                if not d:
                    raise HTTPException(404, "Doc gone")
                if d["trashed"]:
                    raise HTTPException(410, "In trash - restore first")
                base = d["title"] + " (copy)"
                title, i = base, 2
                while con.execute("SELECT 1 FROM docs WHERE owner=? AND title=? COLLATE NOCASE",
                                  (user, title)).fetchone():
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
                deps.check_quota(user, len(text.encode("utf-8")) + fbytes)
                con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (nid, user, title, text, d["folder"], now, now))
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
                _rb.commit()
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
    # verdict reads the files table, so a best-effort sync_doc_files failure
    # above can undercount the copy and miss over-quota the same way.
    try:
        _over = quota_svc.user_bytes(user) > quota_svc.quota_cap()
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
            quota_svc.invalidate_quota_cache(user)
            raise HTTPException(413, "Quota exceeded")
    quota_svc.invalidate_quota_cache(user)
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
