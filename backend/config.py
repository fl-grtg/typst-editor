from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass
class Config:
    HOST: str = "127.0.0.1"
    PORT: int = 8978
    DATA_DIR: Path = ROOT / "data"
    TRUST_PROXY: bool = False
    COOKIE_SECURE: str = "auto"
    REGISTRATION: str = "invite-only"
    REGISTRATION_INVITE_TOKEN: str = ""
    SESSION_SECONDS: int = 1209600
    MAX_DOCS_PER_USER: int = 100
    MAX_BYTES_PER_USER: int = 524288000
    MAX_FILES_PER_DOC: int = 200
    RATE_LOGIN_PER_MIN: int = 10
    RATE_REGISTER_PER_HOUR: int = 20
    RATE_JOIN_PER_MIN: int = 30
    RATE_SEARCH_PER_MIN: int = 60
    RATE_FILES_PER_MIN: int = 20
    RATE_FILES_LIST_PER_MIN: int = 120
    RATE_SAVE_PER_MIN: int = 30
    RATE_COMMENTS_PER_MIN: int = 30
    RATE_EXPORT_PER_MIN: int = 5
    RATE_PW_PER_MIN: int = 10
    RATE_INVITE_PER_MIN: int = 10
    RATE_SHARE_PER_MIN: int = 10
    RATE_SNAPSHOTS_PER_MIN: int = 60
    RATE_CREATE_PER_MIN: int = 20
    RATE_DUPLICATE_PER_MIN: int = 10
    RATE_AVATAR_PER_MIN: int = 10
    RATE_FOLDERS_PER_MIN: int = 20


def _int(v: Any, d: int) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return d


def _bool(v: Any, d: bool) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return d


def _path(v: Any, d: Path) -> Path:
    if v is None or str(v) == "":
        return d
    p = Path(str(v))
    return p if p.is_absolute() else ROOT / p


_RAW: dict = {}
_MTIME: float = -1.0
_HAVE_RAW = False


def _raw() -> dict:
    global _RAW, _MTIME, _HAVE_RAW
    try:
        mt = CONFIG_PATH.stat().st_mtime
    except OSError:
        mt = -1.0
    if not _HAVE_RAW or mt != _MTIME:
        try:
            with open(CONFIG_PATH, "rb") as f:
                raw = tomllib.load(f)
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        _RAW, _MTIME, _HAVE_RAW = raw, mt, True
    return _RAW


_RATE_KEYS = ("LOGIN", "JOIN", "SEARCH", "FILES", "FILES_LIST", "SAVE", "COMMENTS", "EXPORT", "PW",
              "INVITE", "SHARE", "SNAPSHOTS", "CREATE", "DUPLICATE", "AVATAR", "FOLDERS")


