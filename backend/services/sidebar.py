"""Per-user sidebar event queues (SSE)."""
from __future__ import annotations

import logging

log = logging.getLogger("typst.main")


_SIDEBAR_Q: dict[str, set] = {}  # user -> {(loop, queue)} live /api/events streams (single worker)


def notify_sidebar(user: str) -> None:
    # Own list changed elsewhere (MCP, other tab): wake every open sidebar stream of this user.
    # Def endpoints run in a worker thread: schedule into the loop thread-safely.
    # Coalesce: one pending event is enough, sidebar() refetches everything anyway.
    try:
        _targets = list(_SIDEBAR_Q.get(user, ()))
    except RuntimeError:
        log.debug("notify_sidebar race, next mutation retries")
        return  # set mutated concurrently; the next mutation notifies again
    for _loop, _q in _targets:
        try:
            if _q.empty():
                _loop.call_soon_threadsafe(_q.put_nowait, "sidebar")
        except Exception as e:
            log.debug("notify_sidebar dropped: %s", e)
