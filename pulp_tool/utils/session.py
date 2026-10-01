"""
Session utilities for Pulp operations.

This module provides utilities for creating and configuring HTTP clients
with retry strategies and connection pooling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import time
from collections.abc import Sequence
from typing import Any

import httpx
from httpx import HTTPTransport

# ============================================================================
# HTTP Configuration Constants
# ============================================================================

# HTTP status codes that should trigger automatic retries (transient / overload)
RETRY_STATUS_CODES: tuple[int, ...] = (429, 500, 502, 503, 504)

# Connection-level retries (httpx transport; failed connects, etc.)
TRANSPORT_MAX_RETRIES = 3

# Application-level retries after a complete response with a transient status
# (initial attempt + (RESPONSE_RETRY_TOTAL_ATTEMPTS - 1) retries)
RESPONSE_RETRY_TOTAL_ATTEMPTS = 4
RETRY_BACKOFF_FACTOR = 0.5  # base delay before exponential backoff (seconds)


def _compute_retry_delay_s(
    *,
    response: httpx.Response,
    attempt_index: int,
    base_backoff: float,
) -> float:
    """Delay before the next attempt; honors Retry-After for 429 when present."""
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return base_backoff * (2**attempt_index)


class RetryingHttpClient(httpx.Client):
    """
    httpx.Client that retries requests when the server returns a transient status.

    Retries are applied in :meth:`send` (so all high-level calls are covered).
    Streaming requests are not retried (body may already be in flight).
    """

    def __init__(
        self,
        *args: Any,
        response_retry_total_attempts: int | None = None,
        response_retry_status_codes: Sequence[int] | None = None,
        response_retry_backoff_s: float = RETRY_BACKOFF_FACTOR,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        eff_attempts = (
            RESPONSE_RETRY_TOTAL_ATTEMPTS if response_retry_total_attempts is None else response_retry_total_attempts
        )
        self._response_retry_total_attempts = max(1, eff_attempts)
        self._response_retry_status_codes = frozenset(
            response_retry_status_codes if response_retry_status_codes is not None else RETRY_STATUS_CODES
        )
        self._response_retry_backoff_s = response_retry_backoff_s

    def send(  # type: ignore[override]
        self, request: httpx.Request, *, stream: bool = False, **kwargs: Any
    ) -> httpx.Response:
        if stream:
            return super().send(request, stream=True, **kwargs)

        last_response: httpx.Response | None = None
        for attempt in range(self._response_retry_total_attempts):
            response = super().send(request, stream=False, **kwargs)
            last_response = response
            if response.status_code not in self._response_retry_status_codes:
                return response
            if attempt + 1 >= self._response_retry_total_attempts:
                break
            delay_s = _compute_retry_delay_s(
                response=response,
                attempt_index=attempt,
                base_backoff=self._response_retry_backoff_s,
            )
            logging.warning(
                "HTTP %s from %s %s; retrying in %.2fs (attempt %d/%d)",
                response.status_code,
                request.method,
                request.url,
                delay_s,
                attempt + 1,
                self._response_retry_total_attempts,
            )
            try:
                response.close()
            except Exception:  # pylint: disable=broad-except
                logging.debug("Could not close response before retry", exc_info=True)
            time.sleep(delay_s)

        assert last_response is not None  # noqa: S101
        return last_response


class RetryingAsyncClient(httpx.AsyncClient):
    """Async counterpart to :class:`RetryingHttpClient`."""

    def __init__(
        self,
        *args: Any,
        response_retry_total_attempts: int | None = None,
        response_retry_status_codes: Sequence[int] | None = None,
        response_retry_backoff_s: float = RETRY_BACKOFF_FACTOR,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        eff_attempts = (
            RESPONSE_RETRY_TOTAL_ATTEMPTS if response_retry_total_attempts is None else response_retry_total_attempts
        )
        self._response_retry_total_attempts = max(1, eff_attempts)
        self._response_retry_status_codes = frozenset(
            response_retry_status_codes if response_retry_status_codes is not None else RETRY_STATUS_CODES
        )
        self._response_retry_backoff_s = response_retry_backoff_s

    async def send(  # type: ignore[override]
        self, request: httpx.Request, *, stream: bool = False, **kwargs: Any
    ) -> httpx.Response:
        if stream:
            return await super().send(request, stream=True, **kwargs)

        last_response: httpx.Response | None = None
        for attempt in range(self._response_retry_total_attempts):
            response = await super().send(request, stream=False, **kwargs)
            last_response = response
            if response.status_code not in self._response_retry_status_codes:
                return response
            if attempt + 1 >= self._response_retry_total_attempts:
                break
            delay_s = _compute_retry_delay_s(
                response=response,
                attempt_index=attempt,
                base_backoff=self._response_retry_backoff_s,
            )
            logging.warning(
                "HTTP %s from %s %s; retrying in %.2fs (attempt %d/%d)",
                response.status_code,
                request.method,
                request.url,
                delay_s,
                attempt + 1,
                self._response_retry_total_attempts,
            )
            try:
                await response.aclose()
            except Exception:  # pylint: disable=broad-except
                logging.debug("Could not close response before retry", exc_info=True)
            await asyncio.sleep(delay_s)

        assert last_response is not None  # noqa: S101
        return last_response


def create_session_with_retry(
    cert: tuple[str, str] | None = None,
    timeout: float = 30.0,
    max_connections: int = 100,
    auth: httpx.Auth | tuple[str, str] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Client:
    """
    Create an httpx client with retry strategy and connection pooling.

    Args:
        cert: Optional tuple of (cert_file, key_file) paths for client authentication
        timeout: Total timeout in seconds (default: 30.0)
        max_connections: Maximum number of connections in the pool (default: 100)
        auth: Optional auth for Basic Auth (e.g. httpx.BasicAuth or (username, password) tuple)
        extra_headers: Optional extra default headers (e.g. correlation ID)

    Returns:
        Configured :class:`RetryingHttpClient` with:
        - Retries on transient HTTP status codes (429, 5xx gateway/load errors) with backoff
        - Transport-level connection retries
        - HTTP/2 support for multiplexing
        - Compression support (gzip, deflate, br)
        - Optimized connection pooling
        - Timeout configuration
        - Optional client certificate or Basic Auth

    Example:
        >>> client = create_session_with_retry()
        >>> response = client.get("https://pulp.example.com/api/")
        >>> # With client cert and longer timeout
        >>> client = create_session_with_retry(cert=("cert.pem", "key.pem"), timeout=300.0)
        >>> # With Basic Auth (username/password)
        >>> client = create_session_with_retry(auth=("user", "pass"), timeout=300.0)
    """
    # Configure connection limits - increased for parallel workloads
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max(20, max_connections // 5),
    )

    # Configure timeout (total, connect, read, write)
    timeout_config = httpx.Timeout(timeout, connect=10.0)

    # Configure SSL context for client certificates if provided
    verify: bool | ssl.SSLContext = True
    if cert:
        # PEM paths are validated in PulpClient before session creation when mTLS is configured.
        if os.path.exists(cert[0]) and os.path.exists(cert[1]):
            ssl_context = ssl.create_default_context()
            ssl_context.load_cert_chain(certfile=cert[0], keyfile=cert[1])
            verify = ssl_context
        else:
            logging.error(
                "create_session_with_retry called with cert tuple but files missing: %s, %s",
                cert[0],
                cert[1],
            )

    # Transport-level retries (connection failures); response status retries are in RetryingHttpClient
    transport = HTTPTransport(
        limits=limits,
        retries=TRANSPORT_MAX_RETRIES,
        verify=verify,
    )

    # Add compression support headers
    default_headers: dict[str, str] = {
        "Accept-Encoding": "gzip, deflate, br",
    }
    if extra_headers:
        default_headers.update(extra_headers)

    # Try to enable HTTP/2 if available, but don't fail if not
    try:
        import importlib.util  # pylint: disable=import-outside-toplevel

        use_http2 = importlib.util.find_spec("h2") is not None
    except (ImportError, AttributeError):
        use_http2 = False

    if not use_http2:
        logging.debug("HTTP/2 support not available (h2 package not installed)")

    client_kwargs: dict = {
        "transport": transport,
        "timeout": timeout_config,
        "follow_redirects": True,
        "headers": default_headers,
        "http2": use_http2,
    }
    if auth is not None:
        if isinstance(auth, tuple):
            client_kwargs["auth"] = httpx.BasicAuth(auth[0], auth[1])
        else:
            client_kwargs["auth"] = auth

    return RetryingHttpClient(**client_kwargs)


__all__ = [
    "RETRY_STATUS_CODES",
    "RESPONSE_RETRY_TOTAL_ATTEMPTS",
    "RETRY_BACKOFF_FACTOR",
    "TRANSPORT_MAX_RETRIES",
    "RetryingAsyncClient",
    "RetryingHttpClient",
    "create_session_with_retry",
]
