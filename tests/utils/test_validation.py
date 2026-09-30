"""
Tests for validation utility functions.

This module tests file validation, build ID validation, and sanitization functions.
"""

import os
import tempfile

import pytest

from pulp_tool.models.artifacts import ArtifactMetadata, PulledArtifacts
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.utils import (
    extract_build_id_from_artifact_json,
    extract_build_id_from_artifacts,
    sanitize_build_id_for_repository,
    validate_build_id,
    validate_file_path,
    validate_repository_setup,
)
from pulp_tool.utils.validation.build_id import (
    _extract_field_from_artifact,
    extract_metadata_from_artifact_json,
    strip_namespace_from_build_id,
)


class TestFileValidation:
    """Test file validation utility functions."""

    def test_validate_file_path_success(self, temp_file) -> None:
        """Test validate_file_path with valid file."""
        validate_file_path(temp_file, "Test")

    def test_validate_file_path_not_found(self) -> None:
        """Test validate_file_path with non-existent file."""
        with pytest.raises(FileNotFoundError, match="Test file not found"):
            validate_file_path("/non/existent/file.txt", "Test")

    def test_validate_file_path_empty(self) -> None:
        """Test validate_file_path with empty file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
        try:
            with pytest.raises(ValueError, match="Test file is empty"):
                validate_file_path(temp_path, "Test")
        finally:
            os.unlink(temp_path)

    def test_validate_file_path_permission_error(self) -> None:
        """Test validate_file_path with permission error."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
            f.write(b"test content")
        try:
            os.chmod(temp_path, 0)
            with pytest.raises(PermissionError, match="Cannot read"):
                validate_file_path(temp_path, "Test")
        finally:
            os.chmod(temp_path, 420)
            os.unlink(temp_path)


class TestBuildIDValidation:
    """Test build ID validation utility functions."""

    def test_validate_build_id_valid(self) -> None:
        """Test validate_build_id with valid build ID."""
        assert validate_build_id("test-build-123") is True

    def test_validate_build_id_invalid(self) -> None:
        """Test validate_build_id with invalid build ID."""
        assert validate_build_id("") is False
        assert validate_build_id(None) is False
        assert validate_build_id(123) is False

    def test_sanitize_build_id_for_repository(self) -> None:
        """Test sanitize_build_id_for_repository function."""
        assert sanitize_build_id_for_repository("test-build-123") == "test-build-123"
        assert sanitize_build_id_for_repository("test/build:123") == "test-build-123"
        assert sanitize_build_id_for_repository("") == "default-build"
        assert sanitize_build_id_for_repository(None) == "default-build"
        assert sanitize_build_id_for_repository("test--build---123") == "test-build-123"
        assert sanitize_build_id_for_repository("-test-build-123-") == "test-build-123"

    def test_sanitize_build_id_all_invalid_chars(self) -> None:
        """Test sanitize_build_id_for_repository with all invalid characters."""
        result = sanitize_build_id_for_repository("///:::***")
        assert result == "default-build"


class TestRepositoryValidation:
    """Test repository validation utility functions."""

    def test_validate_repository_setup_valid(self, mock_repositories) -> None:
        """Test validate_repository_setup function with valid setup."""
        is_valid, errors = validate_repository_setup(mock_repositories)
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_repository_setup_missing_repo(self) -> None:
        """Test validate_repository_setup function with missing repository."""
        repositories = {"rpms_prn": "test-prn", "rpms_href": "test-href"}
        is_valid, errors = validate_repository_setup(repositories)
        assert is_valid is False
        assert len(errors) > 0
        assert any("Missing logs repository PRN" in error for error in errors)

    def test_validate_repository_setup_missing_rpm_href(self) -> None:
        """Test validate_repository_setup function with missing RPM href."""
        repositories = {
            "rpms_prn": "test-prn",
            "logs_prn": "test-prn",
            "sbom_prn": "test-prn",
            "artifacts_prn": "test-prn",
        }
        is_valid, errors = validate_repository_setup(repositories)
        assert is_valid is False
        assert any("Missing rpms repository href" in error for error in errors)

    def test_validate_repository_setup_invalid_reference(self) -> None:
        """Test validate_repository_setup with invalid repository reference."""
        repositories = {
            "rpms_prn": "test-prn",
            "rpms_href": "  ",
            "logs_prn": "test-prn",
            "logs_href": "test-href",
            "sbom_prn": "test-prn",
            "sbom_href": "test-href",
            "artifacts_prn": "test-prn",
            "artifacts_href": "test-href",
        }
        is_valid, errors = validate_repository_setup(repositories)
        assert is_valid is False
        assert any("Invalid repository reference" in error for error in errors)

    def test_validate_repository_setup_required_types_excludes_artifacts(self) -> None:
        """Test validate_repository_setup with required_types excluding artifacts."""
        repos = {"rpms_prn": "rpms-prn", "rpms_href": "rpms-href", "logs_prn": "logs-prn", "sbom_prn": "sbom-prn"}
        required = ["rpms", "logs", "sbom"]
        is_valid, errors = validate_repository_setup(repos, required_types=required)
        assert is_valid is True
        assert len(errors) == 0


