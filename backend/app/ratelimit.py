"""Tiny in-memory sliding-window rate limiter, keyed by client IP.

Good enough for a single API instance. With several instances you would move
the counters to Redis (see README trade-offs)."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from .errors import ApiError


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        q = self.hits[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            retry_after = max(1, int(self.window - (now - q[0])))
            raise ApiError(
                429, "rate_limited",
                f"Too many requests. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
        q.append(now)


def client_ip(request: Request) -> str:
    # Behind a proxy the real client is the first X-Forwarded-For entry.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
