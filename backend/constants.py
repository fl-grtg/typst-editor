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
PBKDF2_ROUNDS = 300_000
SESSION_RECHECK_TTL = 60.0
LOCK_NAME = ".lock"
ROOMS_MAX = 500
# Config wins: RATE_DEFAULTS only fallback/docs, real limits come from backend/config.py.
RATE_DEFAULTS = {"login": (10, 60), "register": (20, 3600), "auth": (60, 60), "join": (30, 60),
                 "search": (60, 60), "files": (20, 60), "files_list": (120, 60), "save": (30, 60), "comments": (30, 60),
                 "export": (5, 60), "pw": (10, 60), "invite": (10, 60), "share": (10, 60),
                 "snapshots": (60, 60), "create": (20, 60), "duplicate": (10, 60),
                 "avatar": (10, 60), "folders": (20, 60)}
