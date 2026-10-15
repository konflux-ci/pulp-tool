"""Tests for PulpClient memory/concurrency limit helpers."""

from pulp_tool.utils.client_limits import (
    DEFAULT_GET_CACHE_MAX_ENTRIES,
    DEFAULT_HTTP_MAX_CONNECTIONS,
    DEFAULT_MAX_ARCH_UPLOAD_WORKERS,
    DEFAULT_MAX_UPLOAD_WORKERS,
    arch_upload_worker_count,
    effective_pull_workers,
    get_cache_max_entries,
    get_cache_ttl,
    http_max_connections,
    max_arch_upload_workers,
    max_upload_workers,
)


class TestClientLimitsDefaults:
    """Env unset uses Konflux-friendly defaults."""

    def test_http_max_connections_default(self, monkeypatch) -> None:
        monkeypatch.delenv("PULP_TOOL_HTTP_MAX_CONNECTIONS", raising=False)
        assert http_max_connections() == DEFAULT_HTTP_MAX_CONNECTIONS

    def test_get_cache_max_entries_default(self, monkeypatch) -> None:
        monkeypatch.delenv("PULP_TOOL_GET_CACHE_MAX_ENTRIES", raising=False)
        assert get_cache_max_entries() == DEFAULT_GET_CACHE_MAX_ENTRIES

    def test_get_cache_ttl_default(self, monkeypatch) -> None:
        monkeypatch.delenv("PULP_TOOL_GET_CACHE_TTL", raising=False)
        assert get_cache_ttl() == 300

    def test_max_upload_workers_default(self, monkeypatch) -> None:
        monkeypatch.delenv("PULP_TOOL_MAX_UPLOAD_WORKERS", raising=False)
        assert max_upload_workers() == DEFAULT_MAX_UPLOAD_WORKERS

    def test_max_arch_upload_workers_default(self, monkeypatch) -> None:
        monkeypatch.delenv("PULP_TOOL_MAX_ARCH_UPLOAD_WORKERS", raising=False)
        assert max_arch_upload_workers() == DEFAULT_MAX_ARCH_UPLOAD_WORKERS


class TestClientLimitsEnvOverride:
    """Invalid or missing env values fall back safely."""

    def test_http_max_connections_override(self, monkeypatch) -> None:
        monkeypatch.setenv("PULP_TOOL_HTTP_MAX_CONNECTIONS", "48")
        assert http_max_connections() == 48

    def test_invalid_env_falls_back(self, monkeypatch) -> None:
        monkeypatch.setenv("PULP_TOOL_HTTP_MAX_CONNECTIONS", "nope")
        assert http_max_connections() == DEFAULT_HTTP_MAX_CONNECTIONS

    def test_non_positive_env_falls_back(self, monkeypatch) -> None:
        monkeypatch.setenv("PULP_TOOL_MAX_UPLOAD_WORKERS", "0")
        assert max_upload_workers() == DEFAULT_MAX_UPLOAD_WORKERS


class TestClientLimitsHelpers:
    """Derived worker counts."""

    def test_arch_upload_worker_count_caps(self, monkeypatch) -> None:
        monkeypatch.delenv("PULP_TOOL_MAX_ARCH_UPLOAD_WORKERS", raising=False)
        assert arch_upload_worker_count(6) == DEFAULT_MAX_ARCH_UPLOAD_WORKERS
        assert arch_upload_worker_count(2) == 2
        assert arch_upload_worker_count(0) == 1

    def test_effective_pull_workers_caps_to_http_pool(self, monkeypatch) -> None:
        monkeypatch.setenv("PULP_TOOL_HTTP_MAX_CONNECTIONS", "10")
        assert effective_pull_workers(100) == 10
        assert effective_pull_workers(4) == 4
        assert effective_pull_workers(0) == 1
