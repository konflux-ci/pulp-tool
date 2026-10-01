"""Tests for pulp_upload.py module."""

from unittest.mock import Mock, patch

import httpx

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.pulp_api import TaskResponse
from pulp_tool.services.upload_service import _distribution_urls_for_context


class TestFindArtifactContent:
    """Test _find_artifact_content function."""

    def test_find_artifact_content_no_artifacts_dict(self, mock_pulp_client) -> None:
        """Test _find_artifact_content when artifacts_dict is empty."""
        from pulp_tool.services.upload_collect import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_response = Mock(spec=httpx.Response)
        mock_response.json.return_value = {"results": [{"artifacts": {}}]}
        mock_pulp_client.find_content = Mock(return_value=mock_response)
        with patch("pulp_tool.services.upload_collect.logging") as mock_logging:
            result = _find_artifact_content(mock_pulp_client, task_response)
            assert result is None
            mock_logging.error.assert_called()

    def test_find_artifact_content_non_dict_artifacts(self, mock_pulp_client) -> None:
        """Test _find_artifact_content when artifacts is not a dict."""
        from pulp_tool.services.upload_collect import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_response = Mock(spec=httpx.Response)
        mock_response.json.return_value = {"results": [{"artifacts": None}]}
        mock_pulp_client.find_content = Mock(return_value=mock_response)
        with patch("pulp_tool.services.upload_collect.logging") as mock_logging:
            result = _find_artifact_content(mock_pulp_client, task_response)
            assert result is None
            mock_logging.error.assert_called()

    def test_find_artifact_content_no_file_value(self, mock_pulp_client, httpx_mock) -> None:
        """Test _find_artifact_content when artifact response has no file value."""
        from pulp_tool.services.upload_collect import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_content_response = Mock(spec=httpx.Response)
        mock_content_response.json.return_value = {"results": [{"artifacts": {"test.txt": "/api/v3/artifacts/12345/"}}]}
        mock_pulp_client.find_content = Mock(return_value=mock_content_response)
        mock_artifact_response = Mock(spec=httpx.Response)
        mock_artifact_response.json.return_value = {"results": [{"sha256": "abc123"}]}
        mock_pulp_client.get_file_locations = Mock(return_value=mock_artifact_response)
        with patch("pulp_tool.services.upload_collect.logging") as mock_logging:
            result = _find_artifact_content(mock_pulp_client, task_response)
            assert result is None
            mock_logging.error.assert_called()

    def test_find_artifact_content_no_sha256_value(self, mock_pulp_client, httpx_mock) -> None:
        """Test _find_artifact_content when artifact response has no sha256 value."""
        from pulp_tool.services.upload_collect import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_content_response = Mock(spec=httpx.Response)
        mock_content_response.json.return_value = {"results": [{"artifacts": {"test.txt": "/api/v3/artifacts/12345/"}}]}
        mock_pulp_client.find_content = Mock(return_value=mock_content_response)
        mock_artifact_response = Mock(spec=httpx.Response)
        mock_artifact_response.json.return_value = {"results": [{"file": "test.txt@sha256:abc123"}]}
        mock_pulp_client.get_file_locations = Mock(return_value=mock_artifact_response)
        with patch("pulp_tool.services.upload_collect.logging") as mock_logging:
            result = _find_artifact_content(mock_pulp_client, task_response)
            assert result is None
            mock_logging.error.assert_called()

    def test_find_artifact_content_success(self, mock_pulp_client, httpx_mock) -> None:
        """Test _find_artifact_content successful path."""
        from pulp_tool.services.upload_collect import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_content_response = Mock(spec=httpx.Response)
        mock_content_response.json.return_value = {"results": [{"artifacts": {"test.txt": "/api/v3/artifacts/12345/"}}]}
        mock_pulp_client.find_content = Mock(return_value=mock_content_response)
        mock_artifact_response = Mock(spec=httpx.Response)
        mock_artifact_response.json.return_value = {"results": [{"file": "test.txt@sha256:abc123", "sha256": "abc123"}]}
        mock_pulp_client.get_file_locations = Mock(return_value=mock_artifact_response)
        result = _find_artifact_content(mock_pulp_client, task_response)
        assert result is not None
        assert result[0] == "test.txt@sha256:abc123"
        assert result[1] == "abc123"

    def test_find_artifact_content_bare_list_json(self, mock_pulp_client, httpx_mock) -> None:
        """find_content JSON may be a list of content objects instead of paginated dict."""
        from pulp_tool.services.upload_collect import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_content_response = Mock(spec=httpx.Response)
        mock_content_response.json.return_value = [{"artifacts": {"test.txt": "/api/v3/artifacts/12345/"}}]
        mock_pulp_client.find_content = Mock(return_value=mock_content_response)
        mock_artifact_response = Mock(spec=httpx.Response)
        mock_artifact_response.json.return_value = {"results": [{"file": "test.txt@sha256:abc123", "sha256": "abc123"}]}
        mock_pulp_client.get_file_locations = Mock(return_value=mock_artifact_response)
        result = _find_artifact_content(mock_pulp_client, task_response)
        assert result == ("test.txt@sha256:abc123", "abc123")


class TestParseOciReference:
    """Test _parse_oci_reference function."""

    def test_parse_oci_reference_with_digest(self) -> None:
        """Test _parse_oci_reference with digest."""
        from pulp_tool.services.upload_collect import _parse_oci_reference

        with patch("pulp_tool.services.upload_collect.logging") as mock_logging:
            image_url, digest = _parse_oci_reference("quay.io/org/repo@sha256:abc123")
            assert image_url == "quay.io/org/repo"
            assert digest == "sha256:abc123"
            mock_logging.debug.assert_called()

    def test_parse_oci_reference_without_digest(self) -> None:
        """Test _parse_oci_reference without digest."""
        from pulp_tool.services.upload_collect import _parse_oci_reference

        with patch("pulp_tool.services.upload_collect.logging") as mock_logging:
            image_url, digest = _parse_oci_reference("quay.io/org/repo")
            assert image_url == "quay.io/org/repo"
            assert digest == ""
            mock_logging.debug.assert_called()

    def test_format_sha256_digest_already_prefixed(self) -> None:
        """Test _format_sha256_digest leaves sha256: prefix unchanged."""
        from pulp_tool.services.upload_collect import _format_sha256_digest

        assert _format_sha256_digest("sha256:abc123") == "sha256:abc123"
        assert _format_sha256_digest("abc123") == "sha256:abc123"


class TestDistributionUrlsForContext:
    """Tests for _distribution_urls_for_context helper."""

    def test_signed_by_requests_include_signed_rpm_distro(self) -> None:
        """Non-empty signed_by is passed through get_distribution_urls_for_upload_context."""
        helper = Mock()
        helper.get_distribution_urls_for_upload_context.return_value = {"rpms": "https://example.com/rpms/"}
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package=None,
            signed_by=" gpg-key ",
            target_arch_repo=False,
        )
        result = _distribution_urls_for_context(helper, "test-build", context)
        assert result == {"rpms": "https://example.com/rpms/"}
        helper.get_distribution_urls_for_upload_context.assert_called_once_with("test-build", context)
