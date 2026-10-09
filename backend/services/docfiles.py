"""Document file helpers shared by the REST routes and the MCP tools.

Disk layout: <files>/<doc_id>/<path>, where <path> is a relative
"a/b/c.png" style path (flat names from before keep working unchanged).
The files table mirrors the tree (doc_id, path, size, mtime, type):
quota and search read the table, never the filesystem. Write-through
(record/drop on every mutation here) keeps it exact; list_files() runs
sync_doc_files() first so external writers (duplicate, MCP text edit)
heal on the next listing. Hard doc delete cascades via FK.
"""
from __future__ import annotations

import abc
import logging
import os
import re
import secrets
import sqlite3
from pathlib import Path
from typing import NamedTuple

from fastapi import HTTPException, UploadFile

from backend import config, db, deps
from backend.constants import MAX_TXT, UPLOAD_MAX
from backend.services import quota as quota_svc

log = logging.getLogger("typst.main")


class FileEntry(NamedTuple):
    path: str  # relative posix path inside the doc ("a.png", "sub/b.typ")
    size: int
    mtime: float


class FileStore(abc.ABC):
    """Layout + atomic writes for doc attachments. Local disk for now;
    a later object store only replaces this interface (Wave 6)."""

    @abc.abstractmethod
    def doc_path(self, doc_id: str, path: str) -> Path:
        """Final on-disk location (inside the store, traversal-safe)."""

    @abc.abstractmethod
    def tmp_path(self, doc_id: str, path: str) -> Path:
        """Fresh hidden tmp sibling for atomic upload (never listed/counted)."""

    @abc.abstractmethod
    def publish(self, tmp: Path, doc_id: str, path: str) -> None:
        """mkdir parents + atomic replace tmp -> final."""

    @abc.abstractmethod
    def put(self, doc_id: str, path: str, data: bytes) -> int:
        """Atomic small write (text saves). Returns the size."""

    @abc.abstractmethod
    def get(self, doc_id: str, path: str) -> bytes:
        """Raises FileNotFoundError when gone."""

    @abc.abstractmethod
    def delete(self, doc_id: str, path: str) -> bool:
        """True when something was removed."""

    @abc.abstractmethod
    def list(self, doc_id: str) -> list[FileEntry]:
        """Recursive, sorted by path; skips hidden and *.tmp.* files."""

    @abc.abstractmethod
    def stat(self, doc_id: str, path: str) -> FileEntry | None:
        ...


