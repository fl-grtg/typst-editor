from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta

from backend import config, db
from backend.constants import PBKDF2_ROUNDS

log = logging.getLogger(__name__)

_FALLBACK_SESSION_SECONDS = 14 * 24 * 3600
COOKIE = "typst_session"
DUMMY_HASH = f"pbkdf2${PBKDF2_ROUNDS}$" + "00" * 16 + "$" + "00" * 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


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


def mint(username: str) -> str:
    token = secrets.token_urlsafe(32)
    try:
        seconds = int(config.load().SESSION_SECONDS)
    except Exception:
        seconds = _FALLBACK_SESSION_SECONDS
    seconds = min(max(seconds, 3600), 7776000)
    expires = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
    con = db.connect()
    try:
        con.execute("INSERT INTO sessions (token_hash, username, expires) VALUES (?,?,?)",
                    (sha(token), username, expires))
        con.execute("DELETE FROM sessions WHERE username=? AND token_hash NOT IN "
                    "(SELECT token_hash FROM sessions WHERE username=? ORDER BY rowid DESC LIMIT 20)",
                    (username, username))
        con.commit()
        return token
    finally:
        con.close()


def create_session(username: str, password: str) -> str | None:
    con = db.connect()
    try:
        row = con.execute("SELECT hash FROM users WHERE name=?", (username,)).fetchone()
        ok = check_password(password, row["hash"] if row else DUMMY_HASH)
        if not row or not ok:
            return None
        try:
            con.execute("DELETE FROM sessions WHERE expires < ?", (datetime.now(UTC).isoformat(),))
            con.commit()
        except Exception as e:
            log.warning("create_session cleanup failed: %s", e)
    finally:
        con.close()
    return mint(username)


def verify_session(token: str) -> str | None:
    # Cron may delete all expired sessions nightly: DELETE FROM sessions WHERE expires < now.
    if not token or len(token) < 32:
        return None
    con = db.connect()
    try:
        row = con.execute("SELECT username, expires FROM sessions WHERE token_hash=?",
                          (sha(token),)).fetchone()
        if not row:
            return None
        try:
            exp = datetime.fromisoformat(row["expires"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            exp = None
        now = datetime.now(UTC).isoformat()
        if exp is None or exp < datetime.now(UTC):
            try:
                con.execute("DELETE FROM sessions WHERE token_hash=?", (sha(token),))
                con.commit()
            except Exception as e:
                log.warning("verify_session cleanup failed: %s", e)
            return None
        try:
            con.execute("DELETE FROM sessions WHERE username=? AND expires < ?", (row["username"], now))
            con.commit()
        except Exception as e:
            log.warning("verify_session cleanup failed: %s", e)
        return row["username"]
    finally:
        con.close()


def delete_session(token: str) -> None:
    con = db.connect()
    try:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (sha(token),))
        con.commit()
    finally:
        con.close()
