"""Targeted tests for ``upload_collect`` branches required for 100% PR diff coverage."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import httpx
import pytest

from pulp_tool.models.artifacts import ContentData, FileInfoModel, PulpContentRow
from pulp_tool.models.context import UploadContext, UploadRpmContext
from pulp_tool.models.pulp_api import TaskResponse
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.results import PulpResultsModel
from pulp_tool.services import upload_collect as uc


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
            out = uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", "{}", "2024-01-01")
        assert out == "https://example.com/results.json"
        mock_sbom.assert_called_once()

    def test_upload_and_get_results_url_calls_handle_artifact_results(self, mock_pulp_client: Mock) -> None:
        tr = TaskResponse(pulp_href="/t/", state="completed", result={"relative_path": "x.json"})
        ctx = _minimal_context(artifact_results="/u,/d")
        with (
            patch.object(uc, "create_file_content_and_wait", return_value=tr),
            patch.object(uc, "_extract_results_url", return_value="https://u/x.json"),
            patch.object(uc, "_handle_artifact_results") as mock_h,
        ):
            uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", "{}", "2024-01-01")
        mock_h.assert_called_once_with(mock_pulp_client, ctx, tr)

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
            uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", '{"artifacts":{}}', "2024-01-01")
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
            patch.object(uc, "_write_konflux_oci_results") as mock_write,
            patch.object(uc, "_handle_artifact_results") as mock_legacy,
        ):
            uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", '{"artifacts":{}}', "2024-01-01")
        mock_sync.assert_called_once()
        mock_write.assert_called_once_with("quay.io/ns/repo@sha256:abc", "/u", "/d")
        mock_legacy.assert_not_called()

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
        image_url, digest = uc._write_konflux_oci_results(
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
            patch("pulp_tool.services.upload_collect.logging") as log_mock,
            pytest.raises(RuntimeError, match="boom"),
        ):
            uc._upload_and_get_results_url(mock_pulp_client, ctx, "prn", "{}", "2024-01-01")
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
        with patch("pulp_tool.services.upload_collect.logging") as log_mock:
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
        with patch("pulp_tool.services.upload_collect.logging") as log_mock:
            assert uc._build_artifact_map(client, rows) == {}
        log_mock.warning.assert_called()


class TestCollectResultsBranches:
    def test_collect_results_incremental_when_gather_empty(self, mock_pulp_client: Mock) -> None:
        """Lines 279-286: no content_data but model already has artifacts."""
        ctx = _minimal_context()
        refs = _minimal_refs()
        model = PulpResultsModel(build_id="b1", repositories=refs)
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
        model = PulpResultsModel(build_id="b1", repositories=_minimal_refs())
        with patch.object(uc, "_gather_and_validate_content", return_value=None):
            assert uc.collect_results(mock_pulp_client, ctx, "2024-01-01", model) is None


class TestFindArtifactContent:
    def test_no_content_in_created_resources(self, mock_pulp_client: Mock) -> None:
        tr = TaskResponse(pulp_href="/t/", state="completed", created_resources=["/api/v3/foo/"])
        with patch("pulp_tool.services.upload_collect.logging") as log_mock:
            assert uc._find_artifact_content(mock_pulp_client, tr) is None
        log_mock.error.assert_called()

    def test_find_content_returns_empty(self) -> None:
        client = Mock()
        tr = TaskResponse(pulp_href="/t/", state="completed", created_resources=["/api/v3/content/x/"])
        client.find_content.return_value = httpx.Response(200, json={"results": []})
        with patch("pulp_tool.services.upload_collect.content_find_results_from_response", return_value=None):
            with patch("pulp_tool.services.upload_collect.logging") as log_mock:
                assert uc._find_artifact_content(client, tr) is None
        log_mock.error.assert_called()


class TestHandleArtifactResults:
    def test_skips_when_no_artifact_results_config(self, mock_pulp_client: Mock) -> None:
        ctx = _minimal_context(artifact_results=None)
        tr = TaskResponse(pulp_href="/t/", state="completed", result={"relative_path": "x.json"})
        with patch.object(uc, "PulpHelper") as PH:
            PH.return_value.get_distribution_urls.return_value = {"artifacts": "https://a/"}
            with patch("pulp_tool.services.upload_collect.logging") as log_mock:
                uc._handle_artifact_results(mock_pulp_client, ctx, tr)
        log_mock.debug.assert_called()

    def test_invalid_artifact_results_pair(self, mock_pulp_client: Mock) -> None:
        ctx = _minimal_context(artifact_results="only-one-path")
        tr = TaskResponse(pulp_href="/t/", state="completed", result={"relative_path": "x.json"})
        with patch.object(uc, "PulpHelper") as PH:
            PH.return_value.get_distribution_urls.return_value = {"artifacts": "https://a/"}
            with patch("pulp_tool.services.upload_collect.logging") as log_mock:
                uc._handle_artifact_results(mock_pulp_client, ctx, tr)
        log_mock.error.assert_called()

    def test_find_artifact_content_missing(self, mock_pulp_client: Mock) -> None:
        ctx = _minimal_context(artifact_results="/u,/d")
        tr = TaskResponse(pulp_href="/t/", state="completed", result={"relative_path": "x.json"})
        with (
            patch.object(uc, "PulpHelper") as PH,
            patch.object(uc, "_find_artifact_content", return_value=None),
        ):
            PH.return_value.get_distribution_urls.return_value = {"artifacts": "https://a/"}
            with patch("pulp_tool.services.upload_collect.logging") as log_mock:
                uc._handle_artifact_results(mock_pulp_client, ctx, tr)
        log_mock.error.assert_called()


class TestHandleSbomResults:
    def test_no_sbom_in_json_info_only(self) -> None:
        ctx = _minimal_context(sbom_results="/tmp/s")
        with patch("pulp_tool.services.upload_collect.logging") as log_mock:
            uc._handle_sbom_results(Mock(), ctx, json.dumps({"artifacts": {"x.rpm": {"url": "u"}}}))
        log_mock.info.assert_called()

    def test_skip_when_sbom_results_path_missing(self) -> None:
        ctx = _minimal_context(sbom_results=None)
        body = json.dumps({"artifacts": {"sbom.json": {"labels": {}, "url": "https://sbom"}}})
        with patch("pulp_tool.services.upload_collect.logging") as log_mock:
            uc._handle_sbom_results(Mock(), ctx, body)
        log_mock.debug.assert_called()

    def test_writes_sbom_url_file(self, tmp_path) -> None:
        out = tmp_path / "sbom.url"
        ctx = _minimal_context(sbom_results=str(out))
        body = json.dumps({"artifacts": {"sbom.json": {"labels": {}, "url": "https://sbom/x"}}})
        uc._handle_sbom_results(Mock(), ctx, body)
        assert out.read_text() == "https://sbom/x"

    def test_writes_sbom_url_for_scoped_artifact_key(self, tmp_path) -> None:
        out = tmp_path / "sbom.url"
        ctx = _minimal_context(sbom_results=str(out))
        body = json.dumps(
            {
                "artifacts": {
                    "test-build-456/run1/sbom.json": {
                        "labels": {"build_id": "test-build-456/run1", "arch": ""},
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
                        "labels": {"build_id": "test-build-456", "arch": ""},
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
        with patch("pulp_tool.services.upload_collect.logging") as log_mock:
            uc._handle_sbom_results(Mock(), ctx, "{ not json")
        log_mock.error.assert_called()

    def test_ioerror_on_write(self, tmp_path) -> None:
        out = tmp_path / "sbom.url"
        ctx = _minimal_context(sbom_results=str(out))
        body = json.dumps({"artifacts": {"sbom.json": {"labels": {}, "url": "https://u"}}})
        with patch.object(Path, "write_text", side_effect=OSError("denied")):
            with patch("pulp_tool.services.upload_collect.logging") as log_mock:
                uc._handle_sbom_results(Mock(), ctx, body)
        log_mock.error.assert_called()

    def test_resolve_sbom_skips_arch_labeled_sbom_artifact(self) -> None:
        """SBOM-named artifacts with arch labels are ignored (first lookup loop)."""
        ctx = _minimal_context()
        results = {
            "artifacts": {
                "build/sbom.json": {"labels": {"arch": "x86_64"}, "url": "https://skip-me"},
                "cyclonedx.json": {"labels": {}, "url": "https://legacy-sbom"},
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
                "pkg.json": {"labels": {"arch": "aarch64"}, "url": "https://skip-me"},
                "results.json": {"labels": {}, "url": "https://picked"},
            }
        }
        artifact_key, url = uc._resolve_sbom_results_url(results, ctx)
        assert artifact_key == "results.json"
        assert url == "https://picked"
