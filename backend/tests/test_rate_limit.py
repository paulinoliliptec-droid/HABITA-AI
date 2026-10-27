import pytest

from app.core.errors import RateLimitedError
from app.core.rate_limit import TokenBucket


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_bucket_allows_burst_then_limits_and_recovers():
    clock = Clock()
    bucket = TokenBucket(rate_per_minute=60, burst=2, clock=clock)
    bucket.take()
    bucket.take()
    with pytest.raises(RateLimitedError) as exc:
        bucket.take()
    assert exc.value.headers == {"Retry-After": "1"}

    clock.now += 1.0
    bucket.take()  # one token refilled after a second at 60/min
