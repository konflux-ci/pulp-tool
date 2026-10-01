"""
Tests for URL utilities.

This module tests URL utilities including build ID extraction,
validation, and determination from various sources.
"""

import os
import tempfile
from unittest.mock import Mock

import pytest

from pulp_tool.utils import determine_build_id, extract_build_id_from_artifact_json, extract_build_id_from_artifacts
from pulp_tool.utils.url import get_pulp_content_base_url


class TestBuildIDExtraction:
    """Test build ID extraction from various sources."""

    def test_extract_build_id_from_artifact_json(self, mock_artifacts_json) -> None:
        """Test extract_build_id_from_artifact_json function."""
        build_id = extract_build_id_from_artifact_json(mock_artifacts_json)
        assert build_id == "test-build-123"

    def test_extract_build_id_from_artifact_json_no_build_id(self) -> None:
        """Test extract_build_id_from_artifact_json with no build_id."""
        artifact_json = {"artifacts": {"test-file": {"pulp_labels": {"arch": "x86_64"}}}}
        build_id = extract_build_id_from_artifact_json(artifact_json)
        assert build_id == "rok-storage"

    def test_extract_build_id_from_artifacts(self, mock_pulled_artifacts) -> None:
        """Test extract_build_id_from_artifacts function."""
        build_id = extract_build_id_from_artifacts(mock_pulled_artifacts)
        assert build_id == "test-build-123"

    def test_extract_build_id_from_artifacts_no_build_id(self) -> None:
        """Test extract_build_id_from_artifacts with no build_id."""
        from pulp_tool.models.artifacts import PulledArtifacts

        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test-file", "/tmp/test-file", {"arch": "x86_64"})
        build_id = extract_build_id_from_artifacts(pulled_artifacts)
        assert build_id == "rok-storage"


class TestBuildIDDetermination:
    """Test build ID determination with priority fallback."""

    def test_determine_build_id_from_args(self, mock_args) -> None:
        """Test determine_build_id with command line argument."""
        build_id = determine_build_id(mock_args)
        assert build_id == "test-build-123"

    def test_determine_build_id_from_artifact_json(self, mock_artifacts_json) -> None:
        """Test determine_build_id with artifact JSON."""
        args = Mock()
        args.build_id = None
        build_id = determine_build_id(args, artifact_json=mock_artifacts_json)
        assert build_id == "test-build-123"

    def test_determine_build_id_from_pulled_artifacts(self, mock_pulled_artifacts) -> None:
        """Test determine_build_id with pulled artifacts."""
        args = Mock()
        args.build_id = None
        build_id = determine_build_id(args, pulled_artifacts=mock_pulled_artifacts)
        assert build_id == "test-build-123"

    def test_determine_build_id_default(self) -> None:
        """Test determine_build_id with default fallback."""
        args = Mock()
        args.build_id = None
        build_id = determine_build_id(args)
        assert build_id == "rok-storage"


class TestPulpContentBaseUrl:
    """Test Pulp content base URL retrieval."""

    def test_get_pulp_content_base_url_success(self) -> None:
        """Test get_pulp_content_base_url with valid config file."""
        config_content = b'\n[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\n'
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".toml", delete=False) as config_file:
            config_file.write(config_content)
            config_path = config_file.name
        try:
            url = get_pulp_content_base_url(config_path)
            assert url == "https://pulp.example.com/api/pulp-content"
        finally:
            os.unlink(config_path)

    def test_get_pulp_content_base_url_file_not_found(self) -> None:
        """Test get_pulp_content_base_url with non-existent file."""
        with pytest.raises(ValueError, match="Cannot determine Pulp content base URL"):
            get_pulp_content_base_url("/nonexistent/config.toml")

    def test_get_pulp_content_base_url_no_path(self) -> None:
        """Test get_pulp_content_base_url with no path provided."""
        with pytest.raises(ValueError, match="cert_config_path is required"):
            get_pulp_content_base_url(None)

    def test_get_pulp_content_base_url_invalid_toml(self) -> None:
        """Test get_pulp_content_base_url with invalid TOML file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as config_file:
            config_file.write("invalid toml content [[[")
            config_path = config_file.name
        try:
            with pytest.raises(ValueError, match="Cannot determine Pulp content base URL"):
                get_pulp_content_base_url(config_path)
        finally:
            os.unlink(config_path)

    def test_get_pulp_content_base_url_missing_base_url_key(self) -> None:
        """Test get_pulp_content_base_url with missing base_url key."""
        config_content = b'\n[cli]\napi_root = "/pulp/api/v3"\n'
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".toml", delete=False) as config_file:
            config_file.write(config_content)
            config_path = config_file.name
        try:
            with pytest.raises(ValueError, match="Cannot determine Pulp content base URL"):
                get_pulp_content_base_url(config_path)
        finally:
            os.unlink(config_path)

    def test_get_pulp_content_base_url_missing_cli_section(self) -> None:
        """Test get_pulp_content_base_url with missing [cli] section."""
        config_content = b'\n[other]\nkey = "value"\n'
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".toml", delete=False) as config_file:
            config_file.write(config_content)
            config_path = config_file.name
        try:
            with pytest.raises(ValueError, match="Cannot determine Pulp content base URL"):
                get_pulp_content_base_url(config_path)
        finally:
            os.unlink(config_path)
