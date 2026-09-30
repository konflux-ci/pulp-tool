"""
Tests for PulpClient async methods.

This module tests async methods that need coverage.
Uses asyncio.run() so tests work without pytest-asyncio.
"""

import asyncio
from unittest.mock import Mock, patch

import httpx
import pytest

from pulp_tool.api import OAuth2ClientCredentialsAuth, PulpClient
from pulp_tool.models.pulp_results import PulpResultsDocument


class TestPulpClientAsync:
    """Test PulpClient async methods."""

    def test_prepare_async_kwargs_with_auth(self, mock_config) -> None:
        """Test _prepare_async_kwargs with auth configured (lines 762-764)."""
        config_oauth = {k: v for k, v in mock_config.items() if k not in ("cert", "key")}
        client = PulpClient(config_oauth)
        auth = OAuth2ClientCredentialsAuth("client-id", "client-secret", "token-url")
        client._auth = auth
        kwargs = client._prepare_async_kwargs()
        assert "auth" in kwargs
        assert kwargs["auth"] == auth

    def test_prepare_async_kwargs_without_auth(self, mock_config) -> None:
        """Test _prepare_async_kwargs without auth."""
        config_no_auth = {
            "base_url": mock_config["base_url"],
            "api_root": mock_config["api_root"],
            "domain": mock_config.get("domain", ""),
        }
        client = PulpClient(config_no_auth)
        with patch.object(type(client), "auth", property(lambda self: None)):
            kwargs = client._prepare_async_kwargs()
            assert "auth" not in kwargs

    def test_prepare_async_kwargs_merges_correlation_and_call_headers(self, mock_config) -> None:
        """Correlation headers merge with per-call headers (diff coverage for _prepare_async_kwargs)."""
        config_oauth = {k: v for k, v in mock_config.items() if k not in ("cert", "key")}
        client = PulpClient(config_oauth, correlation_namespace="n", correlation_build_id="b")
        kwargs = client._prepare_async_kwargs(headers={"X-Custom": "1"})
        assert kwargs["headers"]["X-Custom"] == "1"
        assert "X-Correlation-ID" in kwargs["headers"]

    def test_async_session_default_headers_include_correlation(self, mock_config) -> None:
        """Async client picks up correlation ID in default headers (diff coverage line ~226)."""

        async def _run() -> None:
            config_oauth = {k: v for k, v in mock_config.items() if k not in ("cert", "key")}
            client = PulpClient(config_oauth, correlation_namespace="ns", correlation_build_id="bid")
            ac = client._get_async_session()
            low = {k.lower(): v for k, v in ac.headers.items()}
            assert low.get("x-correlation-id") == "ns/bid"
            await ac.aclose()

        asyncio.run(_run())

    def test_prepare_async_kwargs_with_existing_auth(self, mock_config) -> None:
        """Test _prepare_async_kwargs when auth already in kwargs."""
        client = PulpClient(mock_config)
        auth = OAuth2ClientCredentialsAuth("client-id", "client-secret", "token-url")
        client._auth = auth
        other_auth = OAuth2ClientCredentialsAuth("other-id", "other-secret", "token-url")
        kwargs = client._prepare_async_kwargs(auth=other_auth)
        assert kwargs["auth"] == other_auth

    def test_async_get(self, mock_config) -> None:
        """Test async_get method."""
        import respx

        async def _run() -> None:
            client = PulpClient(mock_config)
            with respx.mock:
                respx.post("https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token").mock(
                    return_value=httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
                )
                respx.get("https://test.com/api").mock(return_value=httpx.Response(200, json={"status": "ok"}))
                response = await client.async_get("https://test.com/api")
                assert response.status_code == 200
                assert response.json()["status"] == "ok"
                if hasattr(client, "_async_session") and client._async_session:
                    await client._async_session.aclose()

        asyncio.run(_run())

    def test_async_post(self, mock_config) -> None:
        """Test async_post method."""
        import respx

        async def _run() -> None:
            client = PulpClient(mock_config)
            with respx.mock:
                respx.post("https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token").mock(
                    return_value=httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
                )
                respx.post("https://test.com/api").mock(return_value=httpx.Response(201, json={"status": "created"}))
                response = await client.async_post("https://test.com/api", json={"data": "test"})
                assert response.status_code == 201
                assert response.json()["status"] == "created"
                if hasattr(client, "_async_session") and client._async_session:
                    await client._async_session.aclose()

        asyncio.run(_run())

    def test_async_get_rpm_by_pkg_ids(self, mock_config) -> None:
        """Test async_get_rpm_by_pkg_ids method."""
        import respx

        async def _run() -> None:
            client = PulpClient(mock_config)
            with respx.mock:
                respx.post("https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token").mock(
                    return_value=httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
                )
                respx.get(
                    "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/rpm/packages/"
                    "?pkgId__in=abcd1234%2Cefgh5678"
                ).mock(return_value=httpx.Response(200, json={"results": [{"pkgId": "abcd1234"}]}))
                pkg_ids = ["abcd1234", "efgh5678"]
                response = await client.async_get_rpm_by_pkgIDs(pkg_ids)
                assert response.status_code == 200
                assert len(response.json()["results"]) == 1
                if hasattr(client, "_async_session") and client._async_session:
                    await client._async_session.aclose()

        asyncio.run(_run())

    def test_async_get_rpm_by_nvr_empty(self, mock_config) -> None:
        """Test async_get_rpm_by_nvr with empty list returns empty results (line 1320)."""
        import respx

        async def _run() -> None:
            client = PulpClient(mock_config)
            with respx.mock:
                respx.post("https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token").mock(
                    return_value=httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
                )
                response = await client.async_get_rpm_by_nvr([])
                assert response.status_code == 200
                assert response.json()["count"] == 0
                assert response.json()["results"] == []
                if hasattr(client, "_async_session") and client._async_session:
                    await client._async_session.aclose()

        asyncio.run(_run())


