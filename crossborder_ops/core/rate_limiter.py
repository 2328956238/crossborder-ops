import time

LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = burst
  ts = now
end
tokens = math.min(burst, tokens + (now - ts) * rate)
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = (1 - tokens) / rate
end
redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, 120)
return tostring(wait)
"""


class RedisLimiter:
    def __init__(self, client, rate: float, burst: int):
        self.client = client
        self.rate = rate
        self.burst = burst
        self.script = client.register_script(LUA)

    async def acquire(self, key: str) -> float:
        wait = await self.script(keys=[key], args=[self.rate, self.burst, time.time()])
        return float(wait)
