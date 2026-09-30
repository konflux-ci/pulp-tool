"""
HTTP fetch verification for Pulp distribution URLs in e2e tests.

Uses the same distribution auth model as ``pulp-tool pull``: Basic Auth from
``username``/``password`` in ``cli.toml`` (Konflux ``pulp-access``). OAuth credentials
are API-only and cannot fetch pulp-content URLs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import tomllib
from pathlib import Path
from typing import Any

import httpx

from pulp_tool.api import DistributionClient
from pulp_tool.utils.checksum_verify import normalize_sha256_hex

RESULTS_JSON_FILENAME = "pulp_results.json"
LOGGER = logging.getLogger("e2e.distribution_fetch")

# Pulp API reports content in the repository as soon as the upload task completes.
# pulp-content (packages.redhat.com) can lag behind publish — post-test-validation uses
# the Pulp API; distribution fetch uses pulp-content HTTP and must poll longer.
DISTRIBUTION_FETCH_MAX_WAIT_S = float(os.environ.get("E2E_DISTRIBUTION_FETCH_MAX_WAIT_S", "300"))
DISTRIBUTION_FETCH_RETRY_INITIAL_DELAY_S = float(os.environ.get("E2E_DISTRIBUTION_FETCH_DELAY_S", "2"))
DISTRIBUTION_FETCH_RETRY_MAX_DELAY_S = 15.0
DISTRIBUTION_FETCH_RETRY_STATUSES = frozenset({404, 502, 503, 504})
# Back-compat: optional cap on attempts (0 = unlimited until max wait elapses)
_DISTRIBUTION_FETCH_ATTEMPTS_RAW = os.environ.get("E2E_DISTRIBUTION_FETCH_ATTEMPTS", "").strip()
DISTRIBUTION_FETCH_RETRY_ATTEMPTS = (
    max(1, int(_DISTRIBUTION_FETCH_ATTEMPTS_RAW)) if _DISTRIBUTION_FETCH_ATTEMPTS_RAW else 0
)


class DistributionFetchError(Exception):
    """Raised when a distribution URL fetch or checksum verification fails."""

    def __init__(self, message: str, *, url: str | None = None, label: str | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.label = label


def _response_body_preview(response: httpx.Response, *, max_len: int = 800) -> str:
    """Return response body text for diagnostics (works after streaming GET failures)."""
    try:
        body = response.text
    except Exception:
        try:
            raw = response.read()
            body = raw.decode("utf-8", errors="replace") if raw else ""
        except Exception as body_exc:  # noqa: BLE001 — diagnostic helper
            return f"<unreadable: {body_exc}>"
    if not body:
        return ""
    if len(body) <= max_len:
        return body
    return f"{body[:max_len]}… (truncated, {len(body)} chars total)"


def _retry_delay_s(attempt_index: int) -> float:
    delay = DISTRIBUTION_FETCH_RETRY_INITIAL_DELAY_S * (2**attempt_index)
    return min(delay, DISTRIBUTION_FETCH_RETRY_MAX_DELAY_S)


def format_http_status_error(exc: httpx.HTTPStatusError, *, url: str, label: str) -> str:
    """Build a multi-line diagnostic message for HTTP status failures."""
    response = exc.response
    lines = [
        f"{label}: HTTP {response.status_code} for {url}",
        f"reason: {response.reason_phrase}",
    ]
    if response.headers.get("content-type"):
        lines.append(f"content-type: {response.headers.get('content-type')}")
    if response.headers.get("content-length"):
        lines.append(f"content-length: {response.headers.get('content-length')}")
    body = _response_body_preview(response)
    if body:
        lines.append(f"response body: {body}")
    return "\n  ".join(lines)


def format_pulp_results_for_diagnostics(pulp_results: dict[str, Any]) -> str:
    """Pretty-print pulp_results.json for e2e failure logs."""
    return json.dumps(pulp_results, indent=2, sort_keys=True)


def format_fetch_check_summary(
    label: str,
    url: str,
    expected_sha256: str,
    *,
    artifact_entry: dict[str, Any] | None = None,
) -> str:
    """Summarize one distribution fetch check for failure logs."""
    lines = [
        f"check: {label}",
        f"url: {url}",
        f"expected_sha256: {normalize_sha256_hex(expected_sha256)}",
    ]
    if artifact_entry is not None:
        lines.append(f"artifact entry: {json.dumps(artifact_entry, indent=2, sort_keys=True)}")
    return "\n  ".join(lines)


def _resolve_config_path(config_path: Path, path_value: str) -> str | None:
    """Resolve a config path relative to the config file directory when needed."""
    expanded = os.path.expanduser(path_value.strip())
    if not expanded:
        return None
    candidate = Path(expanded)
    if candidate.is_absolute() and candidate.exists():
        return str(candidate)
    if config_path.parent:
        relative = config_path.parent / candidate
        if relative.exists():
            return str(relative)
    if candidate.exists():
        return str(candidate)
    return None


def _load_cli_section(config_path: Path) -> dict[str, Any]:
    with open(config_path, "rb") as f:
        config = tomllib.load(f)
    cli = config.get("cli")
    if not isinstance(cli, dict):
        raise DistributionFetchError(f"Missing [cli] section in config: {config_path}")
    return cli


def distribution_client_from_config(config_path: Path) -> DistributionClient:
    """
    Build a DistributionClient from pulp-access ``cli.toml``.

  Auth resolution (matches Konflux ``pulp-access`` / ``pulp-tool pull``):
    1. ``username`` + ``password`` in ``[cli]`` (Basic Auth for pulp-content GET)
    2. ``cert`` + ``key`` when both resolve to existing files (optional local setups)
    3. Otherwise raise (OAuth-only config cannot fetch distributions)
    """
    config_path = config_path.resolve()
    cli = _load_cli_section(config_path)

    username = cli.get("username")
    password = cli.get("password")
    username_str = str(username).strip() if username is not None else None
    has_password = password is not None
    if username_str and has_password:
        LOGGER.info("Distribution client auth: Basic Auth (username=%s)", username_str)
        return DistributionClient(username=username_str, password=str(password))

    cert_path: str | None = None
    key_path: str | None = None
    loaded_cert = cli.get("cert")
    if loaded_cert and isinstance(loaded_cert, str):
        cert_path = _resolve_config_path(config_path, loaded_cert)
    loaded_key = cli.get("key")
    if loaded_key and isinstance(loaded_key, str):
        key_path = _resolve_config_path(config_path, loaded_key)

    if cert_path and key_path:
        LOGGER.info("Distribution client auth: client certificate (%s)", cert_path)
        return DistributionClient(cert=cert_path, key=key_path)

    raise DistributionFetchError(
        "Distribution auth not available from config. Set username/password in [cli] "
        "(Konflux pulp-access). OAuth (client_id/client_secret) cannot fetch pulp-content URLs."
    )


def probe_http_get_status(client: DistributionClient, url: str) -> int:
    """Return HTTP status code for ``url`` without raising (e2e diagnostics only)."""
    try:
        with client.session.stream("GET", url) as response:
            if response.is_error:
                response.read()
            return int(response.status_code)
    except httpx.HTTPError:
        return 0


def distribution_fetch_retry_policy_summary() -> str:
    """Human-readable summary of retry settings (for e2e logs)."""
    attempts_part = (
        f"max_attempts={DISTRIBUTION_FETCH_RETRY_ATTEMPTS}"
        if DISTRIBUTION_FETCH_RETRY_ATTEMPTS
        else "max_attempts=unlimited"
    )
    return (
        f"max_wait_s={DISTRIBUTION_FETCH_MAX_WAIT_S}, "
        f"{attempts_part}, "
        f"initial_delay_s={DISTRIBUTION_FETCH_RETRY_INITIAL_DELAY_S}, "
        f"max_delay_s={DISTRIBUTION_FETCH_RETRY_MAX_DELAY_S}, "
        f"retry_statuses={sorted(DISTRIBUTION_FETCH_RETRY_STATUSES)}"
    )


def format_distribution_fetch_exhausted_message(
    exc: httpx.HTTPStatusError,
    *,
    url: str,
    label: str,
    attempts: int,
    elapsed_s: float,
) -> str:
    """Error text when retries are exhausted (often Pulp pulp-content propagation)."""
    base = format_http_status_error(exc, url=url, label=label)
    return (
        f"{base}\n"
        f"  retries: {attempts} attempt(s) over {elapsed_s:.1f}s "
        f"({distribution_fetch_retry_policy_summary()})\n"
        f"  hint: upload succeeded and Konflux URL matches build_id — persistent 404 usually means "
        f"pulp-content is not serving this object yet (Pulp publish/CDN lag; content may already "
        f"appear in the Pulp API and in post-test-validation). Compare GET status for SBOM vs "
        f"pulp_results.json on failure."
    )


def _fetch_bytes_once(client: DistributionClient, url: str, *, label: str) -> tuple[int, bytes]:
    """Perform one streaming GET; raise ``HTTPStatusError`` on non-success."""
    with client.session.stream("GET", url) as response:
        status_code = response.status_code
        if response.is_error:
            response.read()
        response.raise_for_status()
        body = b"".join(response.iter_bytes(chunk_size=65536))
    return status_code, body


def fetch_bytes(client: DistributionClient, url: str, *, label: str) -> bytes:
    """GET ``url`` and return the response body."""
    LOGGER.info("HTTP GET %s: %s", label, url)
    started = time.monotonic()
    deadline = started + DISTRIBUTION_FETCH_MAX_WAIT_S
    last_status_error: httpx.HTTPStatusError | None = None
    attempt = 0

    while True:
        if DISTRIBUTION_FETCH_RETRY_ATTEMPTS and attempt >= DISTRIBUTION_FETCH_RETRY_ATTEMPTS:
            break
        attempt += 1
        try:
            status_code, body = _fetch_bytes_once(client, url, label=label)
            elapsed_ms = (time.monotonic() - started) * 1000
            if attempt > 1:
                LOGGER.info(
                    "HTTP GET %s succeeded on attempt %d after %.0f ms (pulp-content became available)",
                    label,
                    attempt,
                    elapsed_ms,
                )
            LOGGER.info(
                "HTTP GET %s complete: status=%s bytes=%d elapsed_ms=%.0f",
                label,
                status_code,
                len(body),
                elapsed_ms,
            )
            return body
        except httpx.HTTPStatusError as exc:
            last_status_error = exc
            if exc.response.status_code not in DISTRIBUTION_FETCH_RETRY_STATUSES:
                elapsed_ms = (time.monotonic() - started) * 1000
                LOGGER.error("HTTP GET %s failed after %.0f ms: %s", label, elapsed_ms, exc)
                raise DistributionFetchError(
                    format_http_status_error(exc, url=url, label=label),
                    url=url,
                    label=label,
                ) from exc

            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                break
            delay_s = min(_retry_delay_s(attempt - 1), remaining_s)
            LOGGER.warning(
                "HTTP GET %s returned %s; retrying in %.1fs (attempt %d, %.0fs left in max wait)",
                label,
                exc.response.status_code,
                delay_s,
                attempt,
                remaining_s,
            )
            time.sleep(delay_s)
        except httpx.HTTPError as exc:
            elapsed_ms = (time.monotonic() - started) * 1000
            LOGGER.error("HTTP GET %s failed after %.0f ms: %s", label, elapsed_ms, exc)
            raise DistributionFetchError(
                f"{label}: HTTP GET failed for {url}: {exc}",
                url=url,
                label=label,
            ) from exc

    elapsed_s = time.monotonic() - started
    if last_status_error is not None:
        LOGGER.error("HTTP GET %s failed after %.0f ms: %s", label, elapsed_s * 1000, last_status_error)
        raise DistributionFetchError(
            format_distribution_fetch_exhausted_message(
                last_status_error,
                url=url,
                label=label,
                attempts=attempt,
                elapsed_s=elapsed_s,
            ),
            url=url,
            label=label,
        ) from last_status_error

    raise DistributionFetchError(
        f"{label}: HTTP GET timed out for {url} after {elapsed_s:.1f}s",
        url=url,
        label=label,
    )


def fetch_pulp_results_json(
    client: DistributionClient,
    url: str,
    *,
    label: str = "pulp_results.json",
    min_last_updated: str | None = None,
    required_distribution_keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """
    GET ``pulp_results.json`` from pulp-content until the document matches expectations.

    pulp-content can return HTTP 200 with a stale body shortly after Pulp publishes an updated
    results document; poll until ``min_last_updated`` (ISO date) and optional keys match.
    """
    LOGGER.info(
        "Polling %s: min_last_updated=%s required_distributions=%s url=%s",
        label,
        min_last_updated,
        sorted(required_distribution_keys or ()),
        url,
    )
    started = time.monotonic()
    deadline = started + DISTRIBUTION_FETCH_MAX_WAIT_S
    attempt = 0
    last_stale: str | None = None

    while True:
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            break
        if DISTRIBUTION_FETCH_RETRY_ATTEMPTS and attempt >= DISTRIBUTION_FETCH_RETRY_ATTEMPTS:
            break
        attempt += 1
        try:
            _status_code, body = _fetch_bytes_once(client, url, label=label)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in DISTRIBUTION_FETCH_RETRY_STATUSES:
                elapsed_ms = (time.monotonic() - started) * 1000
                LOGGER.error("HTTP GET %s failed after %.0f ms: %s", label, elapsed_ms, exc)
                raise DistributionFetchError(
                    format_http_status_error(exc, url=url, label=label),
                    url=url,
                    label=label,
                ) from exc
            delay_s = min(_retry_delay_s(attempt - 1), remaining_s)
            LOGGER.warning(
                "HTTP GET %s returned %s; retrying in %.1fs (attempt %d, %.0fs left in max wait)",
                label,
                exc.response.status_code,
                delay_s,
                attempt,
                remaining_s,
            )
            time.sleep(delay_s)
            continue
        except httpx.HTTPError as exc:
            elapsed_ms = (time.monotonic() - started) * 1000
            LOGGER.error("HTTP GET %s failed after %.0f ms: %s", label, elapsed_ms, exc)
            raise DistributionFetchError(
                f"{label}: HTTP GET failed for {url}: {exc}",
                url=url,
                label=label,
            ) from exc

        try:
            content: dict[str, Any] = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DistributionFetchError(
                f"{label}: invalid JSON from {url}: {exc}",
                url=url,
                label=label,
            ) from exc

        last_updated_raw = content.get("last_updated")
        last_updated = last_updated_raw.strip() if isinstance(last_updated_raw, str) else ""

        schema_raw = content.get("version")
        schema_version = str(schema_raw).strip() if schema_raw is not None else ""

        distributions = content.get("distributions") or {}
        if not isinstance(distributions, dict):
            distributions = {}

        stale_reasons: list[str] = []
        if min_last_updated and (not last_updated or last_updated < min_last_updated):
            stale_reasons.append(f"last_updated={last_updated_raw!r} want>={min_last_updated!r}")
        if not schema_version:
            stale_reasons.append(f"schema version={schema_raw!r} missing")
        if required_distribution_keys:
            missing = [key for key in required_distribution_keys if key not in distributions]
            if missing:
                stale_reasons.append(f"missing distributions {missing!r}")

        if not stale_reasons:
            elapsed_ms = (time.monotonic() - started) * 1000
            LOGGER.info(
                "HTTP GET %s ready: last_updated=%s schema_version=%s attempt=%d elapsed_ms=%.0f",
                label,
                last_updated,
                schema_version,
                attempt,
                elapsed_ms,
            )
            return content

        last_stale = "; ".join(stale_reasons)
        delay_s = min(_retry_delay_s(attempt - 1), remaining_s)
        LOGGER.warning(
            "HTTP GET %s body not ready (%s); retrying in %.1fs (attempt %d, %.0fs left)",
            label,
            last_stale,
            delay_s,
            attempt,
            remaining_s,
        )
        time.sleep(delay_s)

    elapsed_s = time.monotonic() - started
    raise DistributionFetchError(
        f"{label}: pulp_results.json not ready at {url} after {elapsed_s:.1f}s"
        + (f" (last: {last_stale})" if last_stale else "")
        + f" ({distribution_fetch_retry_policy_summary()})",
        url=url,
        label=label,
    )


def fetch_and_verify_sha256(
    client: DistributionClient,
    url: str,
    expected_sha256: str,
    *,
    label: str,
) -> None:
    """
    GET ``url``, hash the response body, and compare to ``expected_sha256``.

    Raises:
        DistributionFetchError: On HTTP errors or checksum mismatch.
    """
    expected = normalize_sha256_hex(expected_sha256)
    if not expected:
        raise DistributionFetchError(
            f"{label}: expected SHA256 is empty",
            url=url,
            label=label,
        )

    LOGGER.info("Verifying %s download and SHA256 from %s", label, url)
    LOGGER.info("  expected SHA256: %s", expected)
    started = time.monotonic()
    body = fetch_bytes(client, url, label=label)
    byte_count = len(body)
    status_code = 200
    hasher = hashlib.sha256()
    hasher.update(body)

    elapsed_ms = (time.monotonic() - started) * 1000
    actual = hasher.hexdigest()
    if actual != expected:
        LOGGER.error(
            "SHA256 mismatch for %s: status=%s bytes=%d elapsed_ms=%.0f expected=%s actual=%s",
            label,
            status_code,
            byte_count,
            elapsed_ms,
            expected,
            actual,
        )
        raise DistributionFetchError(
            f"{label}: SHA256 mismatch for {url}\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}",
            url=url,
            label=label,
        )

    LOGGER.info(
        "SHA256 verified for %s: status=%s bytes=%d elapsed_ms=%.0f sha256=%s",
        label,
        status_code,
        byte_count,
        elapsed_ms,
        actual,
    )


def pulp_results_json_url(pulp_results: dict[str, Any]) -> str:
    """Return the distribution URL for ``pulp_results.json`` from upload results."""
    artifacts = pulp_results.get("artifacts", {})
    if isinstance(artifacts, dict) and RESULTS_JSON_FILENAME in artifacts:
        entry = artifacts[RESULTS_JSON_FILENAME]
        if isinstance(entry, dict) and entry.get("url"):
            return str(entry["url"])

    distributions = pulp_results.get("distributions", {})
    if not isinstance(distributions, dict):
        raise DistributionFetchError("pulp_results.json missing distributions map")
    artifacts_base = distributions.get("artifacts")
    if not artifacts_base:
        raise DistributionFetchError("pulp_results.json missing distributions.artifacts base URL")
    return f"{artifacts_base}{RESULTS_JSON_FILENAME}"
