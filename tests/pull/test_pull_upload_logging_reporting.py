"""
Tests for pulp_tool.pull module.
"""

import logging
import os
import tempfile
from unittest.mock import Mock, patch

from pulp_tool.models.artifacts import ArtifactFile, PulledArtifacts
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.pull.reporting import (
    _calculate_artifact_totals,
    _format_download_summary,
    _format_file_size,
    _get_file_size_safe,
    _log_artifacts_downloaded,
    _log_build_information,
    _log_pull_summary,
    _log_pulp_upload_info,
    _log_single_artifact,
    _log_storage_summary,
    _log_upload_summary,
    generate_pull_report,
)
from pulp_tool.utils import RepositoryRefs


class TestLoggingAndReporting:
    """Test logging and reporting functionality."""

    def test_log_pull_summary(self) -> None:
        """Test pull summary logging."""
        args = Mock()
        args.artifact_location = "test.json"
        args.max_workers = 10
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_pull_summary(10, 2, args)
            mock_logging.info.assert_called_once_with("Pull: %d/%d successful (%d failed)", 10, 12, 2)
            mock_logging.debug.assert_any_call("Source: %s", "test.json")
            mock_logging.debug.assert_any_call("Max workers: %d", 10)

    def test_log_storage_summary(self, caplog) -> None:
        """Test _log_storage_summary logs correct information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm1 = os.path.join(tmpdir, "test.rpm")
            rpm2 = os.path.join(tmpdir, "test2.rpm")
            sbom1 = os.path.join(tmpdir, "test.sbom")
            log1 = os.path.join(tmpdir, "test.log")
            for f in [rpm1, rpm2, sbom1, log1]:
                with open(f, "wb") as file:
                    file.write(b"test data" * 100)
            pulled_artifacts = PulledArtifacts()
            pulled_artifacts.rpms["test.rpm"] = ArtifactFile(file=rpm1, labels={})
            pulled_artifacts.rpms["test2.rpm"] = ArtifactFile(file=rpm2, labels={})
            pulled_artifacts.sboms["test.sbom"] = ArtifactFile(file=sbom1, labels={})
            pulled_artifacts.logs["test.log"] = ArtifactFile(file=log1, labels={})
            with caplog.at_level(logging.DEBUG):
                _log_storage_summary(4, pulled_artifacts)
        assert "Storage locations:" in caplog.text

    def test_format_file_size_bytes(self) -> None:
        """Test _format_file_size with bytes."""
        result = _format_file_size(1024)
        assert result == "1.0 KB"

    def test_format_file_size_kb(self) -> None:
        """Test _format_file_size with KB."""
        result = _format_file_size(1024 * 1024)
        assert result == "1.0 MB"

    def test_format_file_size_mb(self) -> None:
        """Test _format_file_size with MB."""
        result = _format_file_size(1024 * 1024 * 1024)
        assert result == "1.0 GB"

    def test_format_file_size_gb(self) -> None:
        """Test _format_file_size with GB."""
        result = _format_file_size(1024 * 1024 * 1024 * 1024)
        assert result == "1.0 TB"

    def test_log_storage_summary_debug_level(self) -> None:
        """Test logging storage summary at DEBUG level."""
        total_files = 5
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.rpms["test1.rpm"] = ArtifactFile(file="/tmp/test1.rpm", labels={})
        pulled_artifacts.rpms["test2.rpm"] = ArtifactFile(file="/tmp/test2.rpm", labels={})
        pulled_artifacts.logs["test1.log"] = ArtifactFile(file="/tmp/test1.log", labels={})
        pulled_artifacts.sboms["test1.sbom"] = ArtifactFile(file="/tmp/test1.sbom", labels={})
        pulled_artifacts.sboms["test2.sbom"] = ArtifactFile(file="/tmp/test2.sbom", labels={})
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_storage_summary(total_files, pulled_artifacts)
            mock_logging.debug.assert_any_call("Storage locations:")
            mock_logging.debug.assert_any_call("  - %s", "/tmp")

    def test_log_pulp_upload_info_with_upload_info(self) -> None:
        """Test logging Pulp upload info when upload_info is provided."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="rpms-prn",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test-build", repositories=repositories)
        upload_info.uploaded_counts.rpms = 2
        upload_info.uploaded_counts.logs = 1
        upload_info.uploaded_counts.sboms = 1
        upload_info.add_error("Error 1")
        upload_info.add_error("Error 2")
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_pulp_upload_info(upload_info)
            mock_logging.info.assert_called_once_with(
                "Uploaded to Pulp (build: %s): %s", "test-build", "1 SBOM, 1 log, 2 RPMs"
            )
            mock_logging.debug.assert_any_call("Repositories:")
            mock_logging.debug.assert_any_call("  - RPMs: %s", "rpms-prn")
            mock_logging.warning.assert_any_call("Upload errors (%d):", 2)
            mock_logging.warning.assert_any_call("  - %s", "Error 1")
            mock_logging.warning.assert_any_call("  - %s", "Error 2")

    def test_log_pulp_upload_info_without_upload_info(self) -> None:
        """Test logging Pulp upload info when upload_info is None."""
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_pulp_upload_info(None)
            mock_logging.info.assert_not_called()
            mock_logging.warning.assert_not_called()

    def test_log_build_information(self) -> None:
        """Test logging build information."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm(
            "test1.rpm", "/tmp/test1.rpm", {"build_id": "build1", "namespace": "ns1", "arch": "x86_64"}
        )
        pulled_artifacts.add_rpm(
            "test2.rpm", "/tmp/test2.rpm", {"build_id": "build2", "namespace": "ns2", "arch": "aarch64"}
        )
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_build_information(pulled_artifacts)
            mock_logging.debug.assert_any_call("Build IDs: %s", "build1, build2")
            mock_logging.debug.assert_any_call("Namespaces: %s", "ns1, ns2")
            mock_logging.debug.assert_any_call("Architectures: %s", "aarch64, x86_64")

    def test_log_build_information_no_architectures(self) -> None:
        """Test logging build information without architectures (line 308)."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test1.rpm", "/tmp/test1.rpm", {"build_id": "build1"})
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_build_information(pulled_artifacts)
            architecture_calls = [call for call in mock_logging.debug.call_args_list if "Architectures" in str(call)]
            assert len(architecture_calls) == 0

    def test_log_upload_summary_zero_uploads(self) -> None:
        """Test _log_upload_summary with zero uploads (lines 25-26)."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test-build", repositories=repositories)
        upload_info.uploaded_counts.rpms = 0
        upload_info.uploaded_counts.sboms = 0
        upload_info.uploaded_counts.logs = 0
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_upload_summary(upload_info)
            mock_logging.warning.assert_called_once_with("Upload complete: No files uploaded to Pulp")
            assert mock_logging.warning.call_count == 1

    def test_log_upload_summary_with_counts(self) -> None:
        """Test _log_upload_summary with upload counts (lines 29-35)."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="domain:namespace/rpms",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test-build", repositories=repositories)
        upload_info.uploaded_counts.rpms = 1
        upload_info.uploaded_counts.sboms = 2
        upload_info.uploaded_counts.logs = 1
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_upload_summary(upload_info)
            mock_logging.warning.assert_called_once()
            call_args = mock_logging.warning.call_args[0]
            assert "1 RPM" in call_args[1]
            assert "2 SBOMs" in call_args[1]
            assert "1 log" in call_args[1]
            assert call_args[2] == "domain"
            assert call_args[3] == "test-build"

    def test_log_upload_summary_domain_extraction(self) -> None:
        """Test _log_upload_summary domain extraction from PRN (lines 38-39, 41-43, 45)."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="test-domain:namespace/rpms",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test-build", repositories=repositories)
        upload_info.uploaded_counts.rpms = 1
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_upload_summary(upload_info)
            call_args = mock_logging.warning.call_args[0]
            assert call_args[2] == "test-domain"

    def test_log_upload_summary_domain_unknown(self) -> None:
        """Test _log_upload_summary with unknown domain (lines 38-39)."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="invalid-prn",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test-build", repositories=repositories)
        upload_info.uploaded_counts.rpms = 1
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_upload_summary(upload_info)
            call_args = mock_logging.warning.call_args[0]
            assert call_args[2] == "unknown"

    def test_log_pull_summary_no_failures(self) -> None:
        """Test _log_pull_summary with no failures (line 59)."""
        args = Mock()
        args.artifact_location = "test.json"
        args.max_workers = 10
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_pull_summary(10, 0, args)
            mock_logging.info.assert_any_call("Pull: %d artifacts successful", 10)

    def test_format_file_size_zero(self) -> None:
        """Test _format_file_size with 0 bytes (line 98)."""
        result = _format_file_size(0)
        assert result == "0 B"

    def test_get_file_size_safe_with_oserror(self) -> None:
        """Test _get_file_size_safe with OSError (lines 119-124)."""
        with patch("os.path.getsize") as mock_getsize:
            mock_getsize.side_effect = OSError("File not found")
            size_bytes, size_str = _get_file_size_safe("/nonexistent/file")
            assert size_bytes == 0
            assert size_str == "Unknown size"

    def test_log_single_artifact_with_labels(self) -> None:
        """Test _log_single_artifact with labels (lines 140-141, 144-146, 148-153, 155)."""
        artifact_data = ArtifactFile(
            file="/tmp/test.rpm", labels={"build_id": "test-build", "arch": "x86_64", "namespace": "test-ns"}
        )
        with patch("pulp_tool.pull.reporting.logging") as mock_logging, patch("os.path.getsize", return_value=1024):
            file_size = _log_single_artifact("test.rpm", artifact_data)
            assert file_size == 1024
            mock_logging.debug.assert_any_call("    - %s", "test.rpm")
            mock_logging.debug.assert_any_call("      Location: %s", "/tmp/test.rpm")
            mock_logging.debug.assert_any_call("      Size: %s", "1.0 KB")
            mock_logging.debug.assert_any_call("      Build ID: %s", "test-build")
            mock_logging.debug.assert_any_call("      Architecture: %s", "x86_64")
            mock_logging.debug.assert_any_call("      Namespace: %s", "test-ns")

    def test_log_single_artifact_without_labels(self) -> None:
        """Test _log_single_artifact without labels (lines 144-146)."""
        artifact_data = ArtifactFile(file="/tmp/test.rpm", labels={})
        with patch("pulp_tool.pull.reporting.logging") as mock_logging, patch("os.path.getsize", return_value=512):
            file_size = _log_single_artifact("test.rpm", artifact_data)
            assert file_size == 512
            mock_logging.debug.assert_any_call("      Build ID: %s", "Unknown")
            mock_logging.debug.assert_any_call("      Architecture: %s", "Unknown")
            mock_logging.debug.assert_any_call("      Namespace: %s", "Unknown")

    def test_calculate_artifact_totals(self) -> None:
        """Test _calculate_artifact_totals (lines 168-169, 172, 175-178, 180)."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test1.rpm", "/tmp/test1.rpm", {})
        pulled_artifacts.add_rpm("test2.rpm", "/tmp/test2.rpm", {})
        with patch("pulp_tool.pull.reporting._log_single_artifact") as mock_log:
            mock_log.side_effect = [1024, 2048]
            total_files, total_size = _calculate_artifact_totals(pulled_artifacts)
            assert total_files == 2
            assert total_size == 3072
            assert mock_log.call_count == 2

    def test_format_download_summary(self) -> None:
        """Test _format_download_summary (lines 195-196, 198-199, 201-202, 204)."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test.rpm", "/tmp/test.rpm", {})
        summary = _format_download_summary(pulled_artifacts, 1024)
        assert "Downloaded:" in summary
        assert "1.0 KB" in summary

    def test_format_download_summary_no_artifacts(self) -> None:
        """Test _format_download_summary with no artifacts (lines 201-202)."""
        pulled_artifacts = PulledArtifacts()
        summary = _format_download_summary(pulled_artifacts, 0)
        assert summary == "Downloaded: No files"

    def test_log_artifacts_downloaded(self) -> None:
        """Test _log_artifacts_downloaded (lines 217-219, 221)."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test.rpm", "/tmp/test.rpm", {})
        with (
            patch("pulp_tool.pull.reporting._calculate_artifact_totals", return_value=(1, 1024)),
            patch("pulp_tool.pull.reporting._format_download_summary", return_value="Downloaded: 1 RPM (1.0 KB)"),
            patch("pulp_tool.pull.reporting.logging") as mock_logging,
        ):
            total_files, total_size = _log_artifacts_downloaded(pulled_artifacts)
            assert total_files == 1
            assert total_size == 1024
            mock_logging.info.assert_called_once_with("Downloaded: 1 RPM (1.0 KB)")

    def test_log_storage_summary_zero_files(self) -> None:
        """Test _log_storage_summary with zero files (line 254)."""
        pulled_artifacts = PulledArtifacts()
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_storage_summary(0, pulled_artifacts)
            mock_logging.debug.assert_not_called()

    def test_log_pulp_upload_info_no_uploads(self) -> None:
        """Test _log_pulp_upload_info with no uploads (line 289)."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test-build", repositories=repositories)
        upload_info.uploaded_counts.rpms = 0
        upload_info.uploaded_counts.sboms = 0
        upload_info.uploaded_counts.logs = 0
        with patch("pulp_tool.pull.reporting.logging") as mock_logging:
            _log_pulp_upload_info(upload_info)
            mock_logging.info.assert_any_call("No files uploaded to Pulp")

    def test_generate_pull_report(self) -> None:
        """Test generate_pull_report (lines 330-334, 336)."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test.rpm", "/tmp/test.rpm", {"build_id": "test-build"})
        args = Mock()
        args.artifact_location = "test.json"
        args.max_workers = 4
        with (
            patch("pulp_tool.pull.reporting._log_pull_summary") as mock_transfer,
            patch("pulp_tool.pull.reporting._log_artifacts_downloaded", return_value=(1, 1024)) as mock_artifacts,
            patch("pulp_tool.pull.reporting._log_storage_summary") as mock_storage,
            patch("pulp_tool.pull.reporting._log_pulp_upload_info") as mock_upload,
            patch("pulp_tool.pull.reporting._log_build_information") as mock_build,
            patch("pulp_tool.pull.reporting.logging") as mock_logging,
        ):
            generate_pull_report(pulled_artifacts, 1, 0, args, None)
            mock_transfer.assert_called_once_with(1, 0, args)
            mock_artifacts.assert_called_once_with(pulled_artifacts)
            mock_storage.assert_called_once_with(1, pulled_artifacts)
            mock_upload.assert_called_once_with(None)
            mock_build.assert_called_once_with(pulled_artifacts)
            mock_logging.info.assert_any_call("Pull completed successfully")
