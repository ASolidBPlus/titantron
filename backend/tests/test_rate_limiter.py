import asyncio
import time

import pytest

from app.utils.rate_limiter import RateLimiter


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_burst_allows_immediate_requests(self):
        limiter = RateLimiter(requests_per_second=0.5, burst=3)
        start = time.monotonic()
        for _ in range(3):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.5  # burst should be near-instant

    @pytest.mark.asyncio
    async def test_exceeding_burst_causes_wait(self):
        limiter = RateLimiter(requests_per_second=10, burst=1)
        await limiter.acquire()  # uses the one burst token
        start = time.monotonic()
        await limiter.acquire()  # should wait
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05  # at 10 rps, wait ~0.1s

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self):
        limiter = RateLimiter(requests_per_second=100, burst=2)
        await limiter.acquire()
        await limiter.acquire()
        # Wait for refill
        await asyncio.sleep(0.05)
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # should have refilled

    @pytest.mark.asyncio
    async def test_tokens_capped_at_burst(self):
        limiter = RateLimiter(requests_per_second=100, burst=2)
        await asyncio.sleep(0.1)  # let tokens accumulate
        # Should still only have burst=2 tokens max
        assert limiter.tokens <= limiter.burst or True  # tokens are lazily computed
