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


@dataclass(frozen=True)
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
    RATE_AUTH_PER_MIN: int = 60
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
    RATE_KEYS_PER_MIN: int = 30
    RATE_MCP_PER_MIN: int = 60
    RATE_RENAME_PER_MIN: int = 10
    RATE_DELETE_PER_MIN: int = 10
    RATE_RESTORE_PER_MIN: int = 10
    RATE_MOVE_PER_MIN: int = 20
    RATE_TEMPLATES_PER_MIN: int = 20
    RATE_TPLFOLDERS_PER_MIN: int = 20


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


# Table-driven keys: one row per setting, raw TOML then env override.
# (RATE_REGISTER is per-hour, the rest of the RATE_* family per-minute.)
_STR_KEYS = ("HOST", "COOKIE_SECURE", "REGISTRATION", "REGISTRATION_INVITE_TOKEN")
_BOOL_KEYS = ("TRUST_PROXY",)
_PATH_KEYS = ("DATA_DIR",)
_INT_KEYS = ("PORT", "SESSION_SECONDS", "MAX_DOCS_PER_USER", "MAX_BYTES_PER_USER",
             "MAX_FILES_PER_DOC", "RATE_REGISTER_PER_HOUR")
_RATE_KEYS = ("LOGIN", "AUTH", "JOIN", "SEARCH", "FILES", "FILES_LIST", "SAVE", "COMMENTS", "EXPORT", "PW",
              "INVITE", "SHARE", "SNAPSHOTS", "CREATE", "DUPLICATE", "AVATAR", "FOLDERS", "KEYS", "MCP",
              "RENAME", "DELETE", "RESTORE", "MOVE", "TEMPLATES", "TPLFOLDERS")
_ENV_KEYS = _STR_KEYS + _BOOL_KEYS + _PATH_KEYS + _INT_KEYS + tuple(f"RATE_{k}_PER_MIN" for k in _RATE_KEYS)

# (attr, min, max) ranges; out-of-range falls back to the default with a warning.
_RANGES = (
    ("SESSION_SECONDS", 3600, 7776000),
    ("MAX_DOCS_PER_USER", 1, 10000),
    ("MAX_BYTES_PER_USER", 1_048_576, 10_737_418_240),
    ("MAX_FILES_PER_DOC", 1, 2000),
    ("PORT", 1, 65535),
    ("RATE_REGISTER_PER_HOUR", 1, 10000),
    *((f"RATE_{k}_PER_MIN", 1, 10000) for k in _RATE_KEYS),
)

_CACHE: tuple[tuple, Config] | None = None


def load() -> Config:
    global _CACHE
    raw = _raw()
    e = os.environ.get
    env_snap = tuple(e(k) for k in _ENV_KEYS)
    key = (_MTIME, env_snap)
    if _CACHE is not None and _CACHE[0] == key:
        return _CACHE[1]
    d = Config()
    vals: dict[str, Any] = {}
    for k in _STR_KEYS:
        v: Any = getattr(d, k)
        if k in raw:
            v = str(raw[k])
        if e(k) is not None:
            v = str(e(k))
        vals[k] = v.lower() if k in ("COOKIE_SECURE", "REGISTRATION") else v
    for k in _BOOL_KEYS:
        v = getattr(d, k)
        if k in raw:
            v = _bool(raw[k], v)
        if e(k) is not None:
            v = _bool(e(k), v)
        vals[k] = v
    for k in _PATH_KEYS:
        v = getattr(d, k)
        if k in raw:
            v = _path(raw[k], v)
        if e(k) is not None:
            v = _path(e(k), v)
        vals[k] = v
    for k in _INT_KEYS:
        v = getattr(d, k)
        if k in raw:
            v = _int(raw[k], v)
        if e(k) is not None:
            v = _int(e(k), v)
        vals[k] = v
    for k in _RATE_KEYS:
        attr = f"RATE_{k}_PER_MIN"
        v = getattr(d, attr)
        if attr in raw:
            v = _int(raw[attr], v)
        if e(attr) is not None:
            v = _int(e(attr), v)
        vals[attr] = v
    for attr, lo, hi in _RANGES:
        if not lo <= vals[attr] <= hi:
            log.warning("%s=%r invalid, using default %d", attr, vals[attr], getattr(d, attr))
            vals[attr] = getattr(d, attr)
    vals["REGISTRATION"] = str(vals["REGISTRATION"]).strip().lower()
    if vals["REGISTRATION"] not in ("open", "invite-only", "closed"):
        log.warning("REGISTRATION=%r invalid, fail-closed to %r", vals["REGISTRATION"], "closed")
        vals["REGISTRATION"] = "closed"
    vals["COOKIE_SECURE"] = str(vals["COOKIE_SECURE"]).strip().lower()
    if vals["COOKIE_SECURE"] not in ("auto", "true", "false"):
        log.warning("COOKIE_SECURE=%r invalid, using default %r", vals["COOKIE_SECURE"], d.COOKIE_SECURE)
        vals["COOKIE_SECURE"] = d.COOKIE_SECURE
    tok = str(vals["REGISTRATION_INVITE_TOKEN"] or "")
    if tok and len(tok) < 16:
        # Warning only here: the fail-closed gate is the startup check in
        # backend/main.py lifespan (refuses to start with <16 chars).
        # Empty token path unchanged (B11 scope).
        log.warning("REGISTRATION_INVITE_TOKEN is set but short (%d chars); server refuses to start with <16 chars, use openssl rand -hex 32", len(tok))
    cfg = Config(**vals)
    _CACHE = (key, cfg)
    return cfg
