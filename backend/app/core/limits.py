"""Generation request protection: per-minute rate limit, daily quota and request-size limits.

These are the application's own guard; a public deployment should still limit at its ingress.
"""
import ipaddress
import logging
import math
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from fastapi import HTTPException
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from app.core.config import Settings, get_settings

logger = logging.getLogger("social.limits")

GENERATIONS_PATH = "/api/v1/generations"
MINUTE = 60
DAY = 86_400
MINUTE_DETAIL = "Too many generation requests. Please wait a minute and try again."


def request_size_limit(settings) -> int:
    """Largest request the API accepts: the biggest product file plus an optional music track and
    logo, plus 1 MB for multipart framing and form fields. The Next.js proxy and Caddy must allow at
    least this much (tests/test_upload.py checks both), or valid uploads are cut off mid-request."""
    largest = max(settings.max_upload_size_mb, settings.max_video_upload_size_mb)
    return (largest + settings.max_music_upload_size_mb + settings.max_logo_upload_size_mb + 1) * 1024 * 1024


# ---------- client identity ----------

def _parse_ip(value: str):
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    # Dual-stack sockets report IPv4 peers as ::ffff:a.b.c.d; compare them as IPv4.
    if address.version == 6 and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


@lru_cache(maxsize=8)
def _networks(trusted_proxies: str) -> tuple:
    return tuple(ipaddress.ip_network(item.strip(), strict=False) for item in trusted_proxies.split(",") if item.strip())


def client_address(scope, trusted_proxies: str) -> str:
    """The client to count against: the socket peer, or, behind trusted proxies, the forwarded client.

    X-Forwarded-For is read only when the direct peer is a trusted proxy. Each trusted proxy appends
    the address it received the request from, so walking from the right and skipping trusted hops
    reaches the first address our own infrastructure vouches for; entries left of it are
    client-supplied and may be spoofed.
    """
    peer = (scope.get("client") or ("unknown", 0))[0]
    networks = _networks(trusted_proxies)

    def trusted(value):
        address = _parse_ip(value)
        return address is not None and any(address in network for network in networks)

    def normalised(value):
        address = _parse_ip(value)
        if address is None:
            return value.strip()[:100]
        # A subscriber usually holds a whole IPv6 /64; count the block so rotating addresses can't escape.
        return str(ipaddress.ip_network(f"{address}/64", strict=False)) if address.version == 6 else str(address)

    if not networks or not trusted(peer):
        return normalised(peer)
    forwarded = ",".join(value.decode("latin-1") for name, value in scope["headers"] if name == b"x-forwarded-for")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not trusted(hop):
            return normalised(hop)
    return normalised(hops[0] if hops else peer)


# ---------- counter stores ----------

class CounterUnavailable(Exception):
    """The shared counter could not be reached."""


class CounterStore(Protocol):
    async def increment(self, key: str, ttl: int) -> int:
        """Atomically add one to `key` (expiring after `ttl` seconds) and return the new count."""


class MemoryCounterStore:
    """Per-process counters: for local development and tests; N processes allow N times the limit."""

    def __init__(self, clock=time.time, max_keys: int = 50_000):
        self.clock, self.max_keys = clock, max_keys
        self.counts: dict[str, tuple[int, float]] = {}

    async def increment(self, key: str, ttl: int) -> int:
        now = self.clock()
        if key not in self.counts and len(self.counts) >= self.max_keys:
            # Forget expired windows so arbitrary source addresses cannot grow memory indefinitely.
            self.counts = {k: entry for k, entry in self.counts.items() if entry[1] > now}
            if len(self.counts) >= self.max_keys:
                return sys.maxsize  # Still full: refuse new clients rather than grow.
        count, expires = self.counts.get(key, (0, 0.0))
        if expires <= now:
            count, expires = 0, now + ttl
        self.counts[key] = (count + 1, expires)
        return count + 1


