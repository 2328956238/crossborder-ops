# -*- coding: utf-8 -*-
"""Redis 令牌桶限流（fakeredis + Lua）。"""
from __future__ import annotations

from crossborder_ops.core.rate_limiter import RedisLimiter


async def test_token_bucket_first_call_no_wait(redis_client):
    limiter = RedisLimiter(redis_client, rate=1, burst=1)
    assert float(await limiter.acquire("rl:test:S1")) == 0.0


async def test_token_bucket_blocks_when_empty(redis_client):
    limiter = RedisLimiter(redis_client, rate=1, burst=1)
    await limiter.acquire("rl:test:S1")
    wait = float(await limiter.acquire("rl:test:S1"))
    assert 0 < wait <= 1.0


async def test_buckets_are_isolated_per_key(redis_client):
    limiter = RedisLimiter(redis_client, rate=1, burst=1)
    await limiter.acquire("rl:S1:orders")
    assert float(await limiter.acquire("rl:S2:orders")) == 0.0
