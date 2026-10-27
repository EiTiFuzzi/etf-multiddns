"""
Tiny in-memory brute-force protection for the Web UI's password/2FA checks.

Counts FAILED attempts per key (normally the client IP) inside a sliding
time window; once a key has used up its allowance it is blocked until the
oldest counted failure ages out of the window. A successful attempt clears
that key's counter.

Deliberately simple: state lives in memory only (the container runs a single
gunicorn worker, see the Dockerfile, so one process sees every request) and
is lost on restart. Behind a reverse proxy every request arrives from the
proxy's address, so there all clients share one allowance - that errs on
the safe side (an attacker can lock the login for a few minutes, but cannot
guess passwords or 2FA codes faster).
"""

from __future__ import annotations

import threading
import time
from collections import deque


class FailureThrottle:
    def __init__(self, max_failures: int, window_seconds: float, *, max_keys: int = 4096) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self.max_keys = max_keys
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        stamps = self._failures.get(key)
        if stamps is None:
            return deque()
        while stamps and now - stamps[0] >= self.window:
            stamps.popleft()
        if not stamps:
            del self._failures[key]
            return deque()
        return stamps

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Seconds until the key may try again - 0 if it isn't blocked."""
        now = time.monotonic() if now is None else now
        with self._lock:
            stamps = self._prune(key, now)
            if len(stamps) < self.max_failures:
                return 0
            return max(1, int(stamps[0] + self.window - now) + 1)

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            if key not in self._failures and len(self._failures) >= self.max_keys:
                # Bound memory use against an attacker rotating through many
                # source addresses: drop expired keys first, and if that
                # isn't enough, the oldest one.
                for existing in list(self._failures):
                    self._prune(existing, now)  # drops the key itself once empty
                if len(self._failures) >= self.max_keys:
                    oldest = min(self._failures, key=lambda k: self._failures[k][-1])
                    del self._failures[oldest]
            self._failures.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
