"""Tests for upload results collection (:mod:`pulp_tool.upload.results`)."""

import json
import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import httpx
import pytest

from pulp_tool.models.artifacts import ArtifactMetadata, ContentData, FileInfoModel, PulpContentRow
from pulp_tool.models.context import UploadContext, UploadRpmContext
from pulp_tool.models.pulp_api import TaskResponse
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.upload import results as uc
from pulp_tool.upload.results import (
    _add_distributions_to_results,
    _build_artifact_map,
    _distribution_urls_for_context,
    _extract_results_url,
    _populate_results_model,
    _save_results_to_folder,
    _serialize_results_to_json,
    _upload_and_get_results_url,
    collect_results,
)


def _minimal_context(**kwargs: Any) -> UploadContext:
    base: dict[str, Any] = {
        "build_id": "b1",
        "date_str": "2024-01-01",
        "namespace": "ns",
        "parent_package": "pkg",
    }
    base.update(kwargs)
    return UploadContext(**base)


def _minimal_refs() -> RepositoryRefs:
    return RepositoryRefs(
        rpms_href="/r/",
        rpms_prn="rp",
        logs_href="/l/",
        logs_prn="lp",
        sbom_href="/s/",
        sbom_prn="sp",
        artifacts_href="/a/",
        artifacts_prn="ap",
    )


def _empty_results_document() -> PulpResultsDocument:
    return PulpResultsDocument.from_raw({"artifacts": {}})


