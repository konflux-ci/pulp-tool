"""Tests for batch upload from pulp_results.json (:mod:`pulp_tool.upload.batch_json`)."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.upload.artifacts import upload_rpms
from pulp_tool.upload.batch_json import (
    _classify_artifact_from_key,
    process_uploads_from_results_json,
    scan_results_json_for_log_and_sbom_keys,
)
from pulp_tool.upload.results import _handle_sbom_results
from pulp_tool.utils.path_utils import resolve_path_under_base, sanitize_arch_for_path


class TestHandleSbomResults:
    """Test _handle_sbom_results function."""

    def test_handle_sbom_results_success(self, tmp_path) -> None:
        """Test successful SBOM results writing."""
        results_json = {
            "artifacts": {
                "test-sbom.spdx.json": {
                    "pulp_labels": {"build_id": "test-build", "namespace": "test-ns"},
                    "url": (
                        "https://pulp.example.com/pulp/content/test-build/sbom/"
                        "test-sbom.spdx.json@sha256:abc123def456789"
                    ),
                    "sha256": "abc123def456789",
                },
                "test-package.rpm": {
                    "pulp_labels": {"build_id": "test-build", "arch": "x86_64"},
                    "url": "https://pulp.example.com/pulp/content/test-build/rpms/test-package.rpm",
                    "sha256": "rpm123456",
                },
            }
        }
        json_content = json.dumps(results_json)
        sbom_file = tmp_path / "sbom_result.txt"
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path="/tmp/sbom.json",
            sbom_results=str(sbom_file),
        )
        mock_client = Mock()
        _handle_sbom_results(mock_client, args, json_content)
        assert sbom_file.exists()
        content = sbom_file.read_text()
        expected = "https://pulp.example.com/pulp/content/test-build/sbom/test-sbom.spdx.json@sha256:abc123def456789"
        assert content == expected

    def test_handle_sbom_results_no_sbom_found(self, tmp_path, caplog) -> None:
        """Test handling when no SBOM is found."""
        results_json = {
            "artifacts": {
                "test-package.rpm": {
                    "pulp_labels": {"build_id": "test-build", "arch": "x86_64"},
                    "url": "https://pulp.example.com/pulp/content/test-build/rpms/test-package.rpm",
                    "sha256": "rpm123456",
                }
            }
        }
        json_content = json.dumps(results_json)
        sbom_file = tmp_path / "sbom_result.txt"
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path="/tmp/sbom.json",
            sbom_results=str(sbom_file),
        )
        mock_client = Mock()
        with caplog.at_level(logging.INFO):
            _handle_sbom_results(mock_client, args, json_content)
        assert not sbom_file.exists()
        assert "No SBOM file found" in caplog.text

    def test_handle_sbom_results_json_file_without_arch(self, tmp_path) -> None:
        """Test SBOM detection with .json extension (no arch label)."""
        results_json = {
            "artifacts": {
                "cyclonedx.json": {
                    "pulp_labels": {"build_id": "test-build", "namespace": "test-ns"},
                    "url": "https://pulp.example.com/pulp/content/test-build/sbom/cyclonedx.json@sha256:def789abc123",
                    "sha256": "def789abc123",
                }
            }
        }
        json_content = json.dumps(results_json)
        sbom_file = tmp_path / "sbom_result.txt"
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/tmp/rpms",
            sbom_path="/tmp/sbom.json",
            sbom_results=str(sbom_file),
        )
        mock_client = Mock()
        _handle_sbom_results(mock_client, args, json_content)
        assert sbom_file.exists()
        content = sbom_file.read_text()
        expected = "https://pulp.example.com/pulp/content/test-build/sbom/cyclonedx.json@sha256:def789abc123"
        assert content == expected


class TestClassifyArtifactFromKey:
    """Test _classify_artifact_from_key function."""

    def test_classify_rpm(self) -> None:
        """Test RPM classification."""
        assert _classify_artifact_from_key("x86_64/pkg.rpm") == "rpms"
        assert _classify_artifact_from_key("pkg.RPM") == "rpms"

    def test_classify_log(self) -> None:
        """Test log classification."""
        assert _classify_artifact_from_key("x86_64/state.log") == "logs"
        assert _classify_artifact_from_key("build.LOG") == "logs"

    def test_classify_sbom(self) -> None:
        """Test SBOM classification."""
        assert _classify_artifact_from_key("sbom.json") == "sbom"
        assert _classify_artifact_from_key("sbom.spdx") == "sbom"
        assert _classify_artifact_from_key("sbom.spdx.json") == "sbom"
        assert _classify_artifact_from_key("path/to/sbom-file.json") == "sbom"
        assert _classify_artifact_from_key("cyclonedx.json") == "artifacts"
        assert _classify_artifact_from_key("manifest.spdx") == "sbom"

    def test_classify_artifacts(self) -> None:
        """Test generic artifact classification."""
        assert _classify_artifact_from_key("other.tar.gz") == "artifacts"
        assert _classify_artifact_from_key("data.txt") == "artifacts"


class TestScanResultsJsonForLogAndSbomKeys:
    """Tests for scan_results_json_for_log_and_sbom_keys."""

    def test_detects_log_and_sbom_keys(self, tmp_path) -> None:
        """Artifact keys classified as logs and sbom set both flags."""
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"artifacts": {"aarch64/build.log": {}, "report.spdx.json": {}}}))
        assert scan_results_json_for_log_and_sbom_keys(str(p)) == (True, True)

    def test_logs_only(self, tmp_path) -> None:
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"artifacts": {"foo.log": {}}}))
        assert scan_results_json_for_log_and_sbom_keys(str(p)) == (True, False)

    def test_sbom_only(self, tmp_path) -> None:
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"artifacts": {"build-sbom.json": {}}}))
        assert scan_results_json_for_log_and_sbom_keys(str(p)) == (False, True)

    def test_invalid_json_returns_false_false(self, tmp_path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not valid json")
        assert scan_results_json_for_log_and_sbom_keys(str(p)) == (False, False)

    def test_non_dict_artifacts_returns_false_false(self, tmp_path) -> None:
        """``artifacts`` must be a dict; a truthy non-dict (e.g. list) hits the guard branch."""
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"artifacts": ["not-a-dict-entry"]}))
        assert scan_results_json_for_log_and_sbom_keys(str(p)) == (False, False)


class TestPathTraversalProtection:
    """Tests for path containment when uploading from results JSON."""

    def test_resolve_path_under_base_rejects_traversal(self, tmp_path) -> None:
        """Keys with .. must not escape the base directory."""
        base = tmp_path / "workdir"
        base.mkdir()
        safe = base / "pkg.rpm"
        safe.write_bytes(b"rpm")

        resolved = resolve_path_under_base(base, "pkg.rpm")
        assert resolved == safe.resolve()

        with pytest.raises(ValueError, match="escapes base directory"):
            resolve_path_under_base(base, "../outside.rpm")

    def test_process_uploads_skips_traversal_keys(self, mock_pulp_client, tmp_path) -> None:
        """process_uploads_from_results_json skips keys that escape base_path."""
        base = tmp_path / "files"
        base.mkdir()
        outside = tmp_path / "secret.rpm"
        outside.write_bytes(b"secret")

        results_json = tmp_path / "pulp_results.json"
        results_json.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "../secret.rpm": {"pulp_labels": {"arch": "x86_64"}},
                        "x86_64/good.rpm": {"pulp_labels": {"arch": "x86_64"}},
                    }
                }
            )
        )
        good_rpm = base / "x86_64"
        good_rpm.mkdir()
        (good_rpm / "good.rpm").write_bytes(b"good")

        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path=str(base),
            results_json=str(results_json),
            files_base_path=str(base),
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

        with (
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=[]) as mock_upload_rpms,
        ):
            process_uploads_from_results_json(mock_pulp_client, context, repositories)
            mock_upload_rpms.assert_called_once()
            uploaded_paths = mock_upload_rpms.call_args[0][0]
            assert len(uploaded_paths) == 1
            assert uploaded_paths[0].endswith("good.rpm")


class TestSanitizeArchForPath:
    """Tests for architecture validation on pull save paths."""

    def test_rejects_path_traversal_arch(self) -> None:
        with pytest.raises(ValueError, match="Unsupported or invalid architecture"):
            sanitize_arch_for_path("../../tmp")

    def test_accepts_supported_arch(self) -> None:
        assert sanitize_arch_for_path("x86_64") == "x86_64"


class TestPartialRpmUploadFailure:
    """Tests for partial RPM upload handling."""

    def test_upload_rpms_raises_on_partial_failure(self, mock_pulp_client) -> None:
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)

        with (
            patch(
                "pulp_tool.upload.artifacts.upload_rpms_parallel",
                return_value=([("/ok.rpm", "/artifact/1")], ["/bad.rpm: upload failed"]),
            ),
            pytest.raises(ValueError, match="Failed to upload 1 of 2 RPM"),
        ):
            upload_rpms(
                ["/ok.rpm", "/bad.rpm"],
                context,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="/test/rpm-href",
                date="2024-01-01 00:00:00",
                results_model=results_model,
            )

        assert results_model.uploaded_counts.rpms == 1
        assert len(results_model.upload_errors) == 1


class TestPulpResultsDocumentThreadSafety:
    """Tests for thread-safe mutations on PulpResultsDocument."""

    def test_concurrent_add_artifact_preserves_all_entries(self) -> None:
        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        model = PulpResultsDocument(build_id="b1", repositories=repositories)

        def add_one(i: int) -> None:
            model.add_artifact(f"pkg{i}.rpm", f"https://example.com/{i}", f"sha{i}", {"arch": "x86_64"})

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(add_one, range(50)))

        assert model.artifact_count == 50

    def test_concurrent_increment_counts(self) -> None:
        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        model = PulpResultsDocument(build_id="b1", repositories=repositories)

        def inc(_i: int) -> None:
            model.increment_counts(rpms=1)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(inc, range(100)))

        assert model.uploaded_counts.rpms == 100


class TestProcessUploadsFromResultsJson:
    """Test process_uploads_from_results_json function."""

    def test_raises_when_logs_present_but_logs_repo_skipped(self, tmp_path, mock_pulp_client) -> None:
        """Guard: log uploads require logs_prn."""
        arch_dir = tmp_path / "x86_64"
        arch_dir.mkdir()
        log_path = arch_dir / "build.log"
        log_path.write_text("log line")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"x86_64/build.log": {"pulp_labels": {"arch": "x86_64"}}}})
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            skip_logs_repo=True,
        )
        repositories = RepositoryRefs(
            rpms_href="/rpm",
            rpms_prn="rprn",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with pytest.raises(ValueError, match="logs repository was not created"):
            process_uploads_from_results_json(mock_pulp_client, context, repositories)

    def test_raises_when_sbom_present_but_sbom_repo_skipped(self, tmp_path, mock_pulp_client) -> None:
        sbom_path = tmp_path / "sbom.spdx.json"
        sbom_path.write_text("{}")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(json.dumps({"artifacts": {"sbom.spdx.json": {}}}))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            skip_sbom_repo=True,
        )
        repositories = RepositoryRefs(
            rpms_href="/rpm",
            rpms_prn="rprn",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with pytest.raises(ValueError, match="SBOM repository was not created"):
            process_uploads_from_results_json(mock_pulp_client, context, repositories)

    def test_upload_from_results_json_basic(self, tmp_path, mock_pulp_client) -> None:
        """Test upload from JSON without signed-by."""
        rpm_file = tmp_path / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm content")
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with (
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=["/rpm/resource/1"]),
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_with_signed_by(self, tmp_path, mock_pulp_client) -> None:
        """Test upload with signed-by uses signed repos and labels."""
        rpm_file = tmp_path / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm content")
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            signed_by="key-123",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
            rpms_signed_href="/test/rpm-signed-href",
            rpms_signed_prn="rpms-signed-prn",
            logs_signed_prn="logs-signed-prn",
            sbom_signed_prn="sbom-signed-prn",
            artifacts_signed_prn="artifacts-signed-prn",
        )
        with (
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=["/rpm/resource/1"]) as mock_upload_rpms,
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_rpms.assert_called_once()
        call_kw = mock_upload_rpms.call_args[1]
        assert call_kw["rpm_repository_href"] == "/test/rpm-signed-href"
        call_context = mock_upload_rpms.call_args[0][1]
        assert call_context.signed_by == "key-123"

    def test_upload_from_results_json_target_arch_repo_uses_ensure_per_arch(self, tmp_path, mock_pulp_client) -> None:
        """target_arch_repo sets bulk rpm_href empty and uses ensure_rpm_repository_for_arch per arch."""
        rpm_file = tmp_path / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"x")
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            target_arch_repo=True,
        )
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        mock_ph_instance = Mock()
        mock_ph_instance.ensure_rpm_repository_for_arch.return_value = "/per-arch/rpm"
        with (
            patch("pulp_tool.upload.batch_json.PulpHelper", return_value=mock_ph_instance),
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=["/r/1"]) as mock_upload_rpms,
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/r.json"),
        ):
            result = process_uploads_from_results_json(
                mock_pulp_client, context, repositories, pulp_helper=mock_ph_instance
            )
        assert result == "https://example.com/r.json"
        mock_ph_instance.ensure_rpm_repository_for_arch.assert_called_once()
        assert mock_upload_rpms.call_args.kwargs["rpm_repository_href"] == "/per-arch/rpm"

    def test_upload_from_results_json_files_base_path(self, tmp_path, mock_pulp_client) -> None:
        """Test override base path for resolving artifact keys."""
        base_dir = tmp_path / "files"
        base_dir.mkdir()
        rpm_file = base_dir / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm content")
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            files_base_path=str(base_dir),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with (
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=["/rpm/resource/1"]),
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_missing_file(self, tmp_path, mock_pulp_client, caplog) -> None:
        """Test handling of missing file - skip with warning."""
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with (
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=[]),
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
            caplog.at_level(logging.WARNING),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        assert "Skipping missing file" in caplog.text

    def test_upload_from_results_json_empty_artifacts(self, tmp_path, mock_pulp_client) -> None:
        """Test empty artifacts creates minimal results."""
        results_json_path = tmp_path / "pulp_results.json"
        results_data: dict = {"artifacts": {}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_returns_none_when_no_results_json(self, mock_pulp_client) -> None:
        """Test returns None when results_json is not set."""
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=None,
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result is None

    def test_upload_from_results_json_json_read_error(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json raises when JSON cannot be read."""
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text('{"artifacts": {"x": {}}}')
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            with pytest.raises(OSError, match="Permission denied"):
                process_uploads_from_results_json(mock_pulp_client, context, repositories)

    def test_upload_from_results_json_signed_by_no_signed_repos(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json raises when signed_by set but no signed repos."""
        rpm_file = tmp_path / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(json.dumps({"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            signed_by="key-123",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
            rpms_signed_href="",
            rpms_signed_prn="",
        )
        with pytest.raises(ValueError, match="signed_by requires signed repositories"):
            process_uploads_from_results_json(mock_pulp_client, context, repositories)

    def test_upload_from_results_json_invalid_artifact_entry(self, tmp_path, mock_pulp_client) -> None:
        """Non-dict artifact rows are dropped during ``from_raw`` normalization."""
        rpm_file = tmp_path / "pkg.rpm"
        rpm_file.write_bytes(b"fake rpm")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"pkg.rpm": {"pulp_labels": {"arch": "noarch"}}, "bad": "not a dict"}})
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with (
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=["/rpm/1"]),
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_log_and_sbom_and_artifact(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json with log, sbom, and generic artifact."""
        log_file = tmp_path / "x86_64" / "state.log"
        log_file.parent.mkdir()
        log_file.write_text("log content")
        sbom_file = tmp_path / "sbom.json"
        sbom_file.write_text('{"sbom": true}')
        artifact_file = tmp_path / "data.txt"
        artifact_file.write_text("data")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "x86_64/state.log": {"pulp_labels": {"arch": "x86_64"}},
                        "sbom.json": {"pulp_labels": {}},
                        "data.txt": {"pulp_labels": {}},
                    }
                }
            )
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        mock_resp = Mock()
        mock_resp.json.return_value = {"task": "/tasks/1/"}
        mock_task = Mock()
        mock_task.created_resources = ["/content/1/"]
        mock_pulp_client.create_file_content = Mock(return_value=mock_resp)
        mock_pulp_client.wait_for_finished_task = Mock(return_value=mock_task)
        mock_pulp_client.check_response = Mock()
        with (
            patch("pulp_tool.upload.batch_json.upload_log", return_value=["/log/1"]),
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_arch_inference_from_path(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json infers arch from path when not in labels."""
        rpm_file = tmp_path / "aarch64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(json.dumps({"artifacts": {"aarch64/pkg.rpm": {"pulp_labels": {}}}}))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with (
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=["/rpm/1"]) as mock_upload_rpms,
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_rpms.assert_called_once()
        assert mock_upload_rpms.call_args[0][3] == "aarch64"

    def test_upload_from_results_json_log_arch_inference_from_path(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json infers log arch from path (lines 290-291)."""
        log_file = tmp_path / "s390x" / "state.log"
        log_file.parent.mkdir()
        log_file.write_text("log")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(json.dumps({"artifacts": {"s390x/state.log": {"pulp_labels": {}}}}))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with (
            patch("pulp_tool.upload.batch_json.upload_log", return_value=["/log/1"]) as mock_upload_log,
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_log.assert_called_once()
        assert mock_upload_log.call_args[1]["arch"] == "s390x"

    def test_upload_from_results_json_arch_inference_noarch(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json infers noarch when no arch in path (lines 283, 287-293)."""
        rpm_file = tmp_path / "pkg.rpm"
        rpm_file.write_bytes(b"fake rpm")
        log_file = tmp_path / "state.log"
        log_file.write_text("log")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"pkg.rpm": {"pulp_labels": {}}, "state.log": {"pulp_labels": {}}}})
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with (
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=["/rpm/1"]) as mock_upload_rpms,
            patch("pulp_tool.upload.batch_json.upload_log", return_value=["/log/1"]),
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_rpms.assert_called_once()
        assert mock_upload_rpms.call_args[0][3] == "noarch"

    def test_upload_from_results_json_log_uses_unsigned_repo_with_signed_by(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json uses unsigned logs repo when signed_by set (logs never signed)."""
        log_file = tmp_path / "x86_64" / "state.log"
        log_file.parent.mkdir()
        log_file.write_text("log")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"x86_64/state.log": {"pulp_labels": {"arch": "x86_64"}}}})
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            signed_by="key-123",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
            rpms_signed_href="/test/rpm-signed-href",
            rpms_signed_prn="rpms-signed-prn",
        )
        with (
            patch("pulp_tool.upload.batch_json.upload_log", return_value=["/log/1"]) as mock_upload_log,
            patch("pulp_tool.upload.batch_json.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_log.assert_called_once()
        call_kw = mock_upload_log.call_args[1]
        assert "signed_by" not in call_kw["labels"]
        assert mock_upload_log.call_args[0][1] == "logs-prn"

    def test_defer_collect_empty_artifacts_returns_model(self, tmp_path, mock_pulp_client) -> None:
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text('{"artifacts": {}}', encoding="utf-8")
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )

        out = process_uploads_from_results_json(mock_pulp_client, context, repositories, defer_collect=True)
        assert isinstance(out, PulpResultsDocument)

    def test_defer_collect_after_uploads(self, tmp_path, mock_pulp_client) -> None:
        rpm = tmp_path / "pkg.rpm"
        rpm.write_bytes(b"rpm")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}),
            encoding="utf-8",
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            results_json=str(results_json_path),
            files_base_path=str(tmp_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="rpms-prn",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )

        with (
            patch("pulp_tool.upload.batch_json.upload_rpms", return_value=[]),
            patch("pulp_tool.utils.pulp_tasks.create_file_content_and_wait", return_value=Mock()),
        ):
            out = process_uploads_from_results_json(
                mock_pulp_client,
                context,
                repositories,
                defer_collect=True,
            )
        assert isinstance(out, PulpResultsDocument)


