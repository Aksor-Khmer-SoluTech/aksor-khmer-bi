"""A per-key sliding-window rate limiter -- what keeps one API client (app/clients.py)
from making the server fetch and render without bound.

The window is in memory, so the limit is per process.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

WINDOW_SECONDS = 60.0
# Beyond this many distinct keys, forget the ones that have gone quiet.
_PRUNE_ABOVE = 10_000


class RateLimiter:
    """A sliding one-minute window of request times per key."""

    def __init__(self, limit: Callable[[], int]) -> None:
        """`limit` is read on every request, so an env change or a test applies at once."""
        self._limit = limit
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str, *, now: float | None = None) -> float | None:
        """Record a request from `key`; None if it's within the limit, else the seconds until it would be."""
        now = time.monotonic() if now is None else now
        limit = self._limit()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return max(WINDOW_SECONDS - (now - hits[0]), 1.0)
            hits.append(now)
            if len(self._hits) > _PRUNE_ABOVE:
                self._forget_quiet(now)
            return None

    def _forget_quiet(self, now: float) -> None:
        for key in [k for k, q in self._hits.items() if not q or now - q[-1] >= WINDOW_SECONDS]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