class RedisCounterStore:
    """Counters shared by every API process through Redis."""

    def __init__(self, client):
        self.client = client

    @classmethod
    def from_url(cls, url: str) -> "RedisCounterStore":
        # Short timeouts and no retries: a dead Redis must not stall generation requests.
        return cls(Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5, retry=Retry(NoBackoff(), 0)))

    async def increment(self, key: str, ttl: int) -> int:
        try:
            # MULTI/EXEC: the increment and its expiry apply together, so no counter is left immortal.
            async with self.client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, ttl)
                count, _ = await pipe.execute()
            return int(count)
        except (RedisError, OSError, TimeoutError) as exc:
            raise CounterUnavailable(type(exc).__name__) from exc


# ---------- limiter ----------

@dataclass(frozen=True)
class Rejection:
    detail: str
    retry_after: int


class GenerationRateLimiter:
    """Fixed-window counters: one per client per clock minute and one per client per UTC day.

    Windows are aligned to the wall clock, so the key names every process computes agree and a
    single atomic INCR is enough; the trade-off is that a client can burst up to twice the
    per-minute limit across a minute boundary.
    """

    def __init__(self, store: CounterStore, clock=time.time):
        self.store, self.clock = store, clock
        self._last_warning = -math.inf

    async def check(self, client: str, per_minute: int, per_day: int) -> Rejection | None:
        now = self.clock()
        try:
            rejection = await self._hit(client, "minute", MINUTE, now, per_minute, MINUTE_DETAIL)
            # A request refused per minute is not charged to the daily quota.
            if rejection is None and per_day > 0:
                detail = (f"Daily generation limit reached ({per_day} per day). "
                          "It resets at midnight UTC; please try again tomorrow.")
                rejection = await self._hit(client, "day", DAY, now, per_day, detail)
            return rejection
        except CounterUnavailable as exc:
            # Fail open: availability over strictness. Ingress limits remain the outer guard, and
            # the warning is rate limited so an outage does not flood the logs.
            if time.monotonic() - self._last_warning >= 60:
                self._last_warning = time.monotonic()
                logger.warning("Rate limit store unavailable (%s); failing open", exc)
            return None

    async def _hit(self, client, name, window, now, limit, detail) -> Rejection | None:
        index = int(now // window)
        remaining = (index + 1) * window - now
        count = await self.store.increment(f"ratelimit:generations:{name}:{client}:{index}", math.ceil(remaining) + 1)
        return Rejection(detail, max(1, math.ceil(remaining))) if count > limit else None


def build_limiter(settings: Settings) -> GenerationRateLimiter:
    if settings.rate_limit_backend == "redis":
        return GenerationRateLimiter(RedisCounterStore.from_url(settings.redis_url))
    return GenerationRateLimiter(MemoryCounterStore())


# ---------- middleware ----------

class UploadLimitsMiddleware:
    """Rate limits, the daily quota and request-size limits for generation POSTs (create, retry, variants)."""

    def __init__(self, app, limiter: GenerationRateLimiter | None = None):
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith(GENERATIONS_PATH):
            return await self.app(scope, receive, send)
        settings = get_settings()
        if self.limiter is None:
            self.limiter = build_limiter(settings)
        client = client_address(scope, settings.trusted_proxies)
        rejection = await self.limiter.check(client, settings.requests_per_minute, settings.daily_generation_quota)
        if rejection is not None:
            return await JSONResponse({"detail": rejection.detail}, 429,
                                      headers={"Retry-After": str(rejection.retry_after)})(scope, receive, send)
        await self._limit_size(settings, scope, receive, send)

    async def _limit_size(self, settings, scope, receive, send):
        # Per-type limits are enforced while streaming; this is the outer bound for any request.
        limit = request_size_limit(settings)
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid request length."}, 400)(scope, receive, send)
        if declared > limit:
            return await JSONResponse({"detail": "The upload exceeds the request size limit."}, 413)(scope, receive, send)
        size = 0
        exceeded = False
        async def limited_receive():
            nonlocal size, exceeded
            message = await receive()
            size += len(message.get("body", b""))
            if size > limit:
                exceeded = True
                raise HTTPException(413, "The upload exceeds the request size limit.")
            return message
        async def limited_send(message):
            # Multipart parsers may map a receive exception to 400; keep the actual limit error.
            if exceeded:
                if message["type"] == "http.response.start":
                    await JSONResponse({"detail": "The upload exceeds the request size limit."}, 413)(scope, receive, send)
                return
            await send(message)
        await self.app(scope, limited_receive, limited_send)
