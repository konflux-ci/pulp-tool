"""Tests for pulp_upload.py module."""

import json
import re
from unittest.mock import Mock, patch

import httpx
import pytest

from pulp_tool.models import RepositoryRefs
from pulp_tool.models.artifacts import ArtifactMetadata
from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.services.upload_service import _build_artifact_map, _save_results_to_folder, collect_results


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
            patch("pulp_tool.services.upload_collect.logging") as log_mock,
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
        with patch("pulp_tool.services.upload_collect.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {
                "rpms": "https://pulp.example.com/rpms/",
                "logs": "https://pulp.example.com/logs/",
            }
            mock_helper_class.return_value = mock_helper
            with patch("pulp_tool.services.upload_collect._gather_and_validate_content") as mock_gather:
                mock_gather.return_value = Mock(content_results=[], file_results=[], log_results=[], sbom_results=[])
                with patch("pulp_tool.services.upload_collect._build_artifact_map", return_value={}):
                    with patch("pulp_tool.services.upload_collect._populate_results_model"):
                        with patch.object(mock_pulp_client, "build_results_structure", return_value=results_model):
                            with patch(
                                "pulp_tool.services.upload_collect._serialize_results_to_json",
                                return_value='{"test": "json"}',
                            ):
                                with patch(
                                    "pulp_tool.services.upload_collect._upload_and_get_results_url",
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
        with patch("pulp_tool.services.upload_collect._gather_and_validate_content", return_value=None):
            with patch("pulp_tool.services.upload_collect._add_distributions_to_results"):
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
        with patch("pulp_tool.services.upload_collect._gather_and_validate_content", return_value=content):
            with patch("pulp_tool.services.upload_collect._build_artifact_map", return_value={}):
                with patch("pulp_tool.services.upload_collect._populate_results_model"):
                    with patch("pulp_tool.services.upload_collect._add_distributions_to_results"):
                        with patch(
                            "pulp_tool.services.upload_collect._serialize_results_to_json",
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
        with patch("pulp_tool.services.upload_collect.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {"artifacts": "https://a/artifacts/"}
            mock_helper_class.return_value = mock_helper
            with patch("pulp_tool.services.upload_collect._gather_and_validate_content", return_value=None):
                with patch("pulp_tool.services.upload_collect._serialize_results_to_json", return_value="{}"):
                    with patch(
                        "pulp_tool.services.upload_collect._upload_and_get_results_url",
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
        with patch("pulp_tool.services.upload_collect._gather_and_validate_content") as mock_gather:
            mock_gather.return_value = Mock(content_results=[], file_results=[], log_results=[], sbom_results=[])
            with patch("pulp_tool.services.upload_collect._build_artifact_map", return_value={}):
                with patch("pulp_tool.services.upload_collect._populate_results_model"):
                    with patch("pulp_tool.services.upload_collect._add_distributions_to_results"):
                        with patch(
                            "pulp_tool.services.upload_collect._serialize_results_to_json",
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
        with patch("pulp_tool.services.upload_collect._gather_and_validate_content", return_value=None):
            with patch("pulp_tool.services.upload_collect._add_distributions_to_results"):
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
