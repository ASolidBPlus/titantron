import asyncio
import time


class RateLimiter:
    """Token bucket rate limiter for web scraping requests."""

    def __init__(self, requests_per_second: float = 0.5, burst: int = 3):
        self.rate = requests_per_second
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
                self.last_refill = time.monotonic()
            else:
                self.tokens -= 1
