"""Tests for ``pulp_tool.api.pulp_client.cache`` (TTL cache, metrics, cached_get)."""

from unittest.mock import patch

import httpx

from pulp_tool.api.pulp_client.cache import (
    CACHE_TTL,
    PerformanceMetrics,
    TTLCache,
    cached_get,
)


def test_performance_metrics_log_request_cached_branch() -> None:
    """``log_request(cached=True)`` increments ``cached_requests`` (line 31-32)."""
    m = PerformanceMetrics()
    m.log_request(cached=False)
    m.log_request(cached=True)
    assert m.total_requests == 2
    assert m.cached_requests == 1


def test_ttl_cache_hit_and_expired_removes_key() -> None:
    """TTL ``get`` returns stored value, then None after expiry and deletes key (lines 91-96)."""
    cache = TTLCache(ttl=10)
    with patch("pulp_tool.api.pulp_client.cache.time") as mock_time:
        mock_time.time.return_value = 0.0
        cache.set("k2", "v2")
        mock_time.time.return_value = 5.0
        assert cache.get("k2") == "v2"
        mock_time.time.return_value = 100.0
        assert cache.get("k2") is None
    assert cache.size() == 0


def test_cached_get_bypasses_when_first_arg_not_str() -> None:
    """Decorator skips cache when first positional arg is not a string (line 127-128)."""

    class _C:
        def __init__(self) -> None:
            self._get_cache = TTLCache(ttl=CACHE_TTL)
            self._metrics = PerformanceMetrics()
            self.calls = 0

        @cached_get
        def fetch(self, endpoint: object) -> int:
            self.calls += 1
            return 42

    c = _C()
    assert c.fetch(123) == 42
    assert c.fetch(123) == 42
    assert c.calls == 2


def test_cached_get_hit_and_miss_with_metrics() -> None:
    """Cache hit logs and uses ``log_request(cached=True)``; miss stores on success (lines 133-147)."""

    class _C:
        def __init__(self) -> None:
            self._get_cache = TTLCache(ttl=CACHE_TTL)
            self._metrics = PerformanceMetrics()
            self.calls = 0

        @cached_get
        def fetch(self, endpoint: str, name: str) -> httpx.Response:
            self.calls += 1
            return httpx.Response(200, json={"ok": True})

    c = _C()
    r1 = c.fetch("api/x", "n")
    r2 = c.fetch("api/x", "n")
    assert c.calls == 1
    assert r1.status_code == r2.status_code == 200
    assert c._metrics.cached_requests >= 1


def test_ttl_cache_evicts_oldest_when_over_max_entries() -> None:
    """``set`` drops oldest entries when ``max_entries`` is exceeded."""
    cache = TTLCache(ttl=3600, max_entries=2)
    with patch("pulp_tool.api.pulp_client.cache.time") as mock_time:
        mock_time.time.return_value = 1.0
        cache.set("a", 1)
        mock_time.time.return_value = 2.0
        cache.set("b", 2)
        mock_time.time.return_value = 3.0
        cache.set("c", 3)
        assert cache.size() == 2
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3


def test_ttl_cache_prune_expired_on_set() -> None:
    """``set`` removes expired keys before inserting."""
    cache = TTLCache(ttl=10, max_entries=10)
    with patch("pulp_tool.api.pulp_client.cache.time") as mock_time:
        mock_time.time.return_value = 0.0
        cache.set("stale", "x")
        mock_time.time.return_value = 100.0
        cache.set("fresh", "y")
        assert cache.size() == 1
        assert cache.get("fresh") == "y"


def test_cached_get_does_not_store_failed_response() -> None:
    """Only successful responses are cached (``is_success`` branch)."""

    class _C:
        def __init__(self) -> None:
            self._get_cache = TTLCache(ttl=CACHE_TTL)
            self._metrics = PerformanceMetrics()
            self.calls = 0

        @cached_get
        def fetch(self, endpoint: str) -> httpx.Response:
            self.calls += 1
            return httpx.Response(500, text="no")

    c = _C()
    c.fetch("e")
    c.fetch("e")
    assert c.calls == 2