class TestPulpClientErrorPaths:
    """Test PulpClient error paths."""

    def test_repository_operation_update_distro_no_href(self, mock_pulp_client) -> None:
        """Test repository_operation update_distro without distribution_href (line 939)."""
        with pytest.raises(ValueError, match="Distribution href is required"):
            mock_pulp_client.repository_operation(
                "update_distro", repo_type="file", name="test", publication="/pub/123/", distribution_href=None
            )

    def test_get_content_type_from_href_rpm(self) -> None:
        """Test _get_content_type_from_href for RPM."""
        from pulp_tool.api.pulp_client import PulpClient

        result = PulpClient._get_content_type_from_href("/api/v3/content/rpm/packages/123/")
        assert result == "rpm.package"

    def test_get_content_type_from_href_file(self) -> None:
        """Test _get_content_type_from_href for file."""
        from pulp_tool.api.pulp_client import PulpClient

        result = PulpClient._get_content_type_from_href("/api/v3/content/file/files/123/")
        assert result == "file.file"

    def test_get_content_type_from_href_unknown(self) -> None:
        """Test _get_content_type_from_href for unknown."""
        from pulp_tool.api.pulp_client import PulpClient

        result = PulpClient._get_content_type_from_href("/api/v3/content/unknown/123/")
        assert result == "unknown"

    def test_build_rpm_distribution_url(self, mock_pulp_client) -> None:
        """Test _build_rpm_distribution_url."""
        distribution_urls = {"rpms": "https://example.com/rpms/"}
        result = mock_pulp_client._build_rpm_distribution_url("test/package.rpm", distribution_urls)
        assert result == "https://example.com/rpms/Packages/p/package.rpm"

    def test_build_rpm_distribution_url_packages_prefix_lowercase_letter(self, mock_pulp_client) -> None:
        """Letter under Packages/ is lowercase first char of RPM basename."""
        distribution_urls = {"rpms": "https://example.com/rpms/"}
        result = mock_pulp_client._build_rpm_distribution_url("Packages/L/whale.rpm", distribution_urls)
        assert result == "https://example.com/rpms/Packages/w/whale.rpm"

    def test_build_rpm_distribution_url_no_rpms(self, mock_pulp_client) -> None:
        """Test _build_rpm_distribution_url without rpms URL."""
        distribution_urls: dict[str, str] = {}
        result = mock_pulp_client._build_rpm_distribution_url("test/package.rpm", distribution_urls)
        assert result == "test/package.rpm"

    def test_build_rpm_distribution_url_uses_rpms_signed_when_label(self, mock_pulp_client) -> None:
        """Signed content uses rpms_signed base when signed_by is in labels."""
        distribution_urls = {
            "rpms": "https://example.com/ns/build/rpms/",
            "rpms_signed": "https://example.com/ns/build/rpms-signed/",
        }
        labels = {"signed_by": "alias1"}
        result = mock_pulp_client._build_rpm_distribution_url(
            "foo.rpm", distribution_urls, labels=labels, target_arch_repo=False
        )
        assert result == "https://example.com/ns/build/rpms-signed/Packages/f/foo.rpm"

    def test_build_rpm_distribution_url_target_arch_repo(self, mock_pulp_client) -> None:
        """Per-arch mode builds URL from namespace and labels.arch."""
        labels = {"arch": "x86_64"}
        result = mock_pulp_client._build_rpm_distribution_url("pkg.rpm", {}, labels=labels, target_arch_repo=True)
        assert result == "https://pulp.example.com/api/pulp-content/test-domain/x86_64/Packages/p/pkg.rpm"

    def test_build_rpm_distribution_url_target_arch_repo_with_signed_by_label(self, mock_pulp_client) -> None:
        """signed_by label does not change per-arch distribution path (same as unsigned)."""
        labels = {"arch": "aarch64", "signed_by": "key-1"}
        result = mock_pulp_client._build_rpm_distribution_url("pkg.rpm", {}, labels=labels, target_arch_repo=True)
        assert result == "https://pulp.example.com/api/pulp-content/test-domain/aarch64/Packages/p/pkg.rpm"

    def test_build_rpm_packages_url_for_arch_returns_relative_when_no_rpm_basename(self, mock_pulp_client) -> None:
        """_build_rpm_packages_url_for_arch returns input when path has no usable RPM basename."""
        assert mock_pulp_client._build_rpm_packages_url_for_arch("x86_64", "") == ""
        assert mock_pulp_client._build_rpm_packages_url_for_arch("s390x", "   ") == "   "

    def test_build_rpm_distribution_url_target_arch_repo_unsupported_arch_uses_labels_base(
        self, mock_pulp_client
    ) -> None:
        """Non-SUPPORTED arch in labels falls back to label-derived base then Packages/ layout."""
        labels = {"arch": "bogus"}
        result = mock_pulp_client._build_rpm_distribution_url("pkg.rpm", {}, labels=labels, target_arch_repo=True)
        assert result == "https://pulp.example.com/api/pulp-content/test-domain/bogus/Packages/p/pkg.rpm"

    def test_build_rpm_distribution_url_target_arch_repo_unsupported_arch_empty_relative(
        self, mock_pulp_client
    ) -> None:
        """Fallback per-arch URL path returns relative_path when it is not an RPM filename."""
        labels = {"arch": "bogus"}
        result = mock_pulp_client._build_rpm_distribution_url("", {}, labels=labels, target_arch_repo=True)
        assert result == ""

    def test_rpm_distribution_base_url_falls_back_to_noarch_when_invalid(self, mock_pulp_client) -> None:
        """Invalid sanitized arch segment uses noarch in per-arch URL (defensive path)."""
        with patch("pulp_tool.api.pulp_client.content_query.validate_build_id", return_value=False):
            labels = {"arch": "x86_64"}
            base = mock_pulp_client._rpm_distribution_base_url_from_labels(labels)
        assert base == "https://pulp.example.com/api/pulp-content/test-domain/noarch/"

    def test_build_file_distribution_url_with_arch(self) -> None:
        """Test _build_file_distribution_url with arch prefix."""
        from pulp_tool.api.pulp_client import PulpClient

        distribution_urls = {"logs": "https://example.com/logs/"}
        result = PulpClient._build_file_distribution_url("x86_64/test.log", {}, distribution_urls)
        assert result == "https://example.com/logs/x86_64/test.log"

    def test_build_file_distribution_url_sbom(self) -> None:
        """Test _build_file_distribution_url for SBOM."""
        from pulp_tool.api.pulp_client import PulpClient

        distribution_urls = {"sbom": "https://example.com/sbom/"}
        result = PulpClient._build_file_distribution_url("test.sbom.json", {}, distribution_urls)
        assert result == "https://example.com/sbom/test.sbom.json"

    def test_build_file_distribution_url_log_with_arch_label(self) -> None:
        """Test _build_file_distribution_url for log with arch label."""
        from pulp_tool.api.pulp_client import PulpClient

        distribution_urls = {"logs": "https://example.com/logs/"}
        labels = {"arch": "x86_64"}
        result = PulpClient._build_file_distribution_url("test.log", labels, distribution_urls)
        assert result == "https://example.com/logs/x86_64/test.log"

    def test_build_file_distribution_url_log_without_arch(self) -> None:
        """Test _build_file_distribution_url for log without arch."""
        from pulp_tool.api.pulp_client import PulpClient

        distribution_urls = {"logs": "https://example.com/logs/"}
        result = PulpClient._build_file_distribution_url("test.log", {}, distribution_urls)
        assert result == "https://example.com/logs/test.log"

    def test_build_file_distribution_url_no_urls(self) -> None:
        """Test _build_file_distribution_url without distribution URLs."""
        from pulp_tool.api.pulp_client import PulpClient

        result = PulpClient._build_file_distribution_url("test.log", {}, {})
        assert result == "test.log"

    def test_gather_content_data_with_extra_artifacts(self, mock_pulp_client, httpx_mock) -> None:
        """Test gather_content_data with extra_artifacts."""
        call_count = 0

        def mock_find_content(search_type, value) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Mock(json=lambda: {"results": []})
            else:
                return Mock(json=lambda: {"results": [{"pulp_href": "/content/123/"}]})

        mock_pulp_client.find_content = Mock(side_effect=mock_find_content)
        from pulp_tool.models.artifacts import ExtraArtifactRef

        extra_artifacts = [ExtraArtifactRef(pulp_href="/content/123/")]
        result = mock_pulp_client.gather_content_data("test-build", extra_artifacts=extra_artifacts)
        assert result is not None
        assert mock_pulp_client.find_content.call_count == 2

    def test_gather_content_data_href_query_exception(self, mock_pulp_client, httpx_mock) -> None:
        """Test gather_content_data when href query raises exception."""
        call_count = 0

        def mock_find_content(search_type, value) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Mock(json=lambda: {"results": []})
            else:
                raise Exception("Href query failed")

        mock_pulp_client.find_content = Mock(side_effect=mock_find_content)
        from pulp_tool.models.artifacts import ExtraArtifactRef

        extra_artifacts = [ExtraArtifactRef(pulp_href="/content/123/")]
        with patch("pulp_tool.api.pulp_client.results.logging") as mock_logging:
            result = mock_pulp_client.gather_content_data("test-build", extra_artifacts=extra_artifacts)
            assert result is not None
            mock_logging.error.assert_called()

    def test_build_results_structure_no_build_id(self, mock_pulp_client) -> None:
        """Test build_results_structure with no build_id in labels."""
        from pulp_tool.models import RepositoryRefs

        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="rpms-prn",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        from pulp_tool.models.artifacts import PulpContentRow

        content_results = [
            PulpContentRow.model_validate(
                {
                    "pulp_href": "/content/123/",
                    "artifacts": {"test.txt": "/artifacts/123/"},
                    "relative_path": "test.txt",
                }
            )
        ]
        file_info_map = {"/artifacts/123/": Mock(file="test.txt@sha256:abc", sha256="abc")}
        distribution_urls = {"logs": "https://example.com/logs/"}
        with patch("pulp_tool.api.pulp_client.results.logging") as mock_logging:
            mock_pulp_client.build_results_structure(results_model, content_results, file_info_map, distribution_urls)
            mock_logging.warning.assert_called()
