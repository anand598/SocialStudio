import asyncio
import logging
import os
import uuid
import pytest
import redis.exceptions
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.core.config import Settings, get_settings
from app.core.limits import (GenerationRateLimiter, MemoryCounterStore, RedisCounterStore, UploadLimitsMiddleware,
                             build_limiter, client_address)

DAY_START = 20_000 * 86_400  # midnight UTC
NOON = DAY_START + 12 * 3600


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FakeRedis:
    """Implements only the commands RedisCounterStore uses (MULTI pipeline with INCR + EXPIRE)."""

    def __init__(self):
        self.values, self.ttls = {}, {}

    def pipeline(self, transaction=True):
        assert transaction, "counting must be atomic"
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self.redis, self.commands = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.commands.clear()

    def incr(self, key):
        self.commands.append(("incr", key))
        return self

    def expire(self, key, seconds):
        self.commands.append(("expire", key, seconds))
        return self

    async def execute(self):
        results = []
        for command, key, *args in self.commands:
            if command == "incr":
                self.redis.values[key] = self.redis.values.get(key, 0) + 1
                results.append(self.redis.values[key])
            else:
                self.redis.ttls[key] = args[0]
                results.append(True)
        return results


class DeadRedis:
    def pipeline(self, transaction=True):
        return DeadPipeline()


class DeadPipeline(FakePipeline):
    def __init__(self):
        super().__init__(None)

    async def execute(self):
        raise redis.exceptions.ConnectionError("Error 111 connecting to redis:6379. Connection refused.")


@pytest.fixture
def limits(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "requests_per_minute", 3)
    monkeypatch.setattr(settings, "daily_generation_quota", 0)
    monkeypatch.setattr(settings, "trusted_proxies", "")
    return settings


def make_app(limiter):
    inner = FastAPI()

    @inner.post("/api/v1/generations")
    def create():
        return JSONResponse({"id": "new"}, 202)

    @inner.get("/api/v1/generations")
    def history():
        return []

    @inner.post("/api/v1/generations/{job_id}/retry")
    def retry(job_id: str):
        return JSONResponse({"id": job_id}, 202)

    @inner.post("/api/v1/generations/{job_id}/variants")
    def variants(job_id: str):
        return JSONResponse({"id": "variant"}, 202)

    @inner.post("/api/v1/feedback")
    def other():
        return {"ok": True}

    return UploadLimitsMiddleware(inner, limiter=limiter)


def post(client, path="/api/v1/generations", **kwargs):
    return client.post(path, content=b"{}", **kwargs)


# ---------- per-minute limit ----------

def test_per_minute_limit_with_retry_after_until_the_window_resets(limits):
    clock = Clock(NOON + 15)
    with TestClient(make_app(GenerationRateLimiter(MemoryCounterStore(clock), clock))) as client:
        assert [post(client).status_code for _ in range(3)] == [202, 202, 202]
        response = post(client)
        assert response.status_code == 429
        assert "minute" in response.json()["detail"]
        assert "daily" not in response.json()["detail"].lower()
        assert response.headers["Retry-After"] == "45"
        clock.now = NOON + 60
        assert post(client).status_code == 202


def test_counting_is_shared_between_processes_using_redis(limits):
    shared = FakeRedis()
    clock = Clock(NOON)
    # Two middleware stacks with their own store objects, like two API processes on one Redis.
    first = TestClient(make_app(GenerationRateLimiter(RedisCounterStore(shared), clock)))
    second = TestClient(make_app(GenerationRateLimiter(RedisCounterStore(shared), clock)))
    assert post(first).status_code == 202
    assert post(second).status_code == 202
    assert post(first).status_code == 202
    assert post(second).status_code == 429
    assert post(first).status_code == 429
    assert all(0 < ttl <= 61 for ttl in shared.ttls.values())


def test_only_generation_posts_are_counted(limits):
    clock = Clock(NOON)
    with TestClient(make_app(GenerationRateLimiter(MemoryCounterStore(clock), clock))) as client:
        for _ in range(5):
            assert client.get("/api/v1/generations").status_code == 200
            assert post(client, "/api/v1/feedback").status_code == 200
        assert post(client).status_code == 202
        assert post(client, "/api/v1/generations/abc/retry").status_code == 202
        assert post(client, "/api/v1/generations/abc/variants").status_code == 202
        assert post(client, "/api/v1/generations/abc/variants").status_code == 429
        assert post(client, "/api/v1/generations/abc/retry").status_code == 429