class TestUploadPlanFromDocument:
    def test_plan_groups_rpm_log_and_sbom(self, tmp_path) -> None:
        from pulp_tool.upload.batch_json import _plan_uploads_from_document

        rpm = tmp_path / "x86_64" / "pkg.rpm"
        rpm.parent.mkdir()
        rpm.write_bytes(b"rpm")
        log = tmp_path / "build.log"
        log.write_text("log", encoding="utf-8")
        sbom = tmp_path / "sbom.json"
        sbom.write_text("{}", encoding="utf-8")
        doc = PulpResultsDocument.from_raw(
            {
                "artifacts": {
                    "x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}},
                    "build.log": {"pulp_labels": {}},
                    "sbom.json": {"pulp_labels": {}},
                }
            }
        )
        context = UploadRpmContext(
            build_id="b1",
            date_str="2024-01-01",
            namespace="ns",
            results_json=str(tmp_path / "pulp_results.json"),
        )
        plan = _plan_uploads_from_document(doc, base_path=tmp_path, context=context)
        assert plan.rpms_by_arch["x86_64"] == [str(rpm)]
        assert plan.logs_to_upload == [(str(log), "noarch")]
        assert plan.sboms_to_upload == [str(sbom)]

    def test_infer_arch_from_path_when_label_missing(self) -> None:
        from pulp_tool.upload.batch_json import _infer_arch_from_key

        assert _infer_arch_from_key("aarch64/foo.rpm", "") == "aarch64"
        assert _infer_arch_from_key("pkg.rpm", "x86_64") == "x86_64"