class TestBuildIDExtraction:
    """Test build ID extraction functions."""

    def test_extract_build_id_with_artifact_json_response(self) -> None:
        """Test extract_build_id_from_artifact_json with PulpResultsDocument object."""
        metadata = ArtifactMetadata(pulp_labels={"build_id": "test-build-123", "arch": "x86_64"})
        artifact_json = PulpResultsDocument(artifacts={"test.rpm": metadata})
        build_id = extract_build_id_from_artifact_json(artifact_json)
        assert build_id == "test-build-123"

    def test_extract_build_id_with_dict_fallback(self) -> None:
        """Test extract_build_id_from_artifact_json with dict fallback path."""
        artifact_json = {"artifacts": {"test.rpm": {"pulp_labels": {"build_id": "dict-build-456", "arch": "x86_64"}}}}
        build_id = extract_build_id_from_artifact_json(artifact_json)
        assert build_id == "dict-build-456"

    def test_extract_build_id_from_pulled_artifacts_model(self) -> None:
        """Test extract_build_id_from_artifacts with PulledArtifacts Pydantic model."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test.rpm", "/tmp/test.rpm", {"build_id": "model-build-789", "arch": "x86_64"})
        build_id = extract_build_id_from_artifacts(pulled_artifacts)
        assert build_id == "model-build-789"

    def test_extract_build_id_from_pulled_artifacts_sbom(self) -> None:
        """Test extract_build_id_from_artifacts extracting from sbom artifacts."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_sbom("test.sbom", "/tmp/test.sbom", {"build_id": "sbom-build-123", "arch": "noarch"})
        build_id = extract_build_id_from_artifacts(pulled_artifacts)
        assert build_id == "sbom-build-123"

    def test_extract_build_id_from_pulled_artifacts_fallback(self) -> None:
        """Test extract_build_id_from_artifacts fallback when no build_id found."""
        pulled_artifacts = PulledArtifacts()
        build_id = extract_build_id_from_artifacts(pulled_artifacts)
        assert build_id == "rok-storage"


class TestAdditionalValidation:
    """Additional validation tests for coverage."""

    def test_strip_namespace_from_build_id(self) -> None:
        """Test strip_namespace_from_build_id function."""
        result = strip_namespace_from_build_id("namespace/build-123")
        assert result == "build-123"
        result = strip_namespace_from_build_id("build-456")
        assert result == "build-456"
        result = strip_namespace_from_build_id("")
        assert result == ""

    def test_extract_field_from_artifact(self) -> None:
        """Test _extract_field_from_artifact with both dict and ArtifactMetadata inputs."""
        artifact_dict = {"pulp_labels": {"build_id": "test-build-123", "arch": "x86_64"}}
        result = _extract_field_from_artifact(artifact_dict, "build_id")
        assert result == "test-build-123"
        result = _extract_field_from_artifact(artifact_dict, "missing_field")
        assert result is None
        artifact_dict_no_labels = {"file": "test.rpm"}
        result = _extract_field_from_artifact(artifact_dict_no_labels, "build_id")
        assert result is None
        metadata = ArtifactMetadata(pulp_labels={"build_id": "test-build-456", "arch": "x86_64"})
        result = _extract_field_from_artifact(metadata, "build_id")
        assert result == "test-build-456"
        metadata_no_labels = ArtifactMetadata(pulp_labels={})
        result = _extract_field_from_artifact(metadata_no_labels, "build_id")
        assert result is None

    def test_extract_metadata_from_artifact_json_with_labels_none(self) -> None:
        """Test extract_metadata_from_artifact_json with dict metadata having labels=None (covers line 169)."""
        artifact_json = {"artifacts": {"test.rpm": {"labels": None, "url": "https://example.com/test.rpm"}}}
        result = extract_metadata_from_artifact_json(artifact_json, "build_id", fallback="fallback-value")
        assert result == "fallback-value"

    def test_extract_metadata_from_artifact_json_with_non_dict_metadata(self) -> None:
        """Test extract_metadata_from_artifact_json with non-dict metadata (covers line 172)."""
        metadata = ArtifactMetadata(pulp_labels={"build_id": "test-build-789", "arch": "x86_64"})
        artifact_json = {"artifacts": {"test.rpm": metadata}}
        result = extract_metadata_from_artifact_json(artifact_json, "build_id", fallback="fallback-value")
        assert result == "test-build-789"

    def test_validate_build_id_with_space(self) -> None:
        """Test validate_build_id with space character (line 101)."""
        assert validate_build_id("test build") is False

    def test_validate_build_id_with_slash(self) -> None:
        """Test validate_build_id with slash character (line 101)."""
        assert validate_build_id("test/build") is False

    def test_extract_field_from_artifact_none(self) -> None:
        """Test _extract_field_from_artifact with None/other types (line 125)."""
        result = _extract_field_from_artifact(None, "build_id")
        assert result is None
        result = _extract_field_from_artifact("not a dict or ArtifactMetadata", "build_id")
        assert result is None
