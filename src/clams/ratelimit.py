"""In-memory sliding-window limiter. The app runs as one uvicorn process, so
memory is the right place; a restart simply forgets recent attempts."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class Limiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def hit(self, key: str, limit: int, window: float) -> bool:
        """Record an attempt; False when the key is over its limit."""
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def _sweep(self, now: float) -> None:
        # Drop idle keys every few minutes so memory doesn't creep.
        if now - self._last_sweep < 300:
            return
        self._last_sweep = now
        for key in [k for k, q in self._hits.items() if not q or now - q[-1] > 3600]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = Limiter()
