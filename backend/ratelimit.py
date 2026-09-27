from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

_hits: dict[str, list[float]] = {}
_lock = threading.Lock()


def clear() -> None:
    with _lock:
        _hits.clear()


def allow(key: str, limit: int, window_s: int) -> bool:
    now = time.monotonic()
    with _lock:
        if len(_hits) > 20000:
            n = 0
            for k, v in list(_hits.items()):
                if n >= 5000:
                    break
                if not v or now - max(v) > 3600:
                    del _hits[k]
                    n += 1
            if n:
                log.debug("ratelimit evicted %d expired buckets", n)
            else:
                for k in sorted(_hits, key=lambda k: max(_hits[k]) if _hits[k] else 0)[:5000]:
                    del _hits[k]
                log.debug("ratelimit evicted 5000 oldest buckets")
        lst = [t for t in _hits.get(key, []) if now - t < window_s]
        if len(lst) >= limit:
            _hits[key] = lst
            return False
        lst.append(now)
        _hits[key] = lst
        return True