def load() -> Config:
    c = Config()
    raw = _raw()
    e = os.environ.get
    if "HOST" in raw:
        c.HOST = str(raw["HOST"])
    if e("HOST") is not None:
        c.HOST = str(e("HOST"))
    if "PORT" in raw:
        c.PORT = _int(raw["PORT"], c.PORT)
    if e("PORT") is not None:
        c.PORT = _int(e("PORT"), c.PORT)
    if "DATA_DIR" in raw:
        c.DATA_DIR = _path(raw["DATA_DIR"], c.DATA_DIR)
    if e("DATA_DIR") is not None:
        c.DATA_DIR = _path(e("DATA_DIR"), c.DATA_DIR)
    if "TRUST_PROXY" in raw:
        c.TRUST_PROXY = _bool(raw["TRUST_PROXY"], c.TRUST_PROXY)
    if e("TRUST_PROXY") is not None:
        c.TRUST_PROXY = _bool(e("TRUST_PROXY"), c.TRUST_PROXY)
    if "COOKIE_SECURE" in raw:
        c.COOKIE_SECURE = str(raw["COOKIE_SECURE"]).lower()
    if e("COOKIE_SECURE") is not None:
        c.COOKIE_SECURE = str(e("COOKIE_SECURE")).lower()
    if "REGISTRATION" in raw:
        c.REGISTRATION = str(raw["REGISTRATION"]).lower()
    if e("REGISTRATION") is not None:
        c.REGISTRATION = str(e("REGISTRATION")).lower()
    if "REGISTRATION_INVITE_TOKEN" in raw:
        c.REGISTRATION_INVITE_TOKEN = str(raw["REGISTRATION_INVITE_TOKEN"])
    if e("REGISTRATION_INVITE_TOKEN") is not None:
        c.REGISTRATION_INVITE_TOKEN = str(e("REGISTRATION_INVITE_TOKEN"))
    if "SESSION_SECONDS" in raw:
        c.SESSION_SECONDS = _int(raw["SESSION_SECONDS"], c.SESSION_SECONDS)
    if e("SESSION_SECONDS") is not None:
        c.SESSION_SECONDS = _int(e("SESSION_SECONDS"), c.SESSION_SECONDS)
    if "MAX_DOCS_PER_USER" in raw:
        c.MAX_DOCS_PER_USER = _int(raw["MAX_DOCS_PER_USER"], c.MAX_DOCS_PER_USER)
    if e("MAX_DOCS_PER_USER") is not None:
        c.MAX_DOCS_PER_USER = _int(e("MAX_DOCS_PER_USER"), c.MAX_DOCS_PER_USER)
    if "MAX_BYTES_PER_USER" in raw:
        c.MAX_BYTES_PER_USER = _int(raw["MAX_BYTES_PER_USER"], c.MAX_BYTES_PER_USER)
    if e("MAX_BYTES_PER_USER") is not None:
        c.MAX_BYTES_PER_USER = _int(e("MAX_BYTES_PER_USER"), c.MAX_BYTES_PER_USER)
    if "MAX_FILES_PER_DOC" in raw:
        c.MAX_FILES_PER_DOC = _int(raw["MAX_FILES_PER_DOC"], c.MAX_FILES_PER_DOC)
    if e("MAX_FILES_PER_DOC") is not None:
        c.MAX_FILES_PER_DOC = _int(e("MAX_FILES_PER_DOC"), c.MAX_FILES_PER_DOC)
    if "RATE_REGISTER_PER_HOUR" in raw:
        c.RATE_REGISTER_PER_HOUR = _int(raw["RATE_REGISTER_PER_HOUR"], c.RATE_REGISTER_PER_HOUR)
    if e("RATE_REGISTER_PER_HOUR") is not None:
        c.RATE_REGISTER_PER_HOUR = _int(e("RATE_REGISTER_PER_HOUR"), c.RATE_REGISTER_PER_HOUR)
    for _k in _RATE_KEYS:
        _attr = f"RATE_{_k}_PER_MIN"
        if _attr in raw:
            setattr(c, _attr, _int(raw[_attr], getattr(c, _attr)))
        if e(_attr) is not None:
            setattr(c, _attr, _int(e(_attr), getattr(c, _attr)))
    d = Config()
    if not 3600 <= c.SESSION_SECONDS <= 7776000:
        log.warning("SESSION_SECONDS=%r invalid, using default %d", c.SESSION_SECONDS, d.SESSION_SECONDS)
        c.SESSION_SECONDS = d.SESSION_SECONDS
    if not 1 <= c.MAX_DOCS_PER_USER <= 10000:
        log.warning("MAX_DOCS_PER_USER=%r invalid, using default %d", c.MAX_DOCS_PER_USER, d.MAX_DOCS_PER_USER)
        c.MAX_DOCS_PER_USER = d.MAX_DOCS_PER_USER
    if not 1_048_576 <= c.MAX_BYTES_PER_USER <= 10_737_418_240:
        log.warning("MAX_BYTES_PER_USER=%r invalid, using default %d", c.MAX_BYTES_PER_USER, d.MAX_BYTES_PER_USER)
        c.MAX_BYTES_PER_USER = d.MAX_BYTES_PER_USER
    if not 1 <= c.MAX_FILES_PER_DOC <= 2000:
        log.warning("MAX_FILES_PER_DOC=%r invalid, using default %d", c.MAX_FILES_PER_DOC, d.MAX_FILES_PER_DOC)
        c.MAX_FILES_PER_DOC = d.MAX_FILES_PER_DOC
    if not 1 <= c.PORT <= 65535:
        log.warning("PORT=%r invalid, using default %d", c.PORT, d.PORT)
        c.PORT = d.PORT
    if not 1 <= c.RATE_REGISTER_PER_HOUR <= 10000:
        log.warning("RATE_REGISTER_PER_HOUR=%r invalid, using default %d",
                    c.RATE_REGISTER_PER_HOUR, d.RATE_REGISTER_PER_HOUR)
        c.RATE_REGISTER_PER_HOUR = d.RATE_REGISTER_PER_HOUR
    for _k in _RATE_KEYS:
        _attr = f"RATE_{_k}_PER_MIN"
        _v = getattr(c, _attr)
        if not 1 <= _v <= 10000:
            log.warning("%s=%r invalid, using default %d", _attr, _v, getattr(d, _attr))
            setattr(c, _attr, getattr(d, _attr))
    c.REGISTRATION = c.REGISTRATION.strip().lower()
    if c.REGISTRATION not in ("open", "invite-only", "closed"):
        log.warning("REGISTRATION=%r invalid, fail-closed to %r", c.REGISTRATION, "closed")
        c.REGISTRATION = "closed"
    c.COOKIE_SECURE = c.COOKIE_SECURE.strip().lower()
    if c.COOKIE_SECURE not in ("auto", "true", "false"):
        log.warning("COOKIE_SECURE=%r invalid, using default %r", c.COOKIE_SECURE, d.COOKIE_SECURE)
        c.COOKIE_SECURE = d.COOKIE_SECURE
    return c
