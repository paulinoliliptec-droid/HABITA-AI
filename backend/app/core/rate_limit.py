"""Spend boundary for endpoints that trigger paid upstream calls.

In-process, so it is exact only while the service runs a single instance (the
preview is pinned to max-instances=1). A multi-instance deployment needs a shared
limiter (gateway or Redis) and a provider-side daily quota as the hard cap.
"""

import asyncio
import math
import time

from app.core.errors import RateLimitedError


class TokenBucket:
    def __init__(self, rate_per_minute: float, burst: int, clock=time.monotonic) -> None:
        self._rate = rate_per_minute / 60.0
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._updated = clock()

    def take(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
        self._updated = now
        if self._tokens < 1:
            retry_after = math.ceil((1 - self._tokens) / self._rate)
            raise RateLimitedError(
                "HABITA is handling a lot of lookups right now. Please try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )
        self._tokens -= 1


class ResolutionLimiter:
    """Admission control: a request budget plus a cap on concurrent upstream work."""

    def __init__(self, rate_per_minute: float, burst: int, max_concurrency: int) -> None:
        self._bucket = TokenBucket(rate_per_minute, burst)
        self._slots = asyncio.Semaphore(max_concurrency)

    def admit(self) -> asyncio.Semaphore:
        self._bucket.take()
        return self._slots
