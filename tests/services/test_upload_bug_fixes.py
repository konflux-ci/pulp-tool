"""Regression tests for bug fixes in upload security and reliability."""

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.services.upload_service import process_uploads_from_results_json
from pulp_tool.utils.path_utils import resolve_path_under_base, sanitize_arch_for_path
from pulp_tool.utils.uploads import upload_rpms


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
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=[]) as mock_upload_rpms,
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
                "pulp_tool.utils.uploads.upload_rpms_parallel",
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
