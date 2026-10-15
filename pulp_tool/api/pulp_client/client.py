"""
Pulp API client for managing repositories and content.

This module provides the main PulpClient class, which is composed using the
mixin pattern to provide specialized functionality:

Mixins:
    - RpmRepositoryMixin, FileRepositoryMixin: Repository creation and management
    - RpmDistributionMixin, FileDistributionMixin: Distribution management
    - RpmPackageContentMixin, FileContentMixin: Content upload and management
    - ArtifactMixin: Artifact operations
    - TaskMixin: Task monitoring with exponential backoff
    - PulpClientContentQueryMixin: Content queries, RPM lookups, distribution URL helpers
    - PulpClientResultsMixin: Gather content and build upload results structures

The PulpClient class combines all resource-based mixins to provide a complete Pulp API interface
organized by resource type, matching Pulp's API documentation structure.

HTTP helpers (cache, chunked GET, repository_operation body) live in ``pulp_client.cache``,
``pulp_client.chunked_get``, and ``pulp_client.repository`` and are composed by this class.
Shared synthetic-response helpers live in ``pulp_client.helpers``.
``PulpClientContentQueryMixin`` is listed before ``ArtifactMixin`` so the Pulp content/artifact
HTTP helpers (e.g. ``get_file_locations`` accepting ``List[Dict]``) take precedence over the
artifact mixin’s typed variant.

Key Features:
    - OAuth2 authentication with automatic token refresh
    - Exponential backoff for task polling
    - Context-based error handling with @with_error_handling decorator
    - Type-safe operations using Pydantic models
    - Proper resource cleanup with context managers
"""

# Standard library imports
import asyncio
import json
import logging
import os
import ssl
import tempfile
import tomllib
from pathlib import Path
from typing import Any

# Third-party imports
import httpx

from ...exceptions import PulpToolConfigError, PulpToolHTTPError
from ...utils import create_session_with_retry
from ...utils.client_limits import get_cache_max_entries, get_cache_ttl, http_max_connections
from ...utils.constants import DEFAULT_CHUNK_SIZE, RED_HAT_SSO_TOKEN_URL
from ...utils.correlation import CORRELATION_HEADER, resolve_correlation_id
from ...utils.session import RetryingAsyncClient

# Local imports
from ..artifacts.operations import ArtifactMixin
from ..auth import OAuth2ClientCredentialsAuth
from ..content.file_files import FileContentMixin
from ..content.rpm_packages import RpmPackageContentMixin
from ..distributions.file import FileDistributionMixin
from ..distributions.rpm import RpmDistributionMixin
from ..repositories.file import FileRepositoryMixin
from ..repositories.rpm import RpmRepositoryMixin
from ..tasks.operations import TaskMixin
from .cache import PerformanceMetrics, TTLCache, cached_get
from .chunked_get import chunked_get, chunked_get_async
from .content_query import PulpClientContentQueryMixin
from .repository import get_single_resource_by_name
from .repository import repository_operation as repository_operation_impl
from .results import PulpClientResultsMixin

# ============================================================================
# Constants
# ============================================================================

# Default timeout for HTTP requests (seconds)
# Increased to 120 seconds to handle slow operations like bulk content queries
DEFAULT_TIMEOUT = 120


# ============================================================================
# Main Client Class
# ============================================================================


