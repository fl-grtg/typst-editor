from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import sqlite3 as _sqlite3
import threading as _threading
from datetime import UTC, datetime, timedelta

from backend import config, db
from backend.constants import PBKDF2_ROUNDS

log = logging.getLogger(__name__)

# 1C: PBKDF2 rounds bumped to >= 600k (was 300k). Old hashes keep working;
# create_session() rehashes on successful login (see needs_rehash).
HASH_ROUNDS = 600_000
CURRENT_ROUNDS = max(int(PBKDF2_ROUNDS), HASH_ROUNDS)

_FALLBACK_SESSION_SECONDS = 14 * 24 * 3600
COOKIE = "typst_session"
DUMMY_HASH = f"pbkdf2${CURRENT_ROUNDS}$" + "00" * 16 + "$" + "00" * 32

# Session cleanup runs in a background daemon thread (1C): verify_session is
# read-only, never DELETEs. Interval is short enough to bound the sessions
# table, long enough to stay off the hot path.
SESSION_CLEANUP_INTERVAL_S = 300.0

_TLS = _threading.local()
_CLEANUP_THREAD: _threading.Thread | None = None
_CLEANUP_LOCK = _threading.Lock()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, CURRENT_ROUNDS)
    return f"pbkdf2${CURRENT_ROUNDS}${salt.hex()}${digest.hex()}"


def _parse_hash(stored: str) -> tuple[str, int] | None:
    try:
        algo, rounds, _salt_hex, _expected = stored.split("$", 3)
        return algo, int(rounds)
    except (ValueError, TypeError, AttributeError):
        return None


def needs_rehash(stored: str) -> bool:
    """True when a stored hash uses fewer rounds than CURRENT_ROUNDS."""
    parsed = _parse_hash(stored)
    if parsed is None:
        return True
    algo, rounds = parsed
    if algo != "pbkdf2":
        return True
    return rounds < CURRENT_ROUNDS


def check_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, expected = stored.split("$", 3)
        if algo != "pbkdf2" or not 10_000 <= int(rounds) <= 1_000_000:
            return False
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _cached_conn() -> _sqlite3.Connection:
    """Thread-local reused connection (1C): PRAGMAs run once per connection.

    Keyed by the live DB path so tests that monkeypatch db.DB_PATH get a
    fresh connection instead of a stale one. Falls back to db.connect()
    semantics (WAL, busy_timeout, FK) but without re-running PRAGMAs on
    every verify_session call.
    """
    try:
        path = str(db.get_db_path())
    except Exception as e:
        log.warning("auth db path fallback: %s", e)
        path = str(db.DB_PATH)
    con = getattr(_TLS, "con", None)
    cached_path = getattr(_TLS, "path", None)
    if con is not None and cached_path == path:
        try:
            con.execute("SELECT 1").fetchone()
            return con
        except _sqlite3.Error as e:
            log.warning("auth cached conn stale, reopen: %s", e)
            try:
                con.close()
            except Exception as e:
                log.warning("auth cached conn close failed: %s", e)
            _TLS.con = None
    elif con is not None:
        try:
            con.close()
        except Exception as e:
            log.warning("auth cached conn close on path change failed: %s", e)
        _TLS.con = None
    # Fresh connection: PRAGMAs once here, not per query.
    Path = __import__("pathlib").Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = _sqlite3.connect(path, check_same_thread=False)
    con.row_factory = _sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA foreign_keys=ON")
    except _sqlite3.Error as e:
        log.warning("auth pragmas failed: %s", e)
    _TLS.con = con
    _TLS.path = path
    return con


def cleanup_expired_sessions() -> int:
    """Delete expired sessions. Called by the background thread (1C)."""
    try:
        con = db.connect()
    except Exception as e:
        log.warning("session cleanup connect failed: %s", e)
        return 0
    try:
        try:
            cur = con.execute("DELETE FROM sessions WHERE expires < ?",
                              (datetime.now(UTC).isoformat(),))
            con.commit()
            n = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
            if n:
                log.info("session cleanup removed %d expired", n)
            return n
        except Exception as e:
            log.warning("session cleanup failed: %s", e)
            return 0
    finally:
        try:
            con.close()
        except Exception as e:
            log.warning("session cleanup close failed: %s", e)


