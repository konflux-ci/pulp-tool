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

RESULTS_JSON_FILENAME = "pulp_results.json"
LOGGER = logging.getLogger("e2e.distribution_fetch")


class DistributionFetchError(Exception):
    """Raised when a distribution URL fetch or checksum verification fails."""

    def __init__(self, message: str, *, url: str | None = None, label: str | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.label = label


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
    try:
        body = response.text
        if body:
            preview = body if len(body) <= 800 else f"{body[:800]}… (truncated, {len(body)} chars total)"
            lines.append(f"response body: {preview}")
    except Exception as body_exc:  # noqa: BLE001 — diagnostic helper
        lines.append(f"response body: <unreadable: {body_exc}>")
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


def normalize_sha256_hex(value: str) -> str:
    """Strip optional ``sha256:`` prefix and return lowercase hex."""
    normalized = value.strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized.removeprefix("sha256:")
    return normalized


def fetch_bytes(client: DistributionClient, url: str, *, label: str) -> bytes:
    """GET ``url`` and return the response body."""
    LOGGER.info("HTTP GET %s: %s", label, url)
    started = time.monotonic()
    try:
        with client.session.stream("GET", url) as response:
            status_code = response.status_code
            response.raise_for_status()
            body = b"".join(response.iter_bytes(chunk_size=65536))
    except httpx.HTTPStatusError as exc:
        elapsed_ms = (time.monotonic() - started) * 1000
        LOGGER.error("HTTP GET %s failed after %.0f ms: %s", label, elapsed_ms, exc)
        raise DistributionFetchError(
            format_http_status_error(exc, url=url, label=label),
            url=url,
            label=label,
        ) from exc
    except httpx.HTTPError as exc:
        elapsed_ms = (time.monotonic() - started) * 1000
        LOGGER.error("HTTP GET %s failed after %.0f ms: %s", label, elapsed_ms, exc)
        raise DistributionFetchError(
            f"{label}: HTTP GET failed for {url}: {exc}",
            url=url,
            label=label,
        ) from exc

    elapsed_ms = (time.monotonic() - started) * 1000
    LOGGER.info(
        "HTTP GET %s complete: status=%s bytes=%d elapsed_ms=%.0f",
        label,
        status_code,
        len(body),
        elapsed_ms,
    )
    return body


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
    byte_count = 0
    status_code: int | None = None
    try:
        with client.session.stream("GET", url) as response:
            status_code = response.status_code
            response.raise_for_status()
            hasher = hashlib.sha256()
            for chunk in response.iter_bytes(chunk_size=65536):
                byte_count += len(chunk)
                hasher.update(chunk)
    except httpx.HTTPStatusError as exc:
        elapsed_ms = (time.monotonic() - started) * 1000
        LOGGER.error("SHA256 verify %s failed after %.0f ms: %s", label, elapsed_ms, exc)
        raise DistributionFetchError(
            format_http_status_error(exc, url=url, label=label),
            url=url,
            label=label,
        ) from exc
    except httpx.HTTPError as exc:
        elapsed_ms = (time.monotonic() - started) * 1000
        LOGGER.error("SHA256 verify %s failed after %.0f ms: %s", label, elapsed_ms, exc)
        raise DistributionFetchError(
            f"{label}: HTTP GET failed for {url}: {exc}",
            url=url,
            label=label,
        ) from exc

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
