"""Git mirror of project versions: every version becomes a commit, optionally pushed to a remote.

One worker thread runs all Git work in order, so requests never wait on a commit or a slow remote.
The job commits every version newer than the last committed one (git_head), which keeps the order
right however the saves raced, and picks up versions a failed run left behind.
"""
from __future__ import annotations

import base64
import ipaddress
import logging
import os
import posixpath
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from backend import db, deps

log = logging.getLogger("typst.main")

COMMITTER = ("Typst Editor", "noreply@typst-editor.invalid")
PROTOCOLS = "https"  # GIT_ALLOW_PROTOCOL: never file://, ssh or ext:: from a user-supplied remote
BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}")
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="git")
_queued: set[str] = set()
_lock = threading.Lock()


def available() -> bool:
    return shutil.which("git") is not None


def repo_dir(project_id: str) -> Path:
    return deps.get_files_dir().parent / "git" / project_id


def _fernet() -> Fernet:
    # The key lives next to the database, not in it: a leaked app.db or DB backup does not reveal tokens.
    path = deps.get_files_dir().parent / ".secret_key"
    try:
        return Fernet(path.read_bytes().strip())
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return Fernet(path.read_bytes().strip())
        key = Fernet.generate_key()
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return Fernet(key)


def seal(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode() if token else ""


def unseal(stored: str) -> str:
    try:
        return _fernet().decrypt(stored.encode()).decode() if stored else ""
    except (InvalidToken, ValueError):
        return ""


def _internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved


def check_remote(url: str) -> str:
    """An https URL without credentials whose host resolves to routable addresses (private networks are fine, loopback and link-local such as cloud metadata are not)."""
    url = url.strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise HTTPException(400, "Remote must be an https:// URL without credentials")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError, ValueError) as e:
        raise HTTPException(400, "Remote host not found") from e
    if any(_internal(ipaddress.ip_address(str(info[4][0]).split("%")[0])) for info in infos):
        raise HTTPException(400, "Remote host must not be a loopback or link-local address")
    return url


def check_branch(name: str) -> str:
    name = name.strip()
    if not BRANCH_RE.fullmatch(name) or ".." in name or "//" in name or name.endswith(("/", ".", ".lock")):
        raise HTTPException(400, "Invalid branch name")
    return name


def _git(repo: Path, *args: str, env: dict[str, str] | None = None, timeout: int = 60) -> str:
    base = {"PATH": os.environ.get("PATH", ""), "HOME": str(repo), "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": PROTOCOLS}
    return subprocess.run(["git", "-c", f"core.hooksPath={os.devnull}", *args], cwd=repo, env={**base, **(env or {})},
                          capture_output=True, text=True, timeout=timeout, check=True).stdout


def _safe(path: str) -> bool:
    return bool(path) and all(p not in ("", ".", "..") and p.casefold() != ".git" for p in path.split("/"))


def tree(state: dict) -> dict[str, bytes]:
    """Files of a version as the repository holds them: documents named like in the project ZIP export
    (<folder>/<sanitized title>.typ) next to the project files, so an exported ZIP is a clean checkout."""
    from backend.render import _export_stem

    files = {path: base64.b64decode(encoded) for path, encoded in state["files"].items()}
    taken = {path.casefold() for path in files}
    for d in sorted(state["documents"], key=lambda d: d["id"]):
        title = _export_stem(d["title"])
        path = posixpath.join(d.get("folder") or "", title + ".typ")
        if path.casefold() in taken:
            path = posixpath.join(d.get("folder") or "", f"{title}_{d['id']}.typ")
        taken.add(path.casefold())
        files[path] = d["content"].encode("utf-8", errors="surrogateescape")
    return {path: data for path, data in files.items() if _safe(path)}


def _checkout(repo: Path, files: dict[str, bytes]) -> None:
    for entry in repo.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for path, data in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def message(row: sqlite3.Row, coauthors: list[tuple[str, str]]) -> str:
    lines = [" ".join((row["label"] or ("Automatic version" if row["kind"] == "auto" else "Version")).split())]
    if row["summary"]:
        lines += ["", f"Changed: {row['summary']}"]
    if coauthors:
        lines += ["", *(f"Co-authored-by: {name} <{email}>" for name, email in coauthors)]
    return "\n".join(lines)


def _head(repo: Path) -> str:
    try:
        return _git(repo, "rev-parse", "HEAD").strip()
    except subprocess.CalledProcessError:
        return ""  # no commit yet