def _cleanup_loop(interval_s: float) -> None:
    try:
        while True:
            try:
                import time as _time
                _time.sleep(interval_s)
            except Exception as e:
                log.warning("session cleanup sleep interrupted: %s", e)
                break
            try:
                cleanup_expired_sessions()
            except Exception as e:
                log.warning("session cleanup loop failed: %s", e)
    except Exception as e:
        log.warning("session cleanup thread died: %s", e)


def ensure_cleanup_thread(interval_s: float = SESSION_CLEANUP_INTERVAL_S) -> None:
    """Start the daemon cleanup thread once (idempotent, 1C)."""
    global _CLEANUP_THREAD
    with _CLEANUP_LOCK:
        if _CLEANUP_THREAD is not None and _CLEANUP_THREAD.is_alive():
            return
        try:
            t = _threading.Thread(target=_cleanup_loop, args=(interval_s,),
                                  name="session-cleanup", daemon=True)
            t.start()
            _CLEANUP_THREAD = t
        except Exception as e:
            log.warning("session cleanup thread start failed: %s", e)


def mint(username: str) -> str:
    token = secrets.token_urlsafe(32)
    try:
        seconds = int(config.load().SESSION_SECONDS)
    except Exception as e:
        log.warning("mint SESSION_SECONDS fallback: %s", e)
        seconds = _FALLBACK_SESSION_SECONDS
    seconds = min(max(seconds, 3600), 7776000)
    expires = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
    ensure_cleanup_thread()
    con = db.connect()
    try:
        con.execute("INSERT INTO sessions (token_hash, username, expires) VALUES (?,?,?)",
                    (sha(token), username, expires))
        con.execute("DELETE FROM sessions WHERE username=? AND token_hash NOT IN "
                    "(SELECT token_hash FROM sessions WHERE username=? ORDER BY expires DESC, rowid DESC LIMIT 20)",
                    (username, username))
        con.commit()
        return token
    finally:
        try:
            con.close()
        except Exception as e:
            log.warning("mint close failed: %s", e)


def create_session(username: str, password: str) -> str | None:
    con = db.connect()
    try:
        row = con.execute("SELECT name, hash FROM users WHERE name=? COLLATE NOCASE", (username,)).fetchone()
        ok = check_password(password, row["hash"] if row else DUMMY_HASH)
        if not row or not ok:
            return None
        canonical = row["name"]
        stored = row["hash"]
        # 1C: rehash-on-login when stored rounds are stale. Best-effort:
        # a failed rehash never fails the login.
        if needs_rehash(stored):
            try:
                con.execute("UPDATE users SET hash=? WHERE name=?",
                            (hash_password(password), canonical))
                con.commit()
            except Exception as e:
                log.warning("create_session rehash failed for %s: %s", canonical, e)
        # 1C: no expired-session DELETE here (background job owns cleanup).
    finally:
        try:
            con.close()
        except Exception as e:
            log.warning("create_session close failed: %s", e)
    return mint(canonical)


def verify_session(token: str) -> str | None:
    # 1C: read-only. Expired rows are left for the background cleanup thread
    # (cleanup_expired_sessions) so the WS hot path never blocks on writes.
    if not token or len(token) < 32:
        return None
    try:
        con = _cached_conn()
    except Exception as e:
        log.warning("verify_session connect failed: %s", e)
        return None
    try:
        row = con.execute("SELECT username, expires FROM sessions WHERE token_hash=?",
                          (sha(token),)).fetchone()
    except Exception as e:
        log.warning("verify_session select failed: %s", e)
        return None
    if not row:
        return None
    try:
        exp = datetime.fromisoformat(row["expires"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
    except (ValueError, TypeError) as e:
        log.warning("verify_session bad expiry, treat as expired: %s", e)
        return None
    if exp < datetime.now(UTC):
        return None
    return row["username"]


def delete_session(token: str) -> None:
    con = db.connect()
    try:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (sha(token),))
        con.commit()
    except Exception as e:
        log.warning("delete_session failed: %s", e)
    finally:
        try:
            con.close()
        except Exception as e:
            log.warning("delete_session close failed: %s", e)
