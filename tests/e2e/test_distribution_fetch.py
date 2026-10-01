"""Unit tests for e2e distribution URL fetch helpers."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

E2E_DIR = Path(__file__).resolve().parents[2] / "e2e"
sys.path.insert(0, str(E2E_DIR))

from distribution_fetch import (  # noqa: E402
    DistributionFetchError,
    distribution_client_from_config,
    distribution_fetch_retry_policy_summary,
    fetch_and_verify_sha256,
    fetch_bytes,
    fetch_pulp_results_json,
    format_distribution_fetch_exhausted_message,
    format_http_status_error,
    normalize_sha256_hex,
    probe_http_get_status,
    pulp_results_json_url,
)


def test_normalize_sha256_hex_strips_prefix() -> None:
    assert normalize_sha256_hex("sha256:ABC") == "abc"


def test_pulp_results_json_url_from_artifact_entry() -> None:
    pulp_results = {
        "artifacts": {"pulp_results.json": {"url": "https://example.com/artifacts/pulp_results.json"}},
        "distributions": {},
    }
    assert pulp_results_json_url(pulp_results) == "https://example.com/artifacts/pulp_results.json"


def test_pulp_results_json_url_from_distributions_base() -> None:
    pulp_results = {
        "artifacts": {},
        "distributions": {"artifacts": "https://example.com/ns/build/artifacts/"},
    }
    assert pulp_results_json_url(pulp_results) == "https://example.com/ns/build/artifacts/pulp_results.json"


def test_distribution_client_from_config_uses_cert(tmp_path: Path) -> None:
    cert = tmp_path / "tls.crt"
    key = tmp_path / "tls.key"
    cert.write_text("cert")
    key.write_text("key")
    config = tmp_path / "cli.toml"
    config.write_text('[cli]\nbase_url = "https://example.com"\ncert = "tls.crt"\nkey = "tls.key"\n')
    with patch("distribution_fetch.DistributionClient") as mock_client:
        distribution_client_from_config(config)
    mock_client.assert_called_once_with(cert=str(cert), key=str(key))


def test_distribution_client_from_config_uses_basic_auth(tmp_path: Path) -> None:
    config = tmp_path / "cli.toml"
    config.write_text('[cli]\nbase_url = "https://example.com"\nusername = "user"\npassword = "pass"\n')
    with patch("distribution_fetch.DistributionClient") as mock_client:
        distribution_client_from_config(config)
    mock_client.assert_called_once_with(username="user", password="pass")


def test_distribution_client_from_config_prefers_basic_auth_over_cert(tmp_path: Path) -> None:
    cert = tmp_path / "tls.crt"
    key = tmp_path / "tls.key"
    cert.write_text("cert")
    key.write_text("key")
    config = tmp_path / "cli.toml"
    config.write_text(
        '[cli]\nbase_url = "https://example.com"\n'
        'username = "user"\npassword = "pass"\n'
        'cert = "tls.crt"\nkey = "tls.key"\n'
    )
    with patch("distribution_fetch.DistributionClient") as mock_client:
        distribution_client_from_config(config)
    mock_client.assert_called_once_with(username="user", password="pass")


def test_distribution_client_from_config_oauth_only_raises(tmp_path: Path) -> None:
    config = tmp_path / "cli.toml"
    config.write_text('[cli]\nbase_url = "https://example.com"\nclient_id = "id"\nclient_secret = "secret"\n')
    with pytest.raises(DistributionFetchError, match="OAuth"):
        distribution_client_from_config(config)


def test_fetch_and_verify_sha256_match() -> None:
    body = b"rpm payload"
    expected = hashlib.sha256(body).hexdigest()
    client = MagicMock()
    response = MagicMock()
    response.is_error = False
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.iter_bytes = MagicMock(return_value=iter([body]))
    client.session.stream.return_value.__enter__.return_value = response

    fetch_and_verify_sha256(client, "https://example.com/pkg.rpm", expected, label="RPM")


def test_fetch_and_verify_sha256_mismatch() -> None:
    client = MagicMock()
    response = MagicMock()
    response.is_error = False
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.iter_bytes = MagicMock(return_value=iter([b"other"]))
    client.session.stream.return_value.__enter__.return_value = response

    with pytest.raises(DistributionFetchError, match="SHA256 mismatch") as exc_info:
        fetch_and_verify_sha256(client, "https://example.com/pkg.rpm", "a" * 64, label="RPM")
    assert exc_info.value.url == "https://example.com/pkg.rpm"
    assert exc_info.value.label == "RPM"


def test_format_http_status_error_includes_body() -> None:
    request = httpx.Request("GET", "https://example.com/missing.rpm")
    response = httpx.Response(404, text='{"detail":"not found"}', request=request)
    exc = httpx.HTTPStatusError("not found", request=request, response=response)
    message = format_http_status_error(exc, url="https://example.com/missing.rpm", label="RPM")
    assert "HTTP 404" in message
    assert "not found" in message


def test_format_http_status_error_reads_unread_streaming_response_body() -> None:
    class UnreadStreamResponse:
        status_code = 404
        reason_phrase = "Not Found"
        headers = {"content-type": "text/plain; charset=utf-8", "content-length": "9"}

        @property
        def text(self) -> str:
            raise RuntimeError("Attempted to access streaming response content, without having called `read()`.")

        def read(self) -> bytes:
            return b"Not Found"

    request = httpx.Request("GET", "https://example.com/missing.rpm")
    response = UnreadStreamResponse()
    exc = httpx.HTTPStatusError("not found", request=request, response=response)  # type: ignore[arg-type]
    message = format_http_status_error(exc, url="https://example.com/missing.rpm", label="RPM")
    assert "response body: Not Found" in message


def test_fetch_bytes_retries_transient_404() -> None:
    body = b"payload"
    client = MagicMock()
    ok_response = MagicMock()
    ok_response.is_error = False
    ok_response.status_code = 200
    ok_response.raise_for_status = MagicMock()
    ok_response.iter_bytes = MagicMock(return_value=iter([body]))

    missing_request = httpx.Request("GET", "https://example.com/missing")
    missing_response = httpx.Response(404, text="missing", request=missing_request)
    bad_response = MagicMock()
    bad_response.is_error = True
    bad_response.status_code = 404
    bad_response.read = MagicMock(return_value=b"missing")
    bad_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("not found", request=missing_request, response=missing_response)
    )

    client.session.stream.return_value.__enter__.side_effect = [bad_response, ok_response]

    with patch("distribution_fetch.time.sleep"):
        assert fetch_bytes(client, "https://example.com/missing", label="artifact") == body


def test_distribution_fetch_retry_policy_summary() -> None:
    summary = distribution_fetch_retry_policy_summary()
    assert "max_wait_s=" in summary
    assert "404" in summary


def test_probe_http_get_status() -> None:
    client = MagicMock()
    response = MagicMock()
    response.is_error = False
    response.status_code = 404
    client.session.stream.return_value.__enter__.return_value = response
    assert probe_http_get_status(client, "https://example.com/missing") == 404


def test_format_distribution_fetch_exhausted_message() -> None:
    request = httpx.Request("GET", "https://example.com/pulp_results.json")
    response = httpx.Response(404, text="missing", request=request)
    exc = httpx.HTTPStatusError("missing", request=request, response=response)
    message = format_distribution_fetch_exhausted_message(
        exc, url="https://example.com/pulp_results.json", label="pulp_results.json", attempts=8, elapsed_s=74.2
    )
    assert "HTTP 404" in message
    assert "retries: 8 attempt(s)" in message
    assert "pulp-content" in message


def test_fetch_bytes_http_status_error() -> None:
    client = MagicMock()
    request = httpx.Request("GET", "https://example.com/missing")
    response = httpx.Response(404, text="missing", request=request)
    error = httpx.HTTPStatusError("not found", request=request, response=response)
    mock_response = MagicMock()
    mock_response.is_error = True
    mock_response.status_code = 404
    mock_response.read = MagicMock(return_value=b"missing")
    mock_response.raise_for_status.side_effect = error
    client.session.stream.return_value.__enter__.return_value = mock_response

    with patch("distribution_fetch.DISTRIBUTION_FETCH_RETRY_ATTEMPTS", 1), patch("distribution_fetch.time.sleep"):
        with pytest.raises(DistributionFetchError, match="HTTP 404") as exc_info:
            fetch_bytes(client, "https://example.com/missing", label="artifact")
    assert "retries: 1 attempt(s)" in str(exc_info.value)


def test_fetch_bytes_http_error() -> None:
    client = MagicMock()
    client.session.stream.side_effect = httpx.HTTPError("boom")

    with pytest.raises(DistributionFetchError, match="HTTP GET failed"):
        fetch_bytes(client, "https://example.com/missing", label="artifact")


def _mock_pulp_results_response(body: bytes) -> MagicMock:
    response = MagicMock()
    response.is_error = False
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.iter_bytes = MagicMock(return_value=iter([body]))
    return response


def test_fetch_pulp_results_json_polls_stale_last_updated() -> None:
    stale = b'{"version": "1.0.0", "last_updated": "2020-01-01", "distributions": {}}'
    ready = (
        b'{"version": "1.0.0", "last_updated": "2026-06-15", "distributions": {"tag1": "https://example.com/tag1/"}}'
    )
    client = MagicMock()
    client.session.stream.return_value.__enter__.side_effect = [
        _mock_pulp_results_response(stale),
        _mock_pulp_results_response(ready),
    ]

    with patch("distribution_fetch.time.sleep"):
        doc = fetch_pulp_results_json(
            client,
            "https://example.com/pulp_results.json",
            min_last_updated="2026-06-15",
            required_distribution_keys=frozenset({"tag1"}),
        )
    assert doc["last_updated"] == "2026-06-15"
    assert doc["distributions"]["tag1"].startswith("https://")
