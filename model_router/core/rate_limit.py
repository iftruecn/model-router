"""
Per-key rate limiting for Model Router v1.7.0.

Token bucket algorithm, zero external dependencies.
Configurable via environment variables:
  MODEL_ROUTER_RATE_LIMIT   — requests per minute per key (default: 60)
  MODEL_ROUTER_RATE_BURST   — burst size (default: 10)

Usage:
    from model_router.core.rate_limit import RateLimiter, rate_limit_middleware
    # Add as FastAPI middleware in app.py
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """Token bucket for a single key."""
    rate: float          # tokens per second
    burst: int           # max tokens
    tokens: float = 0.0
    last_refill: float = 0.0

    def __post_init__(self):
        self.tokens = float(self.burst)
        self.last_refill = time.monotonic()

    def allow(self) -> bool:
        """Check if one request is allowed (consume 1 token)."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    @property
    def retry_after(self) -> float:
        """Seconds until next token available."""
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.rate


class RateLimiter:
    """
    Per-key rate limiter using token bucket algorithm.

    Thread-safe enough for asyncio (single-threaded event loop).
    """

    def __init__(
        self,
        rpm: int = 60,
        burst: int = 10,
        enabled: bool = True,
    ):
        self._rpm = rpm
        self._burst = burst
        self._rate = rpm / 60.0  # tokens per second
        self._enabled = enabled
        self._buckets: dict[str, TokenBucket] = {}
        # Stats
        self._total_requests = 0
        self._total_rejected = 0

    def check(self, key_id: str) -> tuple[bool, float]:
        """
        Check if request is allowed for the given key.

        Returns (allowed, retry_after_seconds).
        """
        if not self._enabled:
            return True, 0.0

        self._total_requests += 1

        if key_id not in self._buckets:
            self._buckets[key_id] = TokenBucket(
                rate=self._rate, burst=self._burst,
            )

        bucket = self._buckets[key_id]
        if bucket.allow():
            return True, 0.0

        self._total_rejected += 1
        return False, bucket.retry_after

    def get_stats(self) -> dict:
        """Rate limiter stats for /admin/learning."""
        return {
            "enabled": self._enabled,
            "rpm": self._rpm,
            "burst": self._burst,
            "tracked_keys": len(self._buckets),
            "total_requests": self._total_requests,
            "total_rejected": self._total_rejected,
        }

    def reset(self, key_id: Optional[str] = None) -> None:
        """Reset bucket for a key, or all keys."""
        if key_id:
            self._buckets.pop(key_id, None)
        else:
            self._buckets.clear()


# Global singleton (configured via env vars)
import os as _os
_rate_limit = int(_os.environ.get("MODEL_ROUTER_RATE_LIMIT", "0"))
_rate_limiter = RateLimiter(
    rpm=_rate_limit if _rate_limit > 0 else 60,
    burst=int(_os.environ.get("MODEL_ROUTER_RATE_BURST", "10")),
    enabled=_rate_limit > 0,
)
