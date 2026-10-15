"""Memory- and concurrency-related limits for PulpClient and upload/pull paths."""

from __future__ import annotations

import os

from .constants import CACHE_TTL as _DEFAULT_CACHE_TTL

# Konflux-friendly defaults (override via PULP_TOOL_* env vars).
DEFAULT_HTTP_MAX_CONNECTIONS = 24
DEFAULT_GET_CACHE_MAX_ENTRIES = 64
DEFAULT_MAX_UPLOAD_WORKERS = 2
DEFAULT_MAX_ARCH_UPLOAD_WORKERS = 3

_ENV_HTTP_MAX_CONNECTIONS = "PULP_TOOL_HTTP_MAX_CONNECTIONS"
_ENV_GET_CACHE_MAX_ENTRIES = "PULP_TOOL_GET_CACHE_MAX_ENTRIES"
_ENV_GET_CACHE_TTL = "PULP_TOOL_GET_CACHE_TTL"
_ENV_MAX_UPLOAD_WORKERS = "PULP_TOOL_MAX_UPLOAD_WORKERS"
_ENV_MAX_ARCH_UPLOAD_WORKERS = "PULP_TOOL_MAX_ARCH_UPLOAD_WORKERS"


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw, 10)
    except ValueError:
        return default
    return value if value > 0 else default


def http_max_connections() -> int:
    """Maximum HTTP connections for PulpClient sync and async pools."""
    return _positive_int_from_env(_ENV_HTTP_MAX_CONNECTIONS, DEFAULT_HTTP_MAX_CONNECTIONS)


def get_cache_max_entries() -> int:
    """Maximum entries in the PulpClient GET response cache."""
    return _positive_int_from_env(_ENV_GET_CACHE_MAX_ENTRIES, DEFAULT_GET_CACHE_MAX_ENTRIES)


def get_cache_ttl() -> int:
    """TTL in seconds for PulpClient GET response cache."""
    return _positive_int_from_env(_ENV_GET_CACHE_TTL, _DEFAULT_CACHE_TTL)


def max_upload_workers() -> int:
    """Parallel RPM upload workers per architecture."""
    return _positive_int_from_env(_ENV_MAX_UPLOAD_WORKERS, DEFAULT_MAX_UPLOAD_WORKERS)


def max_arch_upload_workers() -> int:
    """Cap on parallel architecture upload threads."""
    return _positive_int_from_env(_ENV_MAX_ARCH_UPLOAD_WORKERS, DEFAULT_MAX_ARCH_UPLOAD_WORKERS)


def arch_upload_worker_count(num_architectures: int) -> int:
    """Thread pool size for per-architecture upload processing."""
    if num_architectures <= 0:
        return 1
    return min(num_architectures, max_arch_upload_workers())


def effective_pull_workers(requested: int) -> int:
    """Cap pull download concurrency to the HTTP connection budget."""
    if requested <= 0:
        return 1
    return min(requested, http_max_connections())


__all__ = [
    "DEFAULT_GET_CACHE_MAX_ENTRIES",
    "DEFAULT_HTTP_MAX_CONNECTIONS",
    "DEFAULT_MAX_ARCH_UPLOAD_WORKERS",
    "DEFAULT_MAX_UPLOAD_WORKERS",
    "arch_upload_worker_count",
    "effective_pull_workers",
    "get_cache_max_entries",
    "get_cache_ttl",
    "http_max_connections",
    "max_arch_upload_workers",
    "max_upload_workers",
]