class PulpClient(
    RpmRepositoryMixin,
    FileRepositoryMixin,
    RpmDistributionMixin,
    FileDistributionMixin,
    RpmPackageContentMixin,
    FileContentMixin,
    PulpClientContentQueryMixin,
    ArtifactMixin,
    TaskMixin,
    PulpClientResultsMixin,
):
    """
    A client for interacting with Pulp API.

    API documentation:
    - https://docs.pulpproject.org/pulp_rpm/restapi.html
    - https://docs.pulpproject.org/pulpcore/restapi.html

    A note regarding PUT vs PATCH:
    - PUT changes all data and therefore all required fields need to be sent
    - PATCH changes only the data that we are sending

    Many methods require repository, distribution, publication, etc,
    to be the full API endpoint (called "pulp_href"), not simply their name.
    If method argument doesn't have "name" in its name, assume it expects
    pulp_href. It looks like this:
    /pulp/api/v3/publications/rpm/rpm/5e6827db-260f-4a0f-8e22-7f17d6a2b5cc/
    """

    def __init__(
        self,
        config: dict[str, str | int],
        domain: str | None = None,
        config_path: Path | None = None,
        *,
        correlation_namespace: str | None = None,
        correlation_build_id: str | None = None,
    ) -> None:
        """Initialize the Pulp client.

        Args:
            config: Configuration dictionary from the TOML file
            domain: Optional explicit domain override
            config_path: Path to config file for resolving relative cert/key paths
            correlation_namespace: Optional CLI namespace for ``X-Correlation-ID`` derivation
            correlation_build_id: Optional CLI build id for correlation ID derivation
        """
        self.domain = domain
        self.config = config
        # Set namespace from domain or config file's domain field
        self.namespace = domain if domain else config.get("domain")
        self.config_path = config_path  # Store config path for resolving relative cert/key paths
        self._correlation_namespace = correlation_namespace
        self._correlation_build_id = correlation_build_id
        self.timeout = DEFAULT_TIMEOUT  # Used by Protocol mixins
        self._auth = None
        self._async_session: httpx.AsyncClient | None = None
        self._cert_temp_dir: tempfile.TemporaryDirectory | None = None
        self._cert_paths: tuple[str, str] | None = None
        self.session = self._create_session()
        cache_ttl = get_cache_ttl()
        # Initialize cache for GET requests
        self._get_cache = TTLCache(ttl=cache_ttl, max_entries=get_cache_max_entries())
        # Initialize performance metrics tracker
        self._metrics = PerformanceMetrics()
        logging.debug(
            "PulpClient initialized with request caching enabled (TTL: %ds, max_entries: %d)",
            cache_ttl,
            get_cache_max_entries(),
        )

    def _require_client_cert_files_if_configured(self) -> None:
        """
        If cert+key are set for mTLS, both PEM paths must exist after resolution.

        Otherwise create_session_with_retry would silently skip loading the client cert,
        and requests would use default TLS verification only—often resulting in HTTP 403
        from gateways that require mTLS.
        """
        cert_cfg = self.config.get("cert")
        key_cfg = self.config.get("key")
        if not cert_cfg and not key_cfg:
            return
        if not cert_cfg or not key_cfg:
            logging.error(
                "Pulp config sets only one of cert/key; provide both for mTLS or omit both and use OAuth2/Basic auth."
            )
            raise ValueError(
                "Invalid Pulp TLS config: both `cert` and `key` must be set for client certificate auth, or "
                "remove both and use client_id/client_secret or username/password."
            )
        cert_path_str, key_path_str = self.cert
        cert_ok = Path(cert_path_str).is_file()
        key_ok = Path(key_path_str).is_file()
        if not cert_ok or not key_ok:
            logging.error(
                "Client TLS is configured (cert/key in config) but certificate file(s) are missing or not readable. "
                "cert=%s (ok=%s), key=%s (ok=%s). "
                "Without these files the HTTP client will not send a client certificate; the API may return HTTP 403.",
                cert_path_str,
                cert_ok,
                key_path_str,
                key_ok,
            )
            raise ValueError(
                f"Certificate or key file not found or not a file: cert={cert_path_str!s}, key={key_path_str!s}. "
                "Use paths that exist in this environment (Konflux/Tekton pods must mount TLS material where "
                "the config points)."
            )

    def _create_session(self) -> httpx.Client:
        """Create a requests session with retry strategy and connection pool configuration."""
        self._require_client_cert_files_if_configured()
        # Pass cert to Client constructor if available, otherwise auth will be added per-request
        cert = self.cert if self.config.get("cert") else None
        return create_session_with_retry(cert=cert, extra_headers=self.headers, max_connections=http_max_connections())

    def _get_async_session(self) -> httpx.AsyncClient:
        """Get or create async session with optimized configuration."""
        if self._async_session is None or self._async_session.is_closed:
            self._require_client_cert_files_if_configured()
            cert = self.cert if self.config.get("cert") else None

            max_conn = http_max_connections()
            limits = httpx.Limits(
                max_connections=max_conn,
                max_keepalive_connections=max(1, max_conn // 4),
            )
            timeout = httpx.Timeout(self.timeout, connect=10.0)

            # Add compression headers and optional correlation ID (pulp-cli ``cid`` pattern)
            default_headers: dict[str, str] = {
                "Accept-Encoding": "gzip, deflate, br",
            }
            ch = self.headers
            if ch:
                default_headers.update(ch)

            # Try to enable HTTP/2 if available, but don't fail if not
            try:
                import importlib.util  # pylint: disable=import-outside-toplevel

                use_http2 = importlib.util.find_spec("h2") is not None
            except (ImportError, AttributeError):
                use_http2 = False

            if not use_http2:
                logging.debug("HTTP/2 support not available for async client (h2 package not installed)")

            # Configure SSL context for client certificates if provided
            verify: bool | ssl.SSLContext = True
            if cert:
                # Only create SSL context if certificate files actually exist
                # This allows tests to pass fake paths without FileNotFoundError
                if os.path.exists(cert[0]) and os.path.exists(cert[1]):
                    ssl_context = ssl.create_default_context()
                    ssl_context.load_cert_chain(certfile=cert[0], keyfile=cert[1])
                    verify = ssl_context
                # If cert paths provided but files don't exist, just use default verification
                # (useful for testing where we mock the actual HTTP calls)

            # Prepare client kwargs
            client_kwargs: dict[str, Any] = {
                "limits": limits,
                "timeout": timeout,
                "follow_redirects": True,
                "headers": default_headers,
                "http2": use_http2,
                "verify": verify,
            }

            # Add auth for non-cert authentication
            if not self.config.get("cert"):
                client_kwargs["auth"] = self.auth

            self._async_session = RetryingAsyncClient(**client_kwargs)  # type: ignore[arg-type]
        return self._async_session

    def invalidate_get_cache(self) -> None:
        """Clear cached GET responses (e.g. after repository mutations)."""
        if hasattr(self, "_get_cache"):
            self._get_cache.clear()

    def _close_async_session_sync(self) -> None:
        """Close the async httpx client when no event loop is running."""
        if not self._async_session or self._async_session.is_closed:
            self._async_session = None
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.async_close())
            self._async_session = None
        else:
            logging.warning(
                "PulpClient.close() called with an open async session while an event loop is running; "
                "await async_close() explicitly"
            )

    def close(self) -> None:
        """Close the session and release all connections."""
        if hasattr(self, "session") and self.session:
            self.session.close()
            logging.debug("PulpClient session closed and connections released")
        self._close_async_session_sync()
        # Clear cache on close
        if hasattr(self, "_get_cache"):
            cache_size = self._get_cache.size()
            self._get_cache.clear()
            logging.debug("Cleared cache (%d entries)", cache_size)
        # Log performance metrics summary
        if hasattr(self, "_metrics"):
            self._metrics.log_summary()
        # Clean up temp cert/key dir if we created one for base64-decoded certs
        if hasattr(self, "_cert_temp_dir") and self._cert_temp_dir is not None:
            try:
                self._cert_temp_dir.cleanup()
            except OSError:
                pass
            self._cert_temp_dir = None
            self._cert_paths = None

    async def async_close(self) -> None:
        """Close the async session and release all connections."""
        if self._async_session and not self._async_session.is_closed:
            await self._async_session.aclose()
            logging.debug("PulpClient async session closed and connections released")
        self._async_session = None

    def _run_async(self, coro) -> Any:
        """
        Run async coroutine and clear cached async session afterward.

        Prevents 'Event loop is closed' when multiple sync wrappers call asyncio.run()
        in sequence (e.g. search-by with checksums + filenames + signed_by).
        Each asyncio.run() creates and closes a loop; the cached httpx.AsyncClient
        becomes bound to a closed loop. Clearing the session ensures the next call
        creates a fresh client for the new loop.
        """

        async def _run_with_cleanup() -> Any:
            try:
                return await coro
            finally:
                if self._async_session and not self._async_session.is_closed:
                    await self._async_session.aclose()
                self._async_session = None

        return asyncio.run(_run_with_cleanup())

    def __enter__(self) -> "PulpClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any | None) -> None:
        """Context manager exit - ensures session is closed."""
        self.close()

    async def _chunked_get_async(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        chunk_param: str | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        **kwargs,
    ) -> httpx.Response:
        """
        Perform a GET request with chunking for large parameter lists using async.

        This is a workaround for the fact that requests with large parameter
        values using "GET" method fails with "Request Line is too large".
        Hence, this splits the parameter value into chunks of the given size,
        and makes separate async requests for each chunk concurrently.
        The results are aggregated into a single response.

        Note: - chunks are created on only one parameter at a time.
              - response object of the last chunk is returned with the aggregated results.
              - chunks are processed concurrently using asyncio for optimal performance
        """
        return await chunked_get_async(self, url, params, chunk_param, chunk_size, **kwargs)

    def _chunked_get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        chunk_param: str | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        **kwargs,
    ) -> httpx.Response:
        """
        Synchronous wrapper for _chunked_get_async.

        Provides a synchronous interface while using async implementation
        underneath for better performance.
        """
        return chunked_get(self, url, params, chunk_param, chunk_size, **kwargs)

    @classmethod
    def create_from_config_file(
        cls,
        path: str | None = None,
        domain: str | None = None,
        *,
        correlation_namespace: str | None = None,
        correlation_build_id: str | None = None,
    ) -> "PulpClient":
        """
        Create a Pulp client from a standard configuration file that is
        used by the `pulp` CLI tool.

        The namespace/domain will be read from the config file's 'domain' field.

        Args:
            path: Path to config file or base64-encoded config content. If None, uses default path.
            domain: Optional domain override
            correlation_namespace: Optional CLI namespace for ``X-Correlation-ID`` derivation
            correlation_build_id: Optional CLI build id for correlation ID derivation
        """
        from ...utils.config_utils import load_config_content

        config_source = path or "~/.config/pulp/cli.toml"
        config_bytes, is_base64 = load_config_content(config_source)

        # Parse TOML from bytes
        try:
            config = tomllib.loads(config_bytes.decode("utf-8"))
        except tomllib.TOMLDecodeError as e:
            source_desc = "base64 config" if is_base64 else str(Path(config_source).expanduser())
            raise PulpToolConfigError(f"Invalid TOML in configuration {source_desc}: {e}") from e

        # For base64 config, config_path is None (no file path)
        # For file path, use the expanded path
        config_path = None if is_base64 else Path(config_source).expanduser()

        return cls(
            config["cli"],
            domain,
            config_path=config_path,
            correlation_namespace=correlation_namespace,
            correlation_build_id=correlation_build_id,
        )

    @property
    def headers(self) -> dict[str, str] | None:
        """
        Optional request headers (e.g. ``X-Correlation-ID`` for log correlation).

        Resolution order: ``cli.correlation_id`` in config > ``PULP_TOOL_CORRELATION_ID`` env >
        ``namespace/build_id`` from CLI kwargs > ``build_id`` alone.
        """
        cid = resolve_correlation_id(
            config_value=self.config.get("correlation_id"),
            namespace=self._correlation_namespace,
            build_id=self._correlation_build_id,
        )
        if not cid:
            return None
        return {CORRELATION_HEADER: cid}

    @property
    def auth(self) -> OAuth2ClientCredentialsAuth | httpx.BasicAuth:
        """
        Get authentication credentials.

        Supports OAuth2 (client_id/client_secret) or Basic Auth (username/password).
        OAuth2 is preferred when both credential types are present.

        Returns:
            OAuth2ClientCredentialsAuth or BasicAuth instance for API authentication
        """
        if not self._auth:
            client_id = self.config.get("client_id")
            client_secret = self.config.get("client_secret")
            username = self.config.get("username")
            password = self.config.get("password")

            # Prefer OAuth2 if both client_id and client_secret are set
            if client_id and client_secret:
                token_url = RED_HAT_SSO_TOKEN_URL
                self._auth = OAuth2ClientCredentialsAuth(  # type: ignore[assignment]
                    client_id=str(client_id),
                    client_secret=str(client_secret),
                    token_url=token_url,
                )
            # Fall back to Basic Auth (username/password) for packages.redhat.com
            elif username is not None and password is not None:
                self._auth = httpx.BasicAuth(str(username), str(password))  # type: ignore[assignment]
            else:
                missing = []
                if not (client_id and client_secret):
                    missing.append("client_id/client_secret (OAuth2)")
                if username is None or password is None:
                    missing.append("username/password (Basic Auth)")
                raise PulpToolConfigError(
                    f"Authentication credentials missing. Provide either: {', or '.join(missing)}. "
                    "See README for configuration."
                )
        return self._auth  # type: ignore[return-value]

    @property
    def cert(self) -> tuple[str, str]:
        """
        Get client certificate information.

        If cert/key paths are not absolute and config_path is available,
        tries to resolve them relative to the config file's directory.
        If cert or key file content is base64-encoded, decodes it and uses
        temporary files so the SSL context receives valid paths.

        Returns:
            Tuple of (cert_path, key_path) for client certificate authentication
        """
        from ...utils.config_utils import load_file_content_maybe_base64

        # Return cached paths when we previously wrote base64-decoded content to temp files
        if self._cert_paths is not None:
            return self._cert_paths

        cert_path_str = str(self.config.get("cert"))
        key_path_str = str(self.config.get("key"))

        # Try to resolve relative paths if config_path is available
        if self.config_path and self.config_path.parent:
            cert_path = Path(cert_path_str)
            key_path = Path(key_path_str)

            # If cert path is not absolute and doesn't exist, try relative to config
            if not cert_path.is_absolute() and not cert_path.exists():
                potential_cert = self.config_path.parent / cert_path
                if potential_cert.exists():
                    cert_path_str = str(potential_cert)

            # If key path is not absolute and doesn't exist, try relative to config
            if not key_path.is_absolute() and not key_path.exists():
                potential_key = self.config_path.parent / key_path
                if potential_key.exists():
                    key_path_str = str(potential_key)

        cert_path = Path(cert_path_str)
        key_path = Path(key_path_str)
        if (
            cert_path_str in ("None", "")
            or key_path_str in ("None", "")
            or not cert_path.exists()
            or not key_path.exists()
        ):
            return (cert_path_str, key_path_str)

        cert_bytes, cert_was_base64 = load_file_content_maybe_base64(cert_path)
        key_bytes, key_was_base64 = load_file_content_maybe_base64(key_path)

        if cert_was_base64 or key_was_base64:
            self._cert_temp_dir = tempfile.TemporaryDirectory()
            temp_dir = Path(self._cert_temp_dir.name)
            temp_cert = temp_dir / "cert.pem"
            temp_key = temp_dir / "key.pem"
            temp_cert.write_bytes(cert_bytes)
            temp_key.write_bytes(key_bytes)
            self._cert_paths = (str(temp_cert), str(temp_key))
            logging.debug("Using temp cert/key from base64-decoded content")
            return self._cert_paths

        return (cert_path_str, key_path_str)

    @property
    def request_params(self) -> dict[str, Any]:
        """
        Get default parameters for requests.

        Returns:
            Dictionary containing default request parameters including
            authentication information (headers and auth, but not cert which is in Client)
        """
        params = {}
        if self.headers:
            params["headers"] = self.headers
        # Note: cert is passed to Client constructor, not per-request
        # Only add auth if not using cert-based authentication
        if not self.config.get("cert"):
            params["auth"] = self.auth  # type: ignore[assignment]
        return params

    def _url(self, endpoint: str) -> str:
        """
        Build a fully qualified URL for a given API endpoint.

        Args:
            endpoint: API endpoint path (e.g., "api/v3/repositories/rpm/rpm/")

        Returns:
            Complete URL including base URL, API root, domain, and endpoint
        """
        domain = self._get_domain()

        relative = os.path.normpath(
            "/".join(
                [
                    str(self.config["api_root"]),
                    domain,
                    endpoint,
                ]
            )
        )

        # Normpath removes the trailing slash. If it was there, put it back
        if endpoint.endswith("/"):
            relative += "/"
        return str(self.config["base_url"]) + relative

    def _get_domain(self) -> str:
        """
        Get the domain name.

        Returns:
            Domain name as configured
        """
        if self.domain:
            return self.domain
        if self.config.get("domain"):
            return str(self.config["domain"])
        return ""

    def get_domain(self) -> str:
        """Public method to get the domain name."""
        return self._get_domain()

    @cached_get
    def _get_single_resource(self, endpoint: str, name: str) -> httpx.Response:
        """
        Helper method to get a single resource by name.

        This method is cached to avoid redundant lookups of repositories/distributions.

        Args:
            endpoint: API endpoint for the resource type
            name: Name of the resource to retrieve

        Returns:
            Response object containing the resource data
        """
        return get_single_resource_by_name(self, endpoint, name)

    def _log_request_headers(self, response: httpx.Response) -> None:
        """Log request headers with sensitive data redacted."""
        if response.request and response.request.headers:
            safe_headers = dict(response.request.headers)
            # Redact sensitive headers
            for sensitive_key in ["authorization", "cookie", "x-api-key"]:
                if sensitive_key in safe_headers:
                    safe_headers[sensitive_key] = "[REDACTED]"
            logging.error("  Request Headers: %s", safe_headers)

    def _log_request_body(self, response: httpx.Response) -> None:
        """Log request body, handling different content types."""
        try:
            if response.request and response.request.content:
                try:
                    # Try to decode as text for logging
                    content = response.request.content.decode("utf-8", errors="replace")
                    # Truncate if very long
                    if len(content) > 1000:
                        logging.error("  Request Body (truncated): %s...", content[:1000])
                    else:
                        logging.error("  Request Body: %s", content)
                except Exception:
                    logging.error("  Request Body: <binary data, %d bytes>", len(response.request.content))
        except (httpx.RequestNotRead, AttributeError):
            # For streaming/multipart requests, content has already been consumed
            content_type = response.request.headers.get("content-type", "") if response.request else ""
            if "multipart" in content_type:
                logging.error("  Request Body: <multipart/form-data - file upload>")
            else:
                logging.error("  Request Body: <streaming request - content already consumed>")

    def _log_response_details(self, response: httpx.Response) -> None:
        """Log response details including headers and body."""
        logging.error("RESPONSE DETAILS:")
        logging.error("  Status Code: %s", response.status_code)
        logging.error("  Response Headers: %s", dict(response.headers))

        # Try to parse error details
        try:
            error_data = response.json()
            logging.error("  Error Data: %s", error_data)
        except (ValueError, json.JSONDecodeError):
            # Log response body at error level for 5xx errors
            if len(response.text) > 500:
                logging.error("  Response Body (truncated): %s...", response.text[:500])
            else:
                logging.error("  Response Body: %s", response.text)

    def _log_server_error(self, response: httpx.Response, operation: str) -> None:
        """Log detailed information for server errors (5xx)."""
        logging.error("=" * 80)
        logging.error("SERVER ERROR (%s) during %s", response.status_code, operation)
        logging.error("=" * 80)

        # Request details
        logging.error("REQUEST DETAILS:")
        logging.error("  Method: %s", response.request.method if response.request else "Unknown")
        logging.error("  URL: %s", response.url)

        self._log_request_headers(response)
        self._log_request_body(response)
        self._log_response_details(response)

        logging.error("=" * 80)

    def _check_response(self, response: httpx.Response, operation: str = "request") -> None:
        """Check if a response is successful, raise exception if not."""
        if not response.is_success:
            # Server errors (5xx) are critical and should be logged as ERROR
            if response.status_code >= 500:
                self._log_server_error(response, operation)
            elif response.status_code >= 400:
                # Client errors (4xx) are logged at debug level
                logging.debug("Client error during %s: %s - %s", operation, response.status_code, response.text)
            else:
                # Other non-success responses
                logging.debug("Failed to %s: %s - %s", operation, response.status_code, response.text)

            raise PulpToolHTTPError(
                f"Failed to {operation}: {response.status_code} - {response.text}",
                response=response,
            )

    def check_response(self, response: httpx.Response, operation: str = "request") -> None:
        """Public method to check if a response is successful, raise exception if not."""
        self._check_response(response, operation)

    # ============================================================================
    # Async Methods for Repository Setup
    # ============================================================================

    def _prepare_async_kwargs(self, **kwargs: Any) -> dict[str, Any]:
        """Merge default request params (headers, auth) into async call kwargs."""
        rp = self.request_params
        out: dict[str, Any] = dict(kwargs)
        if "headers" in rp:
            base_h = dict(rp["headers"])
            if out.get("headers"):
                base_h.update(out["headers"])
            out["headers"] = base_h
        if "auth" in rp and "auth" not in out and rp["auth"] is not None:
            out["auth"] = rp["auth"]
        return out

    async def async_get(self, url: str, **kwargs) -> httpx.Response:
        """Async GET request."""
        client = self._get_async_session()
        return await client.get(url, **self._prepare_async_kwargs(**kwargs))

    async def async_post(self, url: str, **kwargs) -> httpx.Response:
        """Async POST request."""
        client = self._get_async_session()
        return await client.post(url, **self._prepare_async_kwargs(**kwargs))

    # ============================================================================
    # Content Management Methods (migrated from ContentManagerMixin)
    # ============================================================================

    def upload_content(self, file_path: str, labels: dict[str, str], *, file_type: str, arch: str | None = None) -> str:
        """
        Generic file upload function with validation and error handling.

        Args:
            file_path: Path to the file to upload
            labels: Labels to attach to the uploaded content
            file_type: Type of file (e.g., 'rpm', 'file') - determines upload method
            arch: Architecture for the uploaded content (required for RPM uploads)

        Returns:
            Pulp href of the uploaded content

        Raises:
            FileNotFoundError: If the file does not exist
            PermissionError: If the file cannot be read
            ValueError: If the file is empty or arch is missing for RPMs
        """
        from ...utils import validate_file_path

        # Validate file before upload
        validate_file_path(file_path, file_type)

        try:
            # Call the appropriate upload method based on file_type
            if file_type.lower() == "rpm":
                if not arch:
                    raise ValueError("arch parameter is required for RPM uploads")
                # Handle RPM upload directly
                url = self._url("api/v3/content/rpm/packages/upload/")
                with open(file_path, "rb") as fp:
                    file_name = os.path.basename(file_path)
                    build_id = labels.get("build_id", "")

                    # Build relative_path for RPMs
                    # RPMs use only the filename as the relative_path (no build_id, no arch prefix)
                    # The distribution base_path contains namespace/parent_package/rpms
                    relative_path = file_name

                    data = {
                        "pulp_labels": json.dumps(labels),
                        "relative_path": relative_path,
                    }
                    files = {"file": fp}

                    # Log upload attempt details for debugging
                    logging.debug("Attempting RPM upload:")
                    logging.debug("  URL: %s", url)
                    logging.debug("  File: %s", file_name)
                    logging.debug("  Relative Path: %s", relative_path)
                    logging.debug("  Build ID: %s", build_id)
                    logging.debug("  Arch: %s", arch)
                    logging.debug("  Labels: %s", labels)

                    response = self.session.post(
                        url, data=data, files=files, timeout=self.upload_content_timeout, **self.request_params
                    )
            else:
                # For non-RPM files, use create_file_content from FileContentMixin
                response = self.create_file_content(
                    "", file_path, build_id=labels.get("build_id", ""), pulp_label=labels, arch=arch
                )

            # Include filename in operation for better error context
            operation_context = f"upload {file_type} ({os.path.basename(file_path)})"
            self._check_response(response, operation_context)
            return response.json()["pulp_href"]

        except httpx.HTTPError:
            logging.error("Request failed for %s %s", file_type, file_path, exc_info=True)
            raise
        except Exception:
            logging.error("Unexpected error uploading %s %s", file_type, file_path, exc_info=True)
            raise

    # Note: create_file_content and add_content are inherited from FileContentMixin
    # _build_file_relative_path is also inherited from FileContentMixin

    # ============================================================================
    # Repository Management Methods (migrated from RepositoryManagerMixin)
    # ============================================================================

    def _create_resource(self, endpoint: str, request_model: Any) -> httpx.Response:
        """
        Create a resource (repository or distribution).

        Args:
            endpoint: API endpoint for resource creation
            request_model: Request model (RepositoryRequest or DistributionRequest)

        Returns:
            Response object from the creation request
        """
        url = self._url(endpoint)
        data = request_model.model_dump(exclude_none=True)
        response = self.session.post(url, json=data, timeout=self.timeout, **self.request_params)
        self._check_response(response, "create resource")
        return response

    def _create_repository(self, endpoint: str, new_repository: Any) -> httpx.Response:
        """Create a repository (delegates to _create_resource)."""
        return self._create_resource(endpoint, new_repository)

    def _create_distribution(self, endpoint: str, new_distribution: Any) -> httpx.Response:
        """Create a distribution (delegates to _create_resource)."""
        return self._create_resource(endpoint, new_distribution)

    def repository_operation(
        self,
        operation: str,
        repo_type: str,
        *,
        name: str | None = None,
        repository_data: Any | None = None,
        distribution_data: Any | None = None,
        publication: str | None = None,
        distribution_href: str | None = None,
    ) -> httpx.Response:
        """
        Perform repository or distribution operations.

        Args:
            operation: Operation to perform ('create_repo', 'get_repo',
                      'create_distro', 'get_distro', 'update_distro')
            repo_type: Type of repository/distribution ('rpm' or 'file')
            name: Name of the repository/distribution (for get resource operations)
            repository_data: RepositoryRequest model for the repository to create
            distribution_data: DistributionRequest model for the distribution to create
            publication: Publication href (for update operations)
            distribution_href: Full href of distribution (for update operations)

        Returns:
            Response object from the operation
        """
        response = repository_operation_impl(
            self,
            operation,
            repo_type,
            name=name,
            repository_data=repository_data,
            distribution_data=distribution_data,
            publication=publication,
            distribution_href=distribution_href,
        )
        if operation in ("create_repo", "create_distro", "update_distro") and response.is_success:
            self.invalidate_get_cache()
        return response


__all__ = ["DEFAULT_TIMEOUT", "PulpClient"]