# ---------- daily quota ----------

def test_daily_quota_rejects_with_its_own_message_until_midnight_utc(limits, monkeypatch):
    monkeypatch.setattr(limits, "requests_per_minute", 100)
    monkeypatch.setattr(limits, "daily_generation_quota", 3)
    clock = Clock(DAY_START + 23 * 3600)
    with TestClient(make_app(GenerationRateLimiter(MemoryCounterStore(clock), clock))) as client:
        assert [post(client).status_code for _ in range(3)] == [202, 202, 202]
        response = post(client)
        assert response.status_code == 429
        detail = response.json()["detail"]
        assert "daily" in detail.lower() and "3" in detail
        assert response.headers["Retry-After"] == "3600"
        clock.now = DAY_START + 86_400
        assert post(client).status_code == 202


def test_minute_rejections_do_not_use_up_the_daily_quota(limits, monkeypatch):
    monkeypatch.setattr(limits, "requests_per_minute", 1)
    monkeypatch.setattr(limits, "daily_generation_quota", 2)
    clock = Clock(NOON)
    with TestClient(make_app(GenerationRateLimiter(MemoryCounterStore(clock), clock))) as client:
        assert post(client).status_code == 202
        assert [post(client).status_code for _ in range(5)] == [429] * 5
        clock.now += 60
        assert post(client).status_code == 202
        clock.now += 60
        response = post(client)
        assert response.status_code == 429 and "daily" in response.json()["detail"].lower()


def test_quota_zero_disables_the_daily_cap(limits, monkeypatch):
    monkeypatch.setattr(limits, "requests_per_minute", 10)
    monkeypatch.setattr(limits, "daily_generation_quota", 0)
    clock = Clock(NOON)
    with TestClient(make_app(GenerationRateLimiter(MemoryCounterStore(clock), clock))) as client:
        for _ in range(30):
            assert [post(client).status_code for _ in range(10)] == [202] * 10
            clock.now += 60


# ---------- client identity ----------

def scope(peer, *forwarded):
    return {"client": (peer, 5000), "headers": [(b"x-forwarded-for", value.encode()) for value in forwarded]}


def test_forwarded_for_is_ignored_by_default_and_from_untrusted_peers():
    assert client_address(scope("198.51.100.4", "203.0.113.7"), "") == "198.51.100.4"
    assert client_address(scope("198.51.100.4", "203.0.113.7"), "172.16.0.0/12") == "198.51.100.4"


def test_trusted_proxy_by_address_and_by_cidr():
    assert client_address(scope("172.18.0.5", "203.0.113.7"), "172.18.0.5") == "203.0.113.7"
    assert client_address(scope("172.18.0.5", "203.0.113.7"), "10.0.0.0/8, 172.16.0.0/12") == "203.0.113.7"


def test_multiple_trusted_hops_and_spoofed_left_most_entries():
    trusted = "172.16.0.0/12,10.0.0.0/8"
    # Client-supplied junk on the left is skipped: the right-most untrusted hop was added by our proxy.
    assert client_address(scope("172.18.0.5", "1.1.1.1, 203.0.113.7, 10.1.2.3"), trusted) == "203.0.113.7"
    # Several header lines are one list, in order.
    assert client_address(scope("172.18.0.5", "1.1.1.1", "203.0.113.7, 10.1.2.3"), trusted) == "203.0.113.7"


def test_trusted_peer_without_forwarded_for_or_only_trusted_hops():
    assert client_address(scope("172.18.0.5"), "172.16.0.0/12") == "172.18.0.5"
    assert client_address(scope("172.18.0.5", "172.18.0.9, 10.0.0.2"), "172.16.0.0/12,10.0.0.0/8") == "172.18.0.9"


def test_ipv4_mapped_addresses_match_ipv4_networks():
    assert client_address(scope("::ffff:172.18.0.5", "::ffff:203.0.113.7"), "172.16.0.0/12") == "203.0.113.7"


