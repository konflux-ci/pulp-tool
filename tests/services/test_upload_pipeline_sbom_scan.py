"""Tests for upload pipeline (SBOM, classify, scan)."""

import json
import logging
from unittest.mock import Mock

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.services.upload_service import (
    _classify_artifact_from_key,
    _handle_sbom_results,
    scan_results_json_for_log_and_sbom_keys,
)


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