class TestBuildResultsStructure:
    """Test _populate_results_model function."""

    def test_build_results_structure(self, mock_pulp_client) -> None:
        """Test _populate_results_model function (lines 364-367)."""
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
        from pulp_tool.models.artifacts import FileInfoModel, PulpContentRow

        content_results = [
            PulpContentRow.model_validate({"pulp_href": "/content/123/", "artifacts": {"test.txt": "/artifacts/123/"}})
        ]
        file_info_map: dict[str, FileInfoModel] = {
            "/artifacts/123/": FileInfoModel(pulp_href="/artifacts/123/", file="test.txt@sha256:abc", sha256="abc")
        }
        context = UploadContext(
            build_id="test-build", date_str="2024-01-01", namespace="test-namespace", parent_package="test-package"
        )
        with patch("pulp_tool.upload.results.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {
                "rpms": "https://example.com/rpms/",
                "logs": "https://example.com/logs/",
            }
            mock_helper_class.return_value = mock_helper
            mock_pulp_client.build_results_structure = Mock()
            _populate_results_model(mock_pulp_client, results_model, content_results, file_info_map, context)
            mock_pulp_client.build_results_structure.assert_called_once()
            call_args = mock_pulp_client.build_results_structure.call_args
            assert call_args[0][0] == results_model
            assert call_args[0][1] == content_results
            assert call_args[0][2] == file_info_map
            mock_helper_class.assert_called_once_with(mock_pulp_client, parent_package=context.parent_package)
            mock_helper.get_distribution_urls_for_upload_context.assert_called_once_with(context.build_id, context)
            assert call_args.kwargs.get("merge") is True

    def test_populate_results_model_target_arch_repo_uses_flagged_distribution_urls(self, mock_pulp_client) -> None:
        """With target_arch_repo, distribution URLs come from get_distribution_urls_for_upload_context."""
        from pulp_tool.models.artifacts import FileInfoModel

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
        content_results: list = []
        file_info_map: dict[str, FileInfoModel] = {}
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-namespace",
            parent_package="test-package",
            target_arch_repo=True,
        )
        with patch("pulp_tool.upload.results.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {"logs": "https://example.com/logs/"}
            mock_helper_class.return_value = mock_helper
            mock_pulp_client.build_results_structure = Mock()
            _populate_results_model(mock_pulp_client, results_model, content_results, file_info_map, context)
            mock_helper.get_distribution_urls_for_upload_context.assert_called_once_with("test-build", context)
            mock_pulp_client.build_results_structure.assert_called_once()
            assert mock_pulp_client.build_results_structure.call_args.kwargs["target_arch_repo"] is True

    def test_add_distributions_to_results_target_arch_repo(self, mock_pulp_client) -> None:
        """With target_arch_repo, per-arch RPM distribution URLs are added from artifact arch labels."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        results_model.add_artifact(
            "pkg.rpm",
            "https://example.com/pkg.rpm",
            "deadbeef",
            {"arch": "x86_64", "build_id": "test-build", "namespace": "test-namespace"},
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-namespace",
            parent_package="test-package",
            target_arch_repo=True,
        )
        with patch("pulp_tool.upload.results.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {"logs": "https://example.com/logs/"}
            mock_helper.distribution_url_for_base_path.return_value = (
                "https://pulp.example.com/api/pulp-content/test-namespace/x86_64/"
            )
            mock_helper_class.return_value = mock_helper
            _add_distributions_to_results(mock_pulp_client, context, results_model)
            mock_helper.get_distribution_urls_for_upload_context.assert_called_once_with("test-build", context)
            mock_helper.distribution_url_for_base_path.assert_called_once_with("x86_64")
            assert (
                str(results_model.distributions["rpm_x86_64"])
                == "https://pulp.example.com/api/pulp-content/test-namespace/x86_64/"
            )

    def test_add_distributions_to_results_target_arch_repo_build_scoped(self, mock_pulp_client) -> None:
        """Build-scoped target-arch uses {build_id}/{arch} for per-arch distribution URLs."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        results_model.add_artifact(
            "pkg.rpm",
            "https://example.com/pkg.rpm",
            "deadbeef",
            {"arch": "x86_64", "build_id": "test-build", "namespace": "test-namespace"},
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-namespace",
            parent_package="test-package",
            target_arch_repo=True,
            target_arch_repo_build_scoped=True,
        )
        with patch("pulp_tool.upload.results.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {"logs": "https://example.com/logs/"}
            mock_helper.distribution_url_for_base_path.return_value = (
                "https://pulp.example.com/api/pulp-content/test-namespace/test-build/x86_64/"
            )
            mock_helper_class.return_value = mock_helper
            _add_distributions_to_results(mock_pulp_client, context, results_model)
            mock_helper.distribution_url_for_base_path.assert_called_once_with("test-build/x86_64")

    def test_add_distributions_to_results_omits_artifacts_for_local_artifact_results(self, mock_pulp_client) -> None:
        """Folder --artifact-results must not add a synthetic artifacts distribution entry."""
        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="rpms-prn",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
        )
        results_model = PulpResultsDocument(build_id="my-build", repositories=repositories)
        context = UploadRpmContext(
            build_id="my-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/rpms",
            artifact_results="/data/results-out",
        )
        _add_distributions_to_results(mock_pulp_client, context, results_model)
        assert "artifacts" not in results_model.distributions
        assert "rpms" in results_model.distributions
        assert "logs" in results_model.distributions

    def test_add_distributions_to_results_warns_when_no_distribution_urls(self, mock_pulp_client, caplog) -> None:
        """When no build-scoped distribution URLs are returned, log a warning."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-namespace",
            parent_package="test-package",
            target_arch_repo=False,
        )
        with patch("pulp_tool.upload.results.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {}
            mock_helper_class.return_value = mock_helper
            with caplog.at_level(logging.WARNING):
                _add_distributions_to_results(mock_pulp_client, context, results_model)
            assert "No distribution URLs found" in caplog.text


class TestSerializeResultsToJson:
    """Test _serialize_results_to_json function."""

    def test_serialize_results_to_json_success(self) -> None:
        """Test successful JSON serialization."""
        results = {"content": "test", "number": 123}
        json_content = _serialize_results_to_json(results)
        assert isinstance(json_content, str)
        parsed = json.loads(json_content)
        assert parsed == results

    def test_serialize_results_to_json_error(self) -> None:
        """Test JSON serialization with error."""

        class Unserializable:
            pass

        results = {"content": "test", "unserializable": Unserializable()}
        with pytest.raises((TypeError, ValueError)):
            _serialize_results_to_json(results)


class TestUploadAndGetResultsUrl:
    """Test _upload_and_get_results_url function."""

    def test_upload_and_get_results_url_error(self, mock_pulp_client, httpx_mock) -> None:
        """Test results upload with error."""
        httpx_mock.post(re.compile(".*/content/file/files/")).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        args = Mock()
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"
        with patch("pulp_tool.upload.results.create_labels", return_value={"build_id": "test-build"}):
            with pytest.raises(Exception):
                _upload_and_get_results_url(
                    mock_pulp_client,
                    args,
                    "test-repo",
                    PulpResultsDocument.from_raw({"artifacts": {}}),
                    "2024-01-01",
                )


class TestExtractResultsUrl:
    """Test _extract_results_url function."""

    def test_extract_results_url_success(self, mock_pulp_client) -> None:
        """Test successful results URL extraction."""
        args = Mock()
        args.build_id = "test-build"
        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", result={"relative_path": "pulp_results.json"}
        )
        with patch("pulp_tool.upload.results.PulpHelper") as MockPulpHelper:
            mock_helper = Mock()
            mock_helper.get_distribution_urls.return_value = {
                "artifacts": "https://pulp-content.example.com/test-domain/test-build/artifacts/"
            }
            MockPulpHelper.return_value = mock_helper
            result = _extract_results_url(mock_pulp_client, args, task_response)
            assert result == "https://pulp-content.example.com/test-domain/test-build/artifacts/pulp_results.json"
            mock_helper.get_distribution_urls.assert_called_once_with("test-build")


class TestFindArtifactContentCoverage:
    """Additional _find_artifact_content branches (diff coverage)."""

    def test_find_artifact_content_no_artifacts_dict(self, mock_pulp_client) -> None:
        """Test _find_artifact_content when artifacts_dict is empty."""
        from pulp_tool.upload.results import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_response = Mock(spec=httpx.Response)
        mock_response.json.return_value = {"results": [{"artifacts": {}}]}
        mock_pulp_client.find_content = Mock(return_value=mock_response)
        with patch("pulp_tool.upload.results.logging") as mock_logging:
            result = _find_artifact_content(mock_pulp_client, task_response)
            assert result is None
            mock_logging.error.assert_called()

    def test_find_artifact_content_non_dict_artifacts(self, mock_pulp_client) -> None:
        """Test _find_artifact_content when artifacts is not a dict."""
        from pulp_tool.upload.results import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_response = Mock(spec=httpx.Response)
        mock_response.json.return_value = {"results": [{"artifacts": None}]}
        mock_pulp_client.find_content = Mock(return_value=mock_response)
        with patch("pulp_tool.upload.results.logging") as mock_logging:
            result = _find_artifact_content(mock_pulp_client, task_response)
            assert result is None
            mock_logging.error.assert_called()

    def test_find_artifact_content_no_file_value(self, mock_pulp_client, httpx_mock) -> None:
        """Test _find_artifact_content when artifact response has no file value."""
        from pulp_tool.upload.results import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_content_response = Mock(spec=httpx.Response)
        mock_content_response.json.return_value = {"results": [{"artifacts": {"test.txt": "/api/v3/artifacts/12345/"}}]}
        mock_pulp_client.find_content = Mock(return_value=mock_content_response)
        mock_artifact_response = Mock(spec=httpx.Response)
        mock_artifact_response.json.return_value = {"results": [{"sha256": "abc123"}]}
        mock_pulp_client.get_file_locations = Mock(return_value=mock_artifact_response)
        with patch("pulp_tool.upload.results.logging") as mock_logging:
            result = _find_artifact_content(mock_pulp_client, task_response)
            assert result is None
            mock_logging.error.assert_called()

    def test_find_artifact_content_no_sha256_value(self, mock_pulp_client, httpx_mock) -> None:
        """Test _find_artifact_content when artifact response has no sha256 value."""
        from pulp_tool.upload.results import _find_artifact_content

        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/file/files/12345/"]
        )
        mock_content_response = Mock(spec=httpx.Response)
        mock_content_response.json.return_value = {"results": [{"artifacts": {"test.txt": "/api/v3/artifacts/12345/"}}]}
        mock_pulp_client.find_content = Mock(return_value=mock_content_response)
        mock_artifact_response = Mock(spec=httpx.Response)
        mock_artifact_response.json.return_value = {"results": [{"file": "test.txt@sha256:abc123"}]}
        mock_pulp_client.get_file_locations = Mock(return_value=mock_artifact_response)
        with patch("pulp_tool.upload.results.logging") as mock_logging:
            result = _find_artifact_content(mock_pulp_client, task_response)
            assert result is None
            mock_logging.error.assert_called()

    def test_find_artifact_content_success(self, mock_pulp_client, httpx_mock) -> None:
        """Test _find_artifact_content successful path."""
        from pulp_tool.upload.results import _find_artifact_content

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
        from pulp_tool.upload.results import _find_artifact_content

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
        from pulp_tool.upload.results import _parse_oci_reference

        with patch("pulp_tool.upload.results.logging") as mock_logging:
            image_url, digest = _parse_oci_reference("quay.io/org/repo@sha256:abc123")
            assert image_url == "quay.io/org/repo"
            assert digest == "sha256:abc123"
            mock_logging.debug.assert_called()

    def test_parse_oci_reference_without_digest(self) -> None:
        """Test _parse_oci_reference without digest."""
        from pulp_tool.upload.results import _parse_oci_reference

        with patch("pulp_tool.upload.results.logging") as mock_logging:
            image_url, digest = _parse_oci_reference("quay.io/org/repo")
            assert image_url == "quay.io/org/repo"
            assert digest == ""
            mock_logging.debug.assert_called()

    def test_format_sha256_digest_already_prefixed(self) -> None:
        """Test _format_sha256_digest leaves sha256: prefix unchanged."""
        from pulp_tool.upload.results import _format_sha256_digest

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


class TestCollectResults:
    """Test collect_results function."""

    def test_build_artifact_map_skips_query_when_no_valid_hrefs(self, mock_pulp_client) -> None:
        """Content rows without /artifacts/ hrefs: empty map, no get_file_locations (else branch)."""
        from pulp_tool.models.artifacts import PulpContentRow

        rows = [
            PulpContentRow(pulp_href="/c/1/", artifacts={"k": "/pulp/api/v3/content/units/foo/"}),
            PulpContentRow(pulp_href="/c/2/", artifacts={"k": ""}),
        ]
        with (
            patch.object(mock_pulp_client, "get_file_locations") as mock_get_locs,
            patch("pulp_tool.upload.results.logging") as log_mock,
        ):
            result = _build_artifact_map(mock_pulp_client, rows)
        assert result == {}
        mock_get_locs.assert_not_called()
        log_mock.warning.assert_called()

    def test_collect_results_calls_add_distributions(self, mock_pulp_client, httpx_mock) -> None:
        """Test that collect_results calls _add_distributions_to_results."""
        httpx_mock.get(re.compile(".*/content/rpm/packages/\\?pulp_href__in=")).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        httpx_mock.post(re.compile(".*/content/file/files/")).mock(
            return_value=httpx.Response(200, json={"task": "/api/v3/tasks/123/"})
        )
        httpx_mock.get(re.compile(".*/tasks/123/")).mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "completed"})
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path="/tmp/sbom.json",
        )
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
        with patch("pulp_tool.upload.results.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {
                "rpms": "https://pulp.example.com/rpms/",
                "logs": "https://pulp.example.com/logs/",
            }
            mock_helper_class.return_value = mock_helper
            with patch("pulp_tool.upload.results._gather_and_validate_content") as mock_gather:
                mock_gather.return_value = Mock(content_results=[], file_results=[], log_results=[], sbom_results=[])
                with patch("pulp_tool.upload.results._build_artifact_map", return_value={}):
                    with patch("pulp_tool.upload.results._populate_results_model"):
                        with patch.object(mock_pulp_client, "build_results_structure", return_value=results_model):
                            with patch(
                                "pulp_tool.upload.results._serialize_results_to_json",
                                return_value='{"test": "json"}',
                            ):
                                with patch(
                                    "pulp_tool.upload.results._upload_and_get_results_url",
                                    return_value="https://example.com/results.json",
                                ):
                                    result = collect_results(mock_pulp_client, context, "2024-01-01", results_model)
                                    mock_helper_class.assert_called_once_with(
                                        mock_pulp_client, parent_package="test-pkg"
                                    )
                                    mock_helper.get_distribution_urls_for_upload_context.assert_called_once_with(
                                        "test-build", context
                                    )
                                    assert result == "https://example.com/results.json"

    def test_collect_results_requires_repositories_for_incremental_upload(self, mock_pulp_client) -> None:
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            artifact_results="https://example/u,sha256:abc",
        )
        results_model = PulpResultsDocument.model_construct(
            build_id="test-build",
            repositories=None,
            artifacts={
                "pkg.rpm": ArtifactMetadata(pulp_labels={}, url="https://example.com/pkg.rpm", sha256="deadbeef"),
            },
        )
        with patch("pulp_tool.upload.results._gather_and_validate_content", return_value=None):
            with patch("pulp_tool.upload.results._add_distributions_to_results"):
                with pytest.raises(ValueError, match="repositories required"):
                    collect_results(mock_pulp_client, context, "2024-01-01", results_model)

    def test_collect_results_requires_repositories_when_gather_has_content(self, mock_pulp_client) -> None:
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
        )
        results_model = PulpResultsDocument.model_construct(build_id="test-build", repositories=None)
        content = Mock(content_results=[], file_results=[], log_results=[], sbom_results=[])
        with patch("pulp_tool.upload.results._gather_and_validate_content", return_value=content):
            with patch("pulp_tool.upload.results._build_artifact_map", return_value={}):
                with patch("pulp_tool.upload.results._populate_results_model"):
                    with patch("pulp_tool.upload.results._add_distributions_to_results"):
                        with patch(
                            "pulp_tool.upload.results._serialize_results_to_json",
                            return_value="{}",
                        ):
                            with pytest.raises(ValueError, match="repositories required"):
                                collect_results(mock_pulp_client, context, "2024-01-01", results_model)

    def test_collect_results_incremental_only_when_gather_empty(self, mock_pulp_client) -> None:
        """When gather returns no content but the model already has artifacts, still upload results JSON."""
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path=None,
        )
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
        results_model.add_artifact("pkg.rpm", "https://example.com/pkg.rpm", "deadbeef", {"build_id": "test-build"})
        with patch("pulp_tool.upload.results.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {"artifacts": "https://a/artifacts/"}
            mock_helper_class.return_value = mock_helper
            with patch("pulp_tool.upload.results._gather_and_validate_content", return_value=None):
                with patch("pulp_tool.upload.results._serialize_results_to_json", return_value="{}"):
                    with patch(
                        "pulp_tool.upload.results._upload_and_get_results_url",
                        return_value="https://example.com/out.json",
                    ) as mock_upload:
                        result = collect_results(mock_pulp_client, context, "2024-01-01", results_model)
        assert result == "https://example.com/out.json"
        mock_upload.assert_called_once()
        mock_helper.get_distribution_urls_for_upload_context.assert_called()

    def test_collect_results_saves_to_folder_when_artifact_results_is_folder(
        self, mock_pulp_client, httpx_mock, tmp_path
    ) -> None:
        """Test that collect_results saves locally when artifact_results is a folder path."""
        output_dir = tmp_path / "output"
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path=None,
            artifact_results=str(output_dir),
            sbom_results=None,
        )
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
        with patch("pulp_tool.upload.results._gather_and_validate_content") as mock_gather:
            mock_gather.return_value = Mock(content_results=[], file_results=[], log_results=[], sbom_results=[])
            with patch("pulp_tool.upload.results._build_artifact_map", return_value={}):
                with patch("pulp_tool.upload.results._populate_results_model"):
                    with patch("pulp_tool.upload.results._add_distributions_to_results"):
                        with patch(
                            "pulp_tool.upload.results._serialize_results_to_json",
                            return_value='{"artifacts": {}, "distributions": {}}',
                        ):
                            result = collect_results(mock_pulp_client, context, "2024-01-01", results_model)
        assert result is not None
        assert "pulp_results.json" in result
        assert (output_dir / "pulp_results.json").exists()
        assert (output_dir / "pulp_results.json").read_text() == '{"artifacts": {}, "distributions": {}}'

    def test_collect_results_saves_minimal_when_no_content_and_folder_mode(
        self, mock_pulp_client, httpx_mock, tmp_path
    ) -> None:
        """Test that collect_results creates minimal pulp_results.json when no content and folder mode."""
        output_dir = tmp_path / "output"
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path=None,
            artifact_results=str(output_dir),
            sbom_results=None,
        )
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
        with patch("pulp_tool.upload.results._gather_and_validate_content", return_value=None):
            with patch("pulp_tool.upload.results._add_distributions_to_results"):
                result = collect_results(mock_pulp_client, context, "2024-01-01", results_model)
        assert result is not None
        assert (output_dir / "pulp_results.json").exists()
        content = json.loads((output_dir / "pulp_results.json").read_text())
        assert content["artifacts"] == {}
        assert "distributions" in content


class TestSaveResultsToFolder:
    """Test _save_results_to_folder function."""

    def test_save_results_to_folder_success(self, tmp_path) -> None:
        """Test saving results JSON to a folder."""
        output_dir = tmp_path / "results"
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path=None,
            artifact_results=str(output_dir),
            sbom_results=None,
        )
        json_content = '{"artifacts": {}, "distributions": {}}'
        result = _save_results_to_folder(str(output_dir), json_content, context)
        assert result is not None
        assert (output_dir / "pulp_results.json").exists()
        assert (output_dir / "pulp_results.json").read_text() == json_content

    def test_save_results_to_folder_creates_parents(self, tmp_path) -> None:
        """Test that nested folder path is created."""
        output_dir = tmp_path / "a" / "b" / "c"
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path=None,
            artifact_results=str(output_dir),
            sbom_results=None,
        )
        json_content = '{"test": true}'
        result = _save_results_to_folder(str(output_dir), json_content, context)
        assert result is not None
        assert (output_dir / "pulp_results.json").exists()

    def test_save_results_to_folder_with_sbom_results(self, tmp_path) -> None:
        """Test that sbom_results is handled when saving to folder."""
        output_dir = tmp_path / "results"
        sbom_results_file = tmp_path / "sbom_results.txt"
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path=None,
            artifact_results=str(output_dir),
            sbom_results=str(sbom_results_file),
        )
        json_content = json.dumps(
            {
                "artifacts": {"sbom.json": {"url": "https://pulp.example/sbom.json", "pulp_labels": {}}},
                "distributions": {},
            }
        )
        result = _save_results_to_folder(str(output_dir), json_content, context)
        assert result is not None
        assert (output_dir / "pulp_results.json").exists()
        assert sbom_results_file.exists()
        assert sbom_results_file.read_text() == "https://pulp.example/sbom.json"

    def test_save_results_to_folder_handles_io_error(self, tmp_path) -> None:
        """Test that OSError/IOError during save returns None."""
        output_dir = tmp_path / "results"
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path=None,
            artifact_results=str(output_dir),
            sbom_results=None,
        )
        json_content = '{"artifacts": {}, "distributions": {}}'
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            result = _save_results_to_folder(str(output_dir), json_content, context)
        assert result is None


class TestUploadAndExtract:
    def test_upload_and_get_results_url_success_paths(self, mock_pulp_client: Mock) -> None:
        """Happy path: upload, extract URL, log when no Konflux artifact_results, optional sbom (lines 95-116)."""
        tr = TaskResponse(
            pulp_href="/tasks/1/",
            state="completed",
            result={"relative_path": "pulp_results.json"},
        )
        ctx = _minimal_context(artifact_results=None, sbom_results="/tmp/sbom_out")
        with (
            patch.object(uc, "create_file_content_and_wait", return_value=tr),
            patch.object(uc, "_extract_results_url", return_value="https://example.com/results.json"),
            patch.object(uc, "_handle_sbom_results") as mock_sbom,
        ):
            out = uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", _empty_results_document(), "2024-01-01")
        assert out == "https://example.com/results.json"
        mock_sbom.assert_called_once()

    def test_upload_and_get_results_url_requires_oci_for_konflux_results(self, mock_pulp_client: Mock) -> None:
        ctx = _minimal_context(artifact_results="/u,/d", oci_storage=None)
        with pytest.raises(ValueError, match="--oci-storage is required"):
            uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", _empty_results_document(), "2024-01-01")

    def test_konflux_artifact_results_paths_invalid_format(self) -> None:
        ctx = _minimal_context(artifact_results="only-one-path")
        assert uc._konflux_artifact_results_paths(ctx) is None

    def test_upload_and_get_results_url_oras_without_konflux_result_files(self, mock_pulp_client: Mock) -> None:
        tr = TaskResponse(pulp_href="/t/", state="completed", result={"relative_path": "x.json"})
        ctx = _minimal_context(artifact_results=None, oci_storage="quay.io/ns/repo:latest")
        with (
            patch.object(
                uc,
                "sync_pulp_results_with_oci_registry",
                return_value=("quay.io/ns/repo@sha256:abc", tr),
            ) as mock_sync,
            patch.object(uc, "_extract_results_url", return_value="https://u/x.json"),
            patch.object(uc, "_write_konflux_results") as mock_write,
        ):
            uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", _empty_results_document(), "2024-01-01")
        mock_sync.assert_called_once()
        mock_write.assert_not_called()

    def test_upload_and_get_results_url_uses_oras_when_oci_storage_set(self, mock_pulp_client: Mock) -> None:
        tr = TaskResponse(pulp_href="/t/", state="completed", result={"relative_path": "x.json"})
        ctx = _minimal_context(artifact_results="/u,/d", oci_storage="quay.io/ns/repo:latest")
        with (
            patch.object(
                uc,
                "sync_pulp_results_with_oci_registry",
                return_value=("quay.io/ns/repo@sha256:abc", tr),
            ) as mock_sync,
            patch.object(uc, "_extract_results_url", return_value="https://u/x.json"),
            patch.object(uc, "write_konflux_oci_results") as mock_write,
        ):
            doc = _empty_results_document()
            uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", doc, "2024-01-01")
        mock_sync.assert_called_once()
        assert mock_sync.call_args[0][2] is doc
        mock_write.assert_called_once_with("quay.io/ns/repo@sha256:abc", "/u", "/d")

    def test_konflux_results_from_oci_ref(self) -> None:
        url, digest = uc._konflux_results_from_oci_ref("quay.io/ns/repo:tag@sha256:abc123")
        assert url == "quay.io/ns/repo:tag"
        assert digest == "sha256:abc123"

    def test_konflux_results_from_oci_ref_requires_digest(self) -> None:
        with pytest.raises(ValueError, match="no digest"):
            uc._konflux_results_from_oci_ref("quay.io/ns/repo:tag")

    def test_write_konflux_oci_results_writes_split_files(self, tmp_path) -> None:
        url_path = tmp_path / "url"
        digest_path = tmp_path / "digest"
        image_url, digest = uc.write_konflux_oci_results(
            "quay.io/ns/repo:1@sha256:deadbeef", str(url_path), str(digest_path)
        )
        assert image_url == "quay.io/ns/repo:1"
        assert digest == "sha256:deadbeef"
        assert url_path.read_text(encoding="utf-8") == "quay.io/ns/repo:1"
        assert digest_path.read_text(encoding="utf-8") == "sha256:deadbeef"

    def test_upload_and_get_results_url_failure_logs_traceback(self, mock_pulp_client: Mock) -> None:
        ctx = _minimal_context()
        with (
            patch.object(uc, "create_file_content_and_wait", side_effect=RuntimeError("boom")),
            patch("pulp_tool.upload.results.logging") as log_mock,
            pytest.raises(RuntimeError, match="boom"),
        ):
            uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", _empty_results_document(), "2024-01-01")
        log_mock.error.assert_called()

    def test_extract_results_url_raises_without_artifacts_distribution(self, mock_pulp_client: Mock) -> None:
        ctx = _minimal_context()
        tr = TaskResponse(pulp_href="/t/", state="completed", result={"relative_path": "x"})
        with patch.object(uc, "PulpHelper") as PH:
            PH.return_value.get_distribution_urls.return_value = {"logs": "https://l/"}
            with pytest.raises(ValueError, match="No distribution URL found for artifacts"):
                uc._extract_results_url(mock_pulp_client, ctx, tr)

    def test_extract_results_url_raises_without_relative_path(self, mock_pulp_client: Mock) -> None:
        ctx = _minimal_context()
        tr = TaskResponse(pulp_href="/t/", state="completed", result={})
        with patch.object(uc, "PulpHelper") as PH:
            PH.return_value.get_distribution_urls.return_value = {"artifacts": "https://a/"}
            with pytest.raises(ValueError, match="relative_path"):
                uc._extract_results_url(mock_pulp_client, ctx, tr)


class TestGatherAndBuildMap:
    def test_gather_and_validate_content_empty(self) -> None:
        client = Mock()
        client.gather_content_data.return_value = ContentData(content_results=[])
        ctx = _minimal_context()
        with patch("pulp_tool.upload.results.logging") as log_mock:
            assert uc._gather_and_validate_content(client, ctx, None) is None
        log_mock.error.assert_called()

    def test_gather_and_validate_content_success(self) -> None:
        client = Mock()
        rows = [PulpContentRow(pulp_href="/c/1/", artifacts={})]
        client.gather_content_data.return_value = ContentData(content_results=rows)
        ctx = _minimal_context()
        data = uc._gather_and_validate_content(client, ctx, None)
        assert data is not None
        assert len(data.content_results) == 1

    def test_build_artifact_map_queries_when_hrefs_present(self) -> None:
        client = Mock()
        rows = [
            PulpContentRow(pulp_href="/c/", artifacts={"k": "https://pulp/api/v3/content/artifacts/1/"}),
        ]
        client.get_file_locations.return_value = httpx.Response(
            200,
            json={
                "results": [
                    {
                        "pulp_href": "https://pulp/api/v3/content/artifacts/1/",
                        "file": "f",
                        "sha256": "abc",
                    }
                ]
            },
        )
        m = uc._build_artifact_map(client, rows)
        assert len(m) == 1
        assert isinstance(next(iter(m.values())), FileInfoModel)

    def test_build_artifact_map_no_hrefs_warning(self) -> None:
        client = Mock()
        rows = [PulpContentRow(pulp_href="/c/", artifacts={"k": "/api/v3/content/units/foo/"})]
        with patch("pulp_tool.upload.results.logging") as log_mock:
            assert uc._build_artifact_map(client, rows) == {}
        log_mock.warning.assert_called()


class TestCollectResultsBranches:
    def test_collect_results_incremental_when_gather_empty(self, mock_pulp_client: Mock) -> None:
        """Lines 279-286: no content_data but model already has artifacts."""
        ctx = _minimal_context()
        refs = _minimal_refs()
        model = PulpResultsDocument(build_id="b1", repositories=refs)
        model.add_artifact("a.rpm", "https://x", "dead", {"build_id": "b1"})
        with (
            patch.object(uc, "_gather_and_validate_content", return_value=None),
            patch.object(uc, "_add_distributions_to_results"),
            patch.object(uc, "_serialize_results_to_json", return_value="{}"),
            patch.object(uc, "_upload_and_get_results_url", return_value="https://out") as up,
        ):
            out = uc.collect_results(mock_pulp_client, ctx, "2024-01-01", model)
        assert out == "https://out"
        up.assert_called_once()

    def test_collect_results_returns_none_when_no_content_no_model(self, mock_pulp_client: Mock) -> None:
        ctx = _minimal_context()
        model = PulpResultsDocument(build_id="b1", repositories=_minimal_refs())
        with patch.object(uc, "_gather_and_validate_content", return_value=None):
            assert uc.collect_results(mock_pulp_client, ctx, "2024-01-01", model) is None


class TestFindArtifactContentBranches:
    def test_no_content_in_created_resources(self, mock_pulp_client: Mock) -> None:
        tr = TaskResponse(pulp_href="/t/", state="completed", created_resources=["/api/v3/foo/"])
        with patch("pulp_tool.upload.results.logging") as log_mock:
            assert uc._find_artifact_content(mock_pulp_client, tr) is None
        log_mock.error.assert_called()

    def test_find_content_returns_empty(self) -> None:
        client = Mock()
        tr = TaskResponse(pulp_href="/t/", state="completed", created_resources=["/api/v3/content/x/"])
        client.find_content.return_value = httpx.Response(200, json={"results": []})
        with patch("pulp_tool.upload.results.content_find_results_from_response", return_value=None):
            with patch("pulp_tool.upload.results.logging") as log_mock:
                assert uc._find_artifact_content(client, tr) is None
        log_mock.error.assert_called()


class TestHandleSbomResults:
    def test_no_sbom_in_json_info_only(self) -> None:
        ctx = _minimal_context(sbom_results="/tmp/s")
        with patch("pulp_tool.upload.results.logging") as log_mock:
            uc._handle_sbom_results(Mock(), ctx, json.dumps({"artifacts": {"x.rpm": {"url": "u"}}}))
        log_mock.info.assert_called()

    def test_skip_when_sbom_results_path_missing(self) -> None:
        ctx = _minimal_context(sbom_results=None)
        body = json.dumps({"artifacts": {"sbom.json": {"pulp_labels": {}, "url": "https://sbom"}}})
        with patch("pulp_tool.upload.results.logging") as log_mock:
            uc._handle_sbom_results(Mock(), ctx, body)
        log_mock.debug.assert_called()

    def test_writes_sbom_url_file(self, tmp_path) -> None:
        out = tmp_path / "sbom.url"
        ctx = _minimal_context(sbom_results=str(out))
        body = json.dumps({"artifacts": {"sbom.json": {"pulp_labels": {}, "url": "https://sbom/x"}}})
        uc._handle_sbom_results(Mock(), ctx, body)
        assert out.read_text() == "https://sbom/x"

    def test_writes_sbom_url_for_scoped_artifact_key(self, tmp_path) -> None:
        out = tmp_path / "sbom.url"
        ctx = _minimal_context(sbom_results=str(out))
        body = json.dumps(
            {
                "artifacts": {
                    "test-build-456/run1/sbom.json": {
                        "pulp_labels": {"build_id": "test-build-456/run1", "arch": ""},
                        "url": "https://pulp.example/sbom/sbom.json",
                    }
                }
            }
        )
        uc._handle_sbom_results(Mock(), ctx, body)
        assert out.read_text() == "https://pulp.example/sbom/sbom.json"

    def test_fallback_from_sbom_distribution_when_artifact_url_missing(self, tmp_path) -> None:
        out = tmp_path / "sbom.url"
        ctx = UploadRpmContext(
            build_id="b1",
            date_str="2024-01-01",
            namespace="ns",
            parent_package="pkg",
            sbom_results=str(out),
            sbom_path="/tmp/custom-sbom.json",
        )
        body = json.dumps(
            {
                "artifacts": {
                    "test-build-456/sbom.json": {
                        "pulp_labels": {"build_id": "test-build-456", "arch": ""},
                        "url": None,
                    }
                },
                "distributions": {"sbom": "https://pulp.example/content/ns/test-build-456/sbom/"},
            }
        )
        uc._handle_sbom_results(Mock(), ctx, body)
        assert out.read_text() == "https://pulp.example/content/ns/test-build-456/sbom/custom-sbom.json"

    def test_invalid_json_logs_error(self) -> None:
        ctx = _minimal_context(sbom_results="/tmp/x")
        with patch("pulp_tool.upload.results.logging") as log_mock:
            uc._handle_sbom_results(Mock(), ctx, "{ not json")
        log_mock.error.assert_called()

    def test_ioerror_on_write(self, tmp_path) -> None:
        out = tmp_path / "sbom.url"
        ctx = _minimal_context(sbom_results=str(out))
        body = json.dumps({"artifacts": {"sbom.json": {"pulp_labels": {}, "url": "https://u"}}})
        with patch.object(Path, "write_text", side_effect=OSError("denied")):
            with patch("pulp_tool.upload.results.logging") as log_mock:
                uc._handle_sbom_results(Mock(), ctx, body)
        log_mock.error.assert_called()

    def test_resolve_sbom_skips_arch_labeled_sbom_artifact(self) -> None:
        """SBOM-named artifacts with arch labels are ignored (first lookup loop)."""
        ctx = _minimal_context()
        results = {
            "artifacts": {
                "build/sbom.json": {"pulp_labels": {"arch": "x86_64"}, "url": "https://skip-me"},
                "cyclonedx.json": {"pulp_labels": {}, "url": "https://legacy-sbom"},
            }
        }
        artifact_key, url = uc._resolve_sbom_results_url(results, ctx)
        assert artifact_key == "cyclonedx.json"
        assert url == "https://legacy-sbom"

    def test_resolve_sbom_skips_arch_labeled_json_in_legacy_loop(self) -> None:
        """Generic .json artifacts with arch labels are ignored (legacy lookup loop)."""
        ctx = _minimal_context()
        results = {
            "artifacts": {
                "pkg.json": {"pulp_labels": {"arch": "aarch64"}, "url": "https://skip-me"},
                "results.json": {"pulp_labels": {}, "url": "https://picked"},
            }
        }
        artifact_key, url = uc._resolve_sbom_results_url(results, ctx)
        assert artifact_key == "results.json"
        assert url == "https://picked"
