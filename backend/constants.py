"""Central limits: single source for main + sync (no import cycle)."""
ENTRY = "__doc__.typ"  # compile entry file name in temp dirs; a document is its title, never a file
MAX_TXT = 200_000
MAX_FOLDER_DEPTH = 2  # folder levels inside a project (a/b/file.typ); projects themselves do not count
SNAP_MAX = 50
SNAP_EVERY = 900
# Project versions re-embed every attachment (base64 inside the JSON
# blob), so each version roughly duplicates the project size. Automatic
# (system-created, kind='auto') versions are therefore pruned on every
# version write down to the project's auto_keep newest. kind='manual' rows
# are never auto-pruned. Both defaults are per-project settings
# (project_versioning), bounded by the ranges below.
AUTO_SNAP_MINUTES = 30    # minimum gap between automatic versions (0 = every change)
AUTO_SNAP_KEEP = 15       # automatic versions kept
AUTO_SNAP_MINUTES_RANGE = (0, 10080)
AUTO_SNAP_KEEP_RANGE = (1, 200)
AWARE_MAX = 64 * 1024
CACHE_TTL = 10.0
TITLE_MAX = 100
FOLDER_MAX = 40
INVITE_SECONDS = 7 * 86400
EXPORT_MAX = 100 * 1024 * 1024
UPLOAD_MAX = 10 * 1024 * 1024
# Request-body ceiling for /api + /mcp: Content-Length gate in main + chunked
# read cap for the heaviest endpoints (read_capped_body).
MAX_REQUEST_BYTES = 32 * 1024 * 1024
# Per-doc export formats (REST POST /api/docs/{id}/export + MCP export tool).
EXPORT_FORMATS = ("pdf", "svg", "png", "zip")
PBKDF2_ROUNDS = 300_000
SESSION_RECHECK_TTL = 60.0
LOCK_NAME = ".lock"
ROOMS_MAX = 500
# Config wins: RATE_DEFAULTS only fallback/docs, real limits come from backend/config.py.
RATE_DEFAULTS = {"login": (10, 60), "register": (20, 3600), "auth": (180, 60), "join": (30, 60), "read": (60, 60),
                 "search": (120, 60), "files": (60, 60), "file_read": (600, 60), "sidebar": (300, 60), "files_list": (600, 60), "save": (90, 60), "comments": (120, 60),
                 "export": (10, 60), "export_doc": (30, 60), "pw": (10, 60), "invite": (10, 60), "share": (20, 60),
                 "snapshots": (120, 60), "create": (60, 60), "duplicate": (30, 60),
                 "avatar": (20, 60), "folders": (60, 60), "keys": (60, 60), "mcp": (240, 60),
                 "rename": (60, 60), "delete": (60, 60), "restore": (60, 60),
                 "move": (60, 60), "templates": (90, 60), "tplfolders": (60, 60)}

# Account validation (used by schemas and auth routes)
NAME_RE = r"[A-Za-z0-9_-]{2,20}"
MIN_PW = 8
MAX_PW = 200