def test_clients_behind_a_trusted_proxy_get_separate_buckets(limits, monkeypatch):
    monkeypatch.setattr(limits, "requests_per_minute", 1)
    monkeypatch.setattr(limits, "trusted_proxies", "172.16.0.0/12")
    clock = Clock(NOON)
    app = make_app(GenerationRateLimiter(MemoryCounterStore(clock), clock))
    with TestClient(app, client=("172.18.0.5", 4000)) as frontend:
        assert post(frontend, headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 202
        assert post(frontend, headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 429
        assert post(frontend, headers={"X-Forwarded-For": "203.0.113.8"}).status_code == 202
        # Rotating a spoofed left-most entry does not escape the bucket.
        assert post(frontend, headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.8"}).status_code == 429


def test_untrusted_peer_cannot_pick_its_bucket_with_forwarded_for(limits, monkeypatch):
    monkeypatch.setattr(limits, "requests_per_minute", 1)
    clock = Clock(NOON)
    with TestClient(make_app(GenerationRateLimiter(MemoryCounterStore(clock), clock)),
                    client=("198.51.100.4", 4000)) as client:
        assert post(client, headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 202
        assert post(client, headers={"X-Forwarded-For": "203.0.113.8"}).status_code == 429


def test_invalid_trusted_proxies_setting_is_rejected():
    with pytest.raises(ValidationError):
        Settings(trusted_proxies="172.16.0.0/12,not-a-network")
    assert Settings(trusted_proxies=" 10.0.0.0/8 , 172.18.0.5 ").trusted_proxies


# ---------- backends ----------

def test_redis_failure_fails_open_with_a_rate_limited_warning(limits, caplog):
    clock = Clock(NOON)
    with caplog.at_level(logging.WARNING, logger="social.limits"):
        with TestClient(make_app(GenerationRateLimiter(RedisCounterStore(DeadRedis()), clock))) as client:
            assert [post(client).status_code for _ in range(6)] == [202] * 6
    warnings = [record for record in caplog.records if record.name == "social.limits"]
    assert len(warnings) == 1
    assert "failing open" in warnings[0].getMessage()


def test_backend_is_chosen_from_settings(limits, monkeypatch):
    monkeypatch.setattr(limits, "rate_limit_backend", "memory")
    assert isinstance(build_limiter(limits).store, MemoryCounterStore)
    monkeypatch.setattr(limits, "rate_limit_backend", "redis")
    monkeypatch.setattr(limits, "redis_url", "redis://redis.invalid:6379/0")
    store = build_limiter(limits).store
    assert isinstance(store, RedisCounterStore)
    options = store.client.connection_pool.connection_kwargs
    assert options["socket_timeout"] <= 1 and options["socket_connect_timeout"] <= 1


def test_memory_store_forgets_expired_windows():
    clock = Clock(NOON)
    store = MemoryCounterStore(clock, max_keys=2)
    for name in ("a", "b"):
        assert asyncio.run(store.increment(name, 60)) == 1
    clock.now += 61
    assert asyncio.run(store.increment("c", 60)) == 1
    assert set(store.counts) == {"c"}


def test_shared_counting_with_a_real_redis(limits):
    """Integration check; skipped unless a Redis is reachable (RATE_LIMIT_TEST_REDIS_URL)."""
    from redis.asyncio import Redis
    url = os.environ.get("RATE_LIMIT_TEST_REDIS_URL", "redis://localhost:6379/15")

    async def scenario():
        clients = [Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5) for _ in range(2)]
        try:
            try:
                await clients[0].ping()
            except (redis.exceptions.RedisError, OSError):
                pytest.skip("no Redis reachable for the integration test")
            first, second = (GenerationRateLimiter(RedisCounterStore(client)) for client in clients)
            client_id = f"test-{uuid.uuid4()}"
            results = [await limiter.check(client_id, per_minute=2, per_day=3) for limiter in (first, second, first)]
            assert results[:2] == [None, None]
            assert results[2] is not None and results[2].retry_after <= 60
        finally:
            for client in clients:
                await client.aclose()

    asyncio.run(scenario())


def test_ipv6_clients_are_counted_per_64_block():
    # One subscriber usually gets a whole /64; keying single IPv6 addresses would let it rotate
    # addresses to escape both the per-minute limit and the daily quota.
    from app.core.limits import client_address
    def scope(peer):
        return {"client": (peer, 1234), "headers": []}
    a = client_address(scope("2001:db8:1:2::10"), "")
    b = client_address(scope("2001:db8:1:2:ffff:ffff:ffff:1"), "")
    other = client_address(scope("2001:db8:1:3::10"), "")
    assert a == b != other
    assert client_address(scope("::ffff:203.0.113.7"), "") == "203.0.113.7"   # IPv4 stays per address
