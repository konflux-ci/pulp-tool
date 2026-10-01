"""PulpClient additional tests."""

from unittest.mock import patch

import httpx
import pytest

from pulp_tool.api import PulpClient
from pulp_tool.models.pulp_results import PulpResultsDocument


class TestPulpClientAdditional:
    """Additional tests for PulpClient class to achieve 100% coverage."""

    def test_tomllib_import_error(self) -> None:
        """Test tomllib import error fallback."""
        import pulp_tool.api.pulp_client.client

        assert hasattr(pulp_tool.api.pulp_client.client, "tomllib")

    def test_chunked_get_empty_param_fallback(self, mock_pulp_client, httpx_mock) -> None:
        """Test _chunked_get method with empty parameter fallback."""
        httpx_mock.get("https://test.com/api").mock(return_value=httpx.Response(200, json={"results": []}))
        params = {"empty_param": ""}
        result = mock_pulp_client._chunked_get("https://test.com/api", params, chunk_param="empty_param", chunk_size=50)
        assert result.status_code == 200
        assert len(result.json()["results"]) == 0

    def test_chunked_get_no_chunks_processed(self, mock_pulp_client, httpx_mock) -> None:
        """Test _chunked_get method when chunking encounters an error."""
        httpx_mock.get("https://test.com/api?test_param=value1").mock(side_effect=httpx.HTTPError("Network error"))
        params = {"test_param": "value1,value2"}
        with pytest.raises(httpx.HTTPError, match="Network error"):
            mock_pulp_client._chunked_get("https://test.com/api", params, chunk_param="test_param", chunk_size=1)

    def test_request_params_with_headers_property(self, mock_config) -> None:
        """Test request_params property when headers property returns non-None."""
        client = PulpClient(mock_config)
        with patch("pulp_tool.api.PulpClient.headers", new_callable=lambda: lambda self: {"Custom-Header": "test"}):
            params = client.request_params
        assert "headers" in params

    def test_repository_operation_update_distro_without_publication(self, mock_pulp_client, httpx_mock) -> None:
        """Test repository_operation method for updating distribution without publication."""
        httpx_mock.patch("https://pulp.example.com/pulp/api/v3/distributions/12345/").mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/distributions/rpm/rpm/12345/"})
        )
        result = mock_pulp_client.repository_operation(
            "update_distro", "rpm", name="test-distro", distribution_href="/pulp/api/v3/distributions/12345/"
        )
        assert result.status_code == 200
        assert result.json()["pulp_href"] == "/pulp/api/v3/distributions/rpm/rpm/12345/"

    def test_repository_operation_invalid_operation(self, mock_pulp_client) -> None:
        """Test repository_operation method with invalid operation."""
        with pytest.raises(ValueError, match="Unknown operation"):
            mock_pulp_client.repository_operation("invalid", "rpm", name="test")

    def test_add_uploaded_artifact_to_results_model_rpm_key_is_basename(self, mock_pulp_client, tmp_path) -> None:
        """RPM incremental path uses basename as artifact key (is_rpm branch)."""
        from pulp_tool.models import RepositoryRefs

        rpm_path = tmp_path / "my-pkg-1.0-1.x86_64.rpm"
        rpm_path.write_bytes(b"rpm-bytes")
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
        labels = {"build_id": "test-build", "arch": "x86_64"}
        urls = {"rpms": "https://pulp.example.com/content/test/rpms/"}
        with (
            patch("pulp_tool.api.pulp_client.results.calculate_sha256_checksum", return_value="a" * 64),
            patch.object(
                mock_pulp_client, "_build_artifact_distribution_url", return_value="https://dist.example/foo.rpm"
            ),
        ):
            mock_pulp_client.add_uploaded_artifact_to_results_model(
                results_model, local_path=str(rpm_path), labels=labels, is_rpm=True, distribution_urls=urls
            )
        assert "my-pkg-1.0-1.x86_64.rpm" in results_model.artifacts
        meta = results_model.artifacts["my-pkg-1.0-1.x86_64.rpm"]
        assert meta.url == "https://dist.example/foo.rpm"
        assert meta.sha256 == "a" * 64
