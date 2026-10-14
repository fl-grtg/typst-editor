"""Central limits: single source for main + sync (no import cycle)."""
MAX_TXT = 200_000
SNAP_MAX = 50
SNAP_EVERY = 900
SAVE_EVERY = 1.0
AWARE_MAX = 64 * 1024
CACHE_TTL = 10.0
TITLE_MAX = 100
FOLDER_MAX = 40
INVITE_SECONDS = 7 * 86400
EXPORT_MAX = 100 * 1024 * 1024
UPLOAD_MAX = 10 * 1024 * 1024
# Per-doc export formats (REST POST /api/docs/{id}/export + MCP export tool).
EXPORT_FORMATS = ("pdf", "svg", "png", "zip")
PBKDF2_ROUNDS = 300_000
SESSION_RECHECK_TTL = 60.0
LOCK_NAME = ".lock"
ROOMS_MAX = 500
# Config wins: RATE_DEFAULTS only fallback/docs, real limits come from backend/config.py.
RATE_DEFAULTS = {"login": (10, 60), "register": (20, 3600), "auth": (60, 60), "join": (30, 60),
                 "search": (60, 60), "files": (20, 60), "files_list": (120, 60), "save": (30, 60), "comments": (30, 60),
                 "export": (5, 60), "export_doc": (10, 60), "pw": (10, 60), "invite": (10, 60), "share": (10, 60),
                 "snapshots": (60, 60), "create": (20, 60), "duplicate": (10, 60),
                 "avatar": (10, 60), "folders": (20, 60), "keys": (30, 60), "mcp": (60, 60),
                 "rename": (10, 60), "delete": (10, 60), "restore": (10, 60),
                 "move": (20, 60), "templates": (20, 60), "tplfolders": (20, 60)}

# Account validation (used by schemas and auth routes)
NAME_RE = r"[A-Za-z0-9_-]{2,20}"
MIN_PW = 8
MAX_PW = 200