def _commit(con: sqlite3.Connection, repo: Path, row: sqlite3.Row, owner: str) -> str:
    """Commit a version as the project owner; everyone else who wrote is a co-author. Returns the commit holding it."""
    from backend.services import project_history

    _checkout(repo, tree(project_history.load(row["content"])))
    _git(repo, "add", "-A")
    if not row["label"] and not _git(repo, "status", "--porcelain"):
        return _head(repo)  # same files as the last commit: that commit holds this version too
    names = sorted({u for u in row["editors"].split(",") if u and u != owner})
    emails = dict(con.execute(f"SELECT name,git_email FROM users WHERE git_email<>'' AND name IN ({','.join('?' * len(names))})", names).fetchall()) if names else {}
    coauthors = [(n, emails[n]) for n in names if n in emails]
    found = con.execute("SELECT git_email FROM users WHERE name=?", (owner,)).fetchone()
    name, email = (owner, found[0]) if found and found[0] else (owner, COMMITTER[1])
    when = f"@{int(datetime.fromisoformat(row['created_at']).timestamp())} +0000"
    _git(repo, "commit", "-q", "--allow-empty", "-m", message(row, coauthors), env={
        "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": when})
    return _head(repo)


def _push(repo: Path, s: dict, rev: str = "HEAD") -> str:
    """Push `rev` to the remote branch; '' on success, else a short reason."""
    env = {}
    token = unseal(s["token"])
    if s["token"] and not token:
        return "The saved token cannot be read; enter it again"
    if token:
        parts = urlsplit(s["remote"])
        auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"http.{parts.scheme}://{parts.netloc}/.extraHeader",
               "GIT_CONFIG_VALUE_0": f"Authorization: Basic {auth}"}
    try:
        check_remote(s["remote"])  # resolve again: the host may point elsewhere since it was saved
        _git(repo, "push", "-q", "--porcelain", s["remote"], f"{rev}:refs/heads/{s['branch']}", env=env, timeout=120)
    except HTTPException as e:
        return str(e.detail)
    except subprocess.TimeoutExpired:
        return "Push timed out"
    except subprocess.CalledProcessError as e:
        return _reason((e.stderr or "") + (e.stdout or ""), token)  # --porcelain puts the rejected ref on stdout
    return ""


def _reason(output: str, token: str) -> str:
    """One readable line out of git's push output."""
    text = output.replace(token, "***") if token else output
    if "[rejected]" in text or "non-fast-forward" in text or "fetch first" in text:
        return "The remote branch has commits this project does not have; pick another branch or reset it"
    if "Authentication failed" in text or "could not read Username" in text or "returned error: 403" in text:
        return "Access denied: check the token and its push rights"
    if "not found" in text.lower():
        return "Repository not found: check the URL and the token's access"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("hint:")]
    return (lines[-1].removeprefix("fatal: ").removeprefix("error: ") if lines else "Push failed")[:300]


_ROW = "SELECT id,content,label,kind,author,summary,editors,created_at FROM project_snapshots"


def _open(con: sqlite3.Connection, project_id: str) -> tuple[dict, Path, str]:
    from backend.services import project_history

    s = project_history.settings(con, project_id)
    repo = repo_dir(project_id)
    if s["git"] and not (repo / ".git").is_dir():
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
    return s, repo, con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()[0]


def _record(con: sqlite3.Connection, sid: str, commit: str) -> None:
    con.execute("UPDATE project_snapshots SET commit_hash=? WHERE id=?", (commit, sid))
    con.commit()


def _pushed(con: sqlite3.Connection, project_id: str, repo: Path, s: dict, rev: str = "HEAD") -> str:
    status = _push(repo, s, rev)
    con.execute("UPDATE project_versioning SET push_status=?, pushed_at=CASE WHEN ?='' THEN ? ELSE pushed_at END, "
                "pushed_hash=CASE WHEN ?='' THEN ? ELSE pushed_hash END WHERE project_id=?",
                (status, status, db.now_iso(), status, _git(repo, "rev-parse", rev).strip(), project_id))
    con.commit()
    return status


def sync(project_id: str) -> None:
    con = db.connect()
    try:
        s, repo, owner = _open(con, project_id)
        if not s["git"]:
            return
        rows = con.execute(_ROW + " WHERE project_id=? AND created_at>? ORDER BY created_at,rowid", (project_id, s["git_head"])).fetchall()
        if not s["git_head"]:
            rows = rows[-1:]  # Git was just turned on: start from the newest version, not the whole history
        for row in rows:
            _record(con, row["id"], _commit(con, repo, row, owner))
            con.execute("UPDATE project_versioning SET git_head=? WHERE project_id=?", (row["created_at"], project_id))
            con.commit()
        if s["remote"] and s["push"] and rows and _head(repo):
            _pushed(con, project_id, repo, s)
    except (sqlite3.Error, OSError, ValueError, subprocess.SubprocessError) as e:
        log.warning("Git mirror of %s skipped: %s", project_id, e)
    finally:
        con.close()


