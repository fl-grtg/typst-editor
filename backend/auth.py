from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from backend import config, db

SESSION_SECONDS = 14 * 24 * 3600
COOKIE = "typst_session"  # eine Quelle (main + sync nutzen diese)
DUMMY_HASH = "pbkdf2$200000$" + "00" * 16 + "$" + "00" * 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2$200000${salt.hex()}${digest.hex()}"


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


def mint(username: str) -> str:  # Session ohne Passwort: nach Register/Verify
    token = secrets.token_urlsafe(32)
    try:
        seconds = config.load().SESSION_SECONDS
    except Exception:
        seconds = SESSION_SECONDS
    expires = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    con = db.connect()
    try:
        con.execute("INSERT INTO sessions (token_hash, username, expires) VALUES (?,?,?)",
                    (sha(token), username, expires))
        con.commit()
        return token
    finally:
        con.close()


def create_session(username: str, password: str) -> str | None:
    con = db.connect()
    try:
        row = con.execute("SELECT hash FROM users WHERE name=?", (username,)).fetchone()
        real = row["hash"] if row else DUMMY_HASH
        if not row or not check_password(password, real):
            return None
        try:  # abgelaufene Sessions kehren nicht wieder: 1 Delete pro Login hält die Tabelle klein
            con.execute("DELETE FROM sessions WHERE expires < ?", (datetime.now(timezone.utc).isoformat(),))
            con.commit()
        except Exception:
            pass
    finally:
        con.close()
    return mint(username)


def verify_session(token: str) -> str | None:
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
                exp = exp.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            exp = None
        if exp is None or exp < datetime.now(timezone.utc):
            try:
                con.execute("DELETE FROM sessions WHERE token_hash=?", (sha(token),))
                con.commit()
            except Exception:
                pass
            return None
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