class LocalFileStore(FileStore):
    def __init__(self, base: Path | None = None) -> None:
        self._base = base

    def _root(self) -> Path:
        if self._base is not None:
            return self._base
        return deps.get_files_dir()

    def doc_path(self, doc_id: str, path: str) -> Path:
        root = (self._root() / doc_id).resolve()
        base = self._root().resolve()
        if root != base and base not in root.parents:
            raise HTTPException(400, "Bad doc")
        p = (root / Path(path)).resolve()
        if p != root and root not in p.parents:
            raise HTTPException(400, "Bad file name")
        return p

    def tmp_path(self, doc_id: str, path: str) -> Path:
        final = self.doc_path(doc_id, path)
        return final.parent / f"{final.name}.tmp.{secrets.token_hex(8)}"

    def publish(self, tmp: Path, doc_id: str, path: str) -> None:
        final = self.doc_path(doc_id, path)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, final)

    def put(self, doc_id: str, path: str, data: bytes) -> int:
        tmp = self.tmp_path(doc_id, path)
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            self.publish(tmp, doc_id, path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return len(data)

    def get(self, doc_id: str, path: str) -> bytes:
        p = self.doc_path(doc_id, path)
        if not p.is_file():
            raise FileNotFoundError(path)
        return p.read_bytes()

    def delete(self, doc_id: str, path: str) -> bool:
        p = self.doc_path(doc_id, path)
        try:
            p.unlink()
            return True
        except FileNotFoundError:
            return False

    def list(self, doc_id: str) -> list[FileEntry]:
        d = self._root() / doc_id
        out: list[FileEntry] = []
        if not d.is_dir():
            return out
        try:
            walking = list(d.rglob("*"))
        except OSError:
            return out
        for p in walking:
            try:
                if not p.is_file():
                    continue
                rel = p.relative_to(d).as_posix()
                if any(seg.startswith(".") for seg in rel.split("/")) or ".tmp." in p.name:
                    continue
                st = p.stat()
            except OSError:
                continue
            out.append(FileEntry(rel, st.st_size, st.st_mtime))
        out.sort()
        return out

    def stat(self, doc_id: str, path: str) -> FileEntry | None:
        try:
            st = self.doc_path(doc_id, path).stat()
        except OSError:
            return None
        return FileEntry(path, st.st_size, st.st_mtime)


store: FileStore = LocalFileStore()


def file_type(path: str) -> str:
    return Path(path).suffix.lower()


def safe_name(name: str) -> str:
    # Relative "a/b/c.png" paths (new) and flat names (old callers, MCP)
    # share this check: segments are sanitized like before, ".." and
    # absolute paths are rejected, the suffix whitelist still applies.
    raw = (name or "").strip().replace("\\", "/")
    segs = raw.split("/")
    if any(s == ".." for s in segs):
        raise HTTPException(400, "Only png/jpg/jpeg/svg/gif/webp/pdf/typ/bib/csv")
    parts = []
    for s in segs:
        if s in ("", "."):
            continue
        n = re.sub(r"[^A-Za-z0-9._-]", "_", s.strip().lstrip("."))[:100]
        if not n:
            raise HTTPException(400, "Only png/jpg/jpeg/svg/gif/webp/pdf/typ/bib/csv")
        parts.append(n)
    if not parts:
        raise HTTPException(400, "Only png/jpg/jpeg/svg/gif/webp/pdf/typ/bib/csv")
    n = "/".join(parts)
    if Path(n).suffix.lower() not in deps.ALLOWED_IMG:
        raise HTTPException(400, "Only png/jpg/jpeg/svg/gif/webp/pdf/typ/bib/csv")
    if ".tmp." in n:
        raise HTTPException(400, "Reserved name")
    return n


def record_file(doc_id: str, path: str, size: int, mtime: float) -> None:
    con = db.connect()
    try:
        try:
            con.execute("INSERT OR REPLACE INTO files (doc_id, path, size, mtime, type) "
                        "VALUES (?,?,?,?,?)", (doc_id, path, size, mtime, file_type(path)))
            con.commit()
        except sqlite3.OperationalError as e:
            raise deps.busy_503("record_file", e) from e
    finally:
        con.close()


def drop_file(doc_id: str, path: str) -> None:
    con = db.connect()
    try:
        try:
            con.execute("DELETE FROM files WHERE doc_id=? AND path=?", (doc_id, path))
            con.commit()
        except sqlite3.OperationalError as e:
            raise deps.busy_503("drop_file", e) from e
    finally:
        con.close()


def sync_doc_files(doc_id: str) -> int:
    """Reconcile the files table with disk (external writers heal here).
    Returns the row count afterwards."""
    disk = {e.path: e for e in store.list(doc_id)}
    con = db.connect()
    try:
        try:
            rows = con.execute("SELECT path, size, mtime FROM files WHERE doc_id=?", (doc_id,)).fetchall()
        except sqlite3.OperationalError as e:
            raise deps.busy_503("sync_doc_files", e) from e
        known = {r["path"]: (r["size"], r["mtime"]) for r in rows}
        for path, ent in disk.items():
            old = known.get(path)
            if old is None or old[0] != ent.size or old[1] != ent.mtime:
                con.execute("INSERT OR REPLACE INTO files (doc_id, path, size, mtime, type) "
                            "VALUES (?,?,?,?,?)", (doc_id, path, ent.size, ent.mtime, file_type(path)))
        for path in known:
            if path not in disk:
                con.execute("DELETE FROM files WHERE doc_id=? AND path=?", (doc_id, path))
        try:
            con.commit()
        except sqlite3.OperationalError as e:
            raise deps.busy_503("sync_doc_files", e) from e
        return len(disk)
    finally:
        con.close()


def _tree_count(d: Path, skip: str = "") -> int:
    # Recursive live count (subpaths included); tmp/hidden never counted.
    try:
        return sum(1 for p in d.rglob("*") if p.is_file() and ".tmp." not in p.name
                   and not any(seg.startswith(".") for seg in p.relative_to(d).as_posix().split("/"))
                   and (not skip or p.relative_to(d).as_posix() != skip))
    except OSError as e:
        log.warning("upload_file list failed: %s", e)
        raise HTTPException(500, "File list failed") from e


def _max_files() -> int:
    try:
        return config.load().MAX_FILES_PER_DOC
    except Exception:
        return 200


def _upload_locked(doc_id: str, f: UploadFile, n: str, user: str) -> dict:
    max_files = _max_files()
    d = deps.get_files_dir() / doc_id
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("upload_file mkdir failed: %s", e)
        raise HTTPException(500, "Upload failed") from e
    if _tree_count(d, skip=n) >= max_files:
        raise HTTPException(400, "Too many files")
    tmp = store.tmp_path(doc_id, n)
    try:
        tmp.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("upload_file mkdir failed: %s", e)
        raise HTTPException(500, "Upload failed") from e
    size = 0
    try:
        with open(tmp, "wb") as fh:
            while True:
                blk = f.file.read(64 * 1024)
                if not blk:
                    break
                size += len(blk)
                if size > UPLOAD_MAX:
                    raise HTTPException(400, "Max 10 MB")
                fh.write(blk)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
    except HTTPException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except OSError as e:
        log.warning("upload_file write failed: %s", e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(500, "Upload failed") from e
    try:
        old = store.get(doc_id, n)
    except (OSError, HTTPException):
        old = None

    def _restore_upload() -> None:
        try:
            if old is not None:
                store.put(doc_id, n, old)
                st = store.stat(doc_id, n)
                if st is not None:
                    record_file(doc_id, n, st.size, st.mtime)
            else:
                store.delete(doc_id, n)
                drop_file(doc_id, n)
        except (OSError, HTTPException):
            pass

    _up_owner = deps._owner(doc_id, user)
    try:
        with quota_svc.quota_guard(_up_owner, max(0, size - (len(old) if old is not None else 0)), rollback=_restore_upload):
            try:
                store.publish(tmp, doc_id, n)
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            if _tree_count(d) > max_files:
                _restore_upload()
                raise HTTPException(400, "Too many files")
            st = store.stat(doc_id, n)
            if st is not None:
                record_file(doc_id, n, st.size, st.mtime)
    except sqlite3.OperationalError as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise deps.busy_503("upload_file", e) from e
    except HTTPException:
        # Both 413 paths clean up tmp (pre-check never replaced it, post-check rolls back).
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    touch_doc(doc_id)
    quota_svc.invalidate_quota_cache(_up_owner)
    return {"name": n, "size": size}


def need_text(name: str) -> str:
    n = safe_name(name)
    if Path(n).suffix.lower() not in deps.TEXT_SUFFIX:
        raise HTTPException(400, "Only typ/bib/csv as text")
    return n


def save_text_file(doc_id: str, name: str, content: str, owner: str) -> None:
    """Same write path as the text-tab route: tmp+replace, quota, table sync."""
    name = need_text(name)  # validate here too: callers must not skip the suffix whitelist
    if len(content) > MAX_TXT:
        raise HTTPException(400, "Max 200 KB")
    try:
        old = store.get(doc_id, name)
    except (OSError, HTTPException):
        old = None
    _old_sz = len(old) if old is not None else 0
    if old is None and _tree_count(deps.get_files_dir() / doc_id) >= _max_files():
        raise HTTPException(400, "Too many files")

    def _restore_text() -> None:
        try:
            if old is None:
                store.delete(doc_id, name)
                drop_file(doc_id, name)
            else:
                store.put(doc_id, name, old)
                st = store.stat(doc_id, name)
                if st is not None:
                    record_file(doc_id, name, st.size, st.mtime)
        except (OSError, HTTPException):
            pass

    tmp = store.tmp_path(doc_id, name)
    try:
        with quota_svc.quota_guard(owner, max(0, len(content.encode("utf-8")) - _old_sz),
                                   rollback=_restore_text):
            try:
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(content, encoding="utf-8")
                store.publish(tmp, doc_id, name)
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            st = store.stat(doc_id, name)
            if st is not None:
                record_file(doc_id, name, st.size, st.mtime)
    except sqlite3.OperationalError as e:
        raise deps.busy_503("save_text_file", e) from e
    touch_doc(doc_id)
    quota_svc.invalidate_quota_cache(owner)


def touch_doc(doc_id: str) -> None:
    con = db.connect()
    try:
        try:
            con.execute("UPDATE docs SET updated_at=? WHERE id=?", (db.now_iso(), doc_id))
            con.commit()
        except sqlite3.OperationalError as e:
            raise deps.busy_503("touch_doc", e) from e
    finally:
        con.close()