def commit_version(project_id: str, sid: str) -> str:
    """Commit a version that has none (it predates Git being turned on): its files go on top as a new commit.
    The next version brings the newest files back on top."""
    con = db.connect()
    try:
        s, repo, owner = _open(con, project_id)
        row = con.execute(_ROW + " WHERE id=? AND project_id=?", (sid, project_id)).fetchone()
        if not row:
            return "Version not found"
        if con.execute("SELECT commit_hash FROM project_snapshots WHERE id=?", (sid,)).fetchone()[0]:
            return ""
        if s["git_head"] and row["created_at"] > s["git_head"]:  # still queued: commit the backlog in order instead
            sync(project_id)
            return ""
        _record(con, sid, _commit(con, repo, row, owner))
        if s["remote"] and s["push"]:
            return _pushed(con, project_id, repo, s)
        return ""
    finally:
        con.close()


def push_version(project_id: str, sid: str) -> str:
    """Push the commit of a version (and everything before it) to the remote branch."""
    con = db.connect()
    try:
        s, repo, _owner = _open(con, project_id)
        found = con.execute("SELECT commit_hash FROM project_snapshots WHERE id=? AND project_id=?", (sid, project_id)).fetchone()
        if not found or not found[0]:
            return "Commit this version first"
        return _pushed(con, project_id, repo, s, found[0])
    finally:
        con.close()


def pushed(project_id: str, head: str) -> set[str]:
    """Commits the remote branch has: the last pushed commit and its ancestors."""
    repo = repo_dir(project_id)
    if not head or not (repo / ".git").is_dir():
        return set()
    try:
        return set(_git(repo, "rev-list", head).split())
    except (OSError, subprocess.SubprocessError):
        return set()


def schedule(project_id: str) -> None:
    if not available():
        return
    with _lock:
        if project_id in _queued:
            return
        _queued.add(project_id)

    def run() -> None:
        with _lock:
            _queued.discard(project_id)
        sync(project_id)

    _pool.submit(run)


def run_now(fn: Callable[..., str], *args: str) -> str:
    """Run a Git job on the worker, in order with the queued ones; '' on success, else a short reason."""
    def job() -> str:
        try:
            return fn(*args)
        except subprocess.CalledProcessError as e:
            return _reason((e.stderr or "") + (e.stdout or ""), "")
        except (sqlite3.Error, OSError, ValueError, subprocess.SubprocessError) as e:
            log.warning("Git job for %s failed: %s", args[0] if args else "", e)
            return "Git failed on the server"
    return _pool.submit(job).result(timeout=180)


def _config(repo: Path, s: dict) -> bytes:
    """A clean config for an exported .git: the remote and branch, never a token."""
    lines = ["[core]", "\trepositoryformatversion = 0", "\tfilemode = true", "\tbare = false"]
    if s["remote"]:
        local = _git(repo, "symbolic-ref", "--short", "HEAD").strip() or "main"
        lines += ['[remote "origin"]', f"\turl = {s['remote']}", "\tfetch = +refs/heads/*:refs/remotes/origin/*",
                  f'[branch "{local}"]', "\tremote = origin", f"\tmerge = refs/heads/{s['branch']}"]
    return ("\n".join(lines) + "\n").encode()


def _export_files(project_id: str) -> dict[str, bytes]:
    from backend.services import project_history

    repo = repo_dir(project_id)
    if not (repo / ".git").is_dir() or not _head(repo):
        return {}
    _git(repo, "repack", "-a", "-d", "-q")  # a few pack files instead of one file per object
    con = db.connect()
    try:
        s = project_history.settings(con, project_id)
    finally:
        con.close()
    out = {".git/config": _config(repo, s)}
    for path in sorted((repo / ".git").rglob("*")):
        rel = path.relative_to(repo / ".git").as_posix()
        if path.is_file() and not path.is_symlink() and rel != "config" and not rel.startswith("hooks/") and not rel.endswith(".lock"):
            out[".git/" + rel] = path.read_bytes()
    return out


