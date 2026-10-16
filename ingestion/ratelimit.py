"""Redis sliding-window rate limiting for inbound alerts.

Each service has its own window. If Redis is unavailable the limiter fails
open (alerts are allowed) and logs a warning, so an outage of the cache does
not block incident detection.
"""

from __future__ import annotations

import time
import uuid

import redis

from app.config import settings
from observability.logging import get_logger

_CLIENT: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _CLIENT


class SlidingWindowRateLimiter:
    def __init__(self, client: redis.Redis, limit: int, window_seconds: int) -> None:
        self._client = client
        self._limit = limit
        self._window = window_seconds

    @staticmethod
    def _key(service: str) -> str:
        return f"ratelimit:alerts:{service}"

    def allow(self, service: str) -> bool:
        now = time.time()
        redis_key = self._key(service)
        member = f"{now:.6f}-{uuid.uuid4().hex}"
        try:
            pipe = self._client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, now - self._window)
            pipe.zadd(redis_key, {member: now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, self._window)
            _, _, count, _ = pipe.execute()
        except redis.RedisError as exc:
            get_logger(stage="ratelimit").warning(f"redis unavailable; allowing alert: {exc}")
            return True
        return int(count) <= self._limit


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(
        get_client(),
        limit=settings.alert_rate_limit_per_minute,
        window_seconds=settings.alert_rate_limit_window_seconds,
    )
