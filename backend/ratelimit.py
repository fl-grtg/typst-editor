from __future__ import annotations

import threading
import time

_hits: dict[str, list[float]] = {}
_lock = threading.Lock()


def clear() -> None:
    with _lock:
        _hits.clear()


def allow(key: str, limit: int, window_s: int) -> bool:
    now = time.monotonic()
    with _lock:
        if len(_hits) > 20000:  # Notbremse: aelteste Haelfte raus statt alles (weniger Reset-Fläche)
            for k in list(_hits)[:10000]:
                del _hits[k]
        lst = [t for t in _hits.get(key, []) if now - t < window_s]
        if len(lst) >= limit:
            _hits[key] = lst
            return False
        lst.append(now)
        _hits[key] = lst
        return True