def export_files(project_id: str) -> dict[str, bytes]:
    """The project's .git for a ZIP export ({} without Git history), made on the worker so no commit runs meanwhile."""
    try:
        return _pool.submit(_export_files, project_id).result(timeout=180)
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError, TimeoutError) as e:
        log.warning("Git export of %s skipped: %s", project_id, e)
        return {}


_HEX = re.compile(rb"[0-9a-f]{40}([0-9a-f]{24})?\n?")
_KEEP = re.compile(r"HEAD|packed-refs|refs/(heads|tags)/[A-Za-z0-9._/-]{1,200}|objects/[0-9a-f]{2}/[0-9a-f]{38,62}|objects/pack/pack-[0-9a-f]{40,64}\.(pack|idx|rev)")


def remote_of(git: dict[str, bytes]) -> tuple[str, str]:
    """Remote URL (as https) and remote branch named by an imported .git/config; ('', '') when there is none."""
    sections: dict[tuple[str, str], dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in git.get("config", b"").decode("utf-8", errors="replace").splitlines():
        line = raw.split("#")[0].split(";")[0].strip()
        if m := re.fullmatch(r'\[\s*([A-Za-z][\w.-]*)(?:\s+"([^"]*)")?\s*\]', line):
            current = sections.setdefault((m[1].lower(), m[2] or ""), {})
        elif current is not None and "=" in line:
            key, value = (x.strip() for x in line.split("=", 1))
            current[key.lower()] = value.strip('"')
    remotes = {name: v["url"] for (kind, name), v in sections.items() if kind == "remote" and v.get("url")}
    url = remotes.get("origin") or next(iter(remotes.values()), "")
    if m := re.fullmatch(r"(?:ssh://)?git@([^:/]+)[:/](.+)", url):  # scp-style SSH clone URL: the same repository over https
        url = f"https://{m[1]}/{m[2]}"
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        return "", ""
    url = f"https://{parts.hostname}{f':{parts.port}' if parts.port else ''}{parts.path}"  # drop any user:token@
    head = git.get("HEAD", b"").decode("utf-8", errors="replace").strip()
    local = head.removeprefix("ref: refs/heads/") if head.startswith("ref: refs/heads/") else ""
    merge = sections.get(("branch", local), {}).get("merge", "")
    branch = merge.removeprefix("refs/heads/") or local or "main"
    return url, branch if BRANCH_RE.fullmatch(branch) else "main"


def adopt(project_id: str, git: dict[str, bytes]) -> None:
    """Take over an imported .git: its history (objects and refs only, never config, hooks or alternates, which
    could run commands or reach other repositories on the server) and its remote and branch. Git stays on, push off."""
    remote, branch = remote_of(git)
    try:
        remote = check_remote(remote) if remote else ""
    except HTTPException:
        remote = ""
    history = False
    if available():
        repo = repo_dir(project_id)
        try:
            shutil.rmtree(repo, ignore_errors=True)
            repo.mkdir(parents=True)
            _git(repo, "init", "-q", "-b", "main")
            for rel, data in git.items():
                if not _KEEP.fullmatch(rel) or ".." in rel:
                    continue
                if rel.startswith("refs/") and not _HEX.fullmatch(data):
                    continue
                if rel == "HEAD" and not (_HEX.fullmatch(data) or re.fullmatch(rb"ref: refs/heads/[A-Za-z0-9._/-]{1,100}\n?", data)):
                    continue
                target = repo / ".git" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            _git(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}")
            _git(repo, "fsck", "--connectivity-only", "--no-dangling", "--no-progress")
            history = True
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("Imported Git history of %s not usable: %s", project_id, e)
            shutil.rmtree(repo, ignore_errors=True)
    if not history and not remote:
        return
    with db.tx() as con:
        con.execute("INSERT INTO project_versioning (project_id,git,remote,branch) VALUES (?,?,?,?) "
                    "ON CONFLICT(project_id) DO UPDATE SET git=excluded.git,remote=excluded.remote,branch=excluded.branch",
                    (project_id, int(history), remote, branch))


def drain() -> None:
    _pool.submit(lambda: None).result()


def reap() -> int:
    """Remove repositories of projects that no longer exist (startup sweep)."""
    base = deps.get_files_dir().parent / "git"
    if not base.is_dir():
        return 0
    con = db.connect()
    try:
        gone = [p for p in base.iterdir() if not con.execute("SELECT 1 FROM projects WHERE id=?", (p.name,)).fetchone()]
    finally:
        con.close()
    for p in gone:
        shutil.rmtree(p, ignore_errors=True)
    return len(gone)
