import asyncio
import random

import httpx

MAX_RETRIES = 5


class AmazonClient:
    def __init__(self, base_url: str, limiter, transport=None):
        self.http = httpx.AsyncClient(base_url=base_url, timeout=10, transport=transport)
        self.limiter = limiter
        self.stats = {"requests": 0, "retries": 0, "throttled_429": 0}

    async def get(self, path: str, shop_id: str, endpoint: str, **params):
        for attempt in range(MAX_RETRIES + 1):
            wait = await self.limiter.acquire(f"rl:{shop_id}:{endpoint}")
            if wait > 0:
                await asyncio.sleep(wait)

            self.stats["requests"] += 1
            resp = await self.http.get(path, params=params, headers={"x-shop-id": shop_id})
            if resp.status_code == 429:
                self.stats["throttled_429"] += 1
            if resp.status_code != 429 and resp.status_code < 500:
                resp.raise_for_status()
                return resp.json()

            if attempt == MAX_RETRIES:
                break
            self.stats["retries"] += 1
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                delay = float(retry_after)
            else:
                delay = min(30, 2 ** attempt) * random.uniform(0.5, 1.5)
            await asyncio.sleep(delay)

        raise RuntimeError(f"giving up after retries: {path}")
