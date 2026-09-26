from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

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
    REGISTRATION: str = "open"
    REGISTRATION_INVITE_TOKEN: str = ""
    SESSION_SECONDS: int = 1209600
    MAX_DOCS_PER_USER: int = 100
    MAX_BYTES_PER_USER: int = 524288000
    MAX_FILES_PER_DOC: int = 200
    RATE_LOGIN_PER_MIN: int = 10
    RATE_REGISTER_PER_HOUR: int = 20


def _int(v, d: int) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return d


def _bool(v, d: bool) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return d


def _path(v, d: Path) -> Path:
    if v is None or str(v) == "":
        return d
    p = Path(str(v))
    return p if p.is_absolute() else ROOT / p


def load() -> Config:
    c = Config()
    try:
        with open(CONFIG_PATH, "rb") as f:
            raw = tomllib.load(f)
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
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
    if "RATE_LOGIN_PER_MIN" in raw:
        c.RATE_LOGIN_PER_MIN = _int(raw["RATE_LOGIN_PER_MIN"], c.RATE_LOGIN_PER_MIN)
    if e("RATE_LOGIN_PER_MIN") is not None:
        c.RATE_LOGIN_PER_MIN = _int(e("RATE_LOGIN_PER_MIN"), c.RATE_LOGIN_PER_MIN)
    if "RATE_REGISTER_PER_HOUR" in raw:
        c.RATE_REGISTER_PER_HOUR = _int(raw["RATE_REGISTER_PER_HOUR"], c.RATE_REGISTER_PER_HOUR)
    if e("RATE_REGISTER_PER_HOUR") is not None:
        c.RATE_REGISTER_PER_HOUR = _int(e("RATE_REGISTER_PER_HOUR"), c.RATE_REGISTER_PER_HOUR)
    return c
