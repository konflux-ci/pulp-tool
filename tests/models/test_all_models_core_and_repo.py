"""Tests for core models (repo, context, artifacts)."""

import pytest
from pydantic import ValidationError

from pulp_tool.models.artifacts import (
    ArtifactFile,
    PulledArtifacts,
)
from pulp_tool.models.base import KonfluxBaseModel
from pulp_tool.models.context import PullContext, UploadRpmContext
from pulp_tool.models.repository import RepositoryRefs


class TestKonfluxBaseModel:
    """Test base model configuration."""

    def test_extra_fields_forbidden(self) -> None:
        """Test that extra fields are not allowed."""

        class TestModel(KonfluxBaseModel):
            name: str

        with pytest.raises(ValidationError) as exc_info:
            TestModel(name="test", extra_field="should fail")
        assert "extra_field" in str(exc_info.value)

    def test_validate_assignment(self) -> None:
        """Test that assignment validation is enabled."""

        class TestModel(KonfluxBaseModel):
            age: int

        model = TestModel(age=25)
        with pytest.raises(ValidationError):
            model.age = "not an integer"


class TestRepositoryRefs:
    """Test RepositoryRefs model."""

    def test_create_repository_refs(self) -> None:
        """Test creating a RepositoryRefs instance."""
        refs = RepositoryRefs(
            rpms_href="/pulp/api/v3/repositories/rpm/123/",
            rpms_prn="pulp:rpm:123",
            logs_href="/pulp/api/v3/repositories/file/logs-123/",
            logs_prn="pulp:file:logs-123",
            sbom_href="/pulp/api/v3/repositories/file/sbom-123/",
            sbom_prn="pulp:file:sbom-123",
            artifacts_href="/pulp/api/v3/repositories/file/artifacts-123/",
            artifacts_prn="pulp:file:artifacts-123",
        )
        assert refs.rpms_href == "/pulp/api/v3/repositories/rpm/123/"
        assert refs.rpms_prn == "pulp:rpm:123"
        assert refs.logs_href == "/pulp/api/v3/repositories/file/logs-123/"
        assert refs.logs_prn == "pulp:file:logs-123"
        assert refs.sbom_href == "/pulp/api/v3/repositories/file/sbom-123/"
        assert refs.sbom_prn == "pulp:file:sbom-123"
        assert refs.artifacts_href == "/pulp/api/v3/repositories/file/artifacts-123/"
        assert refs.artifacts_prn == "pulp:file:artifacts-123"

    def test_repository_refs_required_fields(self) -> None:
        """Test that all fields are required."""
        with pytest.raises(ValidationError):
            RepositoryRefs(rpms_href="/test/", rpms_prn="test")


class TestUploadRpmContext:
    """Test UploadRpmContext model."""

    def test_create_upload_rpm_context_minimal(self) -> None:
        """Test creating UploadRpmContext with minimal required fields."""
        context = UploadRpmContext(
            build_id="test-build-123",
            date_str="2024-01-15",
            namespace="test-namespace",
            parent_package="test-package",
            rpm_path="/path/to/rpms",
            sbom_path="/path/to/sbom.json",
        )
        assert context.build_id == "test-build-123"
        assert context.date_str == "2024-01-15"
        assert context.namespace == "test-namespace"
        assert context.parent_package == "test-package"
        assert context.rpm_path == "/path/to/rpms"
        assert context.sbom_path == "/path/to/sbom.json"
        assert context.config is None
        assert context.debug == 0
        assert context.artifact_results is None
        assert context.sbom_results is None

    def test_upload_rpm_context_signed_by_gpg_user_id_normalized(self) -> None:
        """Pulp rejects commas/parens in labels; substitute for storage."""
        raw = "Red Hat Test (release,) <sec@example.com>"
        expected = "Red Hat Test [release:] <sec@example.com>"
        context = UploadRpmContext(
            build_id="b",
            date_str="2024-01-15",
            namespace="ns",
            signed_by=raw,
        )
        assert context.signed_by == expected

    def test_upload_rpm_context_signed_by_whitespace_only_becomes_none(self) -> None:
        context = UploadRpmContext(
            build_id="b",
            date_str="2024-01-15",
            namespace="ns",
            signed_by="  \t  ",
        )
        assert context.signed_by is None

    def test_create_upload_rpm_context_full(self) -> None:
        """Test creating UploadRpmContext with all fields."""
        context = UploadRpmContext(
            build_id="test-build-123",
            date_str="2024-01-15",
            namespace="test-namespace",
            parent_package="test-package",
            rpm_path="/path/to/rpms",
            sbom_path="/path/to/sbom.json",
            config="/path/to/config.toml",
            debug=2,
            artifact_results="url_path,digest_path",
            sbom_results="/path/to/sbom_results.txt",
        )
        assert context.config == "/path/to/config.toml"
        assert context.debug == 2
        assert context.artifact_results == "url_path,digest_path"
        assert context.sbom_results == "/path/to/sbom_results.txt"


class TestPullContext:
    """Test PullContext model."""

    def test_create_pull_context_minimal(self) -> None:
        """Test creating PullContext with minimal required fields."""
        context = PullContext(artifact_location="https://example.com/artifacts.json")
        assert context.artifact_location == "https://example.com/artifacts.json"
        assert context.key_path is None
        assert context.config is None
        assert context.transfer_dest is None
        assert context.build_id is None
        assert context.max_workers == 10
        assert context.debug == 0

    def test_create_pull_context_full(self) -> None:
        """Test creating PullContext with all fields."""
        context = PullContext(
            artifact_location="https://example.com/artifacts.json",
            key_path="/path/to/key.pem",
            config="/path/to/config.toml",
            transfer_dest="/path/to/dest.toml",
            build_id="test-build-123",
            max_workers=8,
            debug=2,
        )
        assert context.key_path == "/path/to/key.pem"
        assert context.config == "/path/to/config.toml"
        assert context.transfer_dest == "/path/to/dest.toml"
        assert context.build_id == "test-build-123"
        assert context.max_workers == 8
        assert context.debug == 2

    def test_pull_context_invalid_operation_label(self) -> None:
        """PullContext rejects unknown operation_label values."""
        with pytest.raises(ValidationError, match="operation_label"):
            PullContext(operation_label="sync")


class TestArtifactFile:
    """Test ArtifactFile model."""

    def test_create_artifact_file_minimal(self) -> None:
        """Test creating ArtifactFile with minimal fields."""
        artifact = ArtifactFile(file="/path/to/artifact.rpm", labels={})
        assert artifact.file == "/path/to/artifact.rpm"
        assert artifact.labels == {}

    def test_create_artifact_file_full(self) -> None:
        """Test creating ArtifactFile with all fields."""
        artifact = ArtifactFile(
            file="/path/to/artifact.rpm", labels={"build_id": "test-123", "arch": "x86_64", "namespace": "test-ns"}
        )
        assert artifact.file == "/path/to/artifact.rpm"
        assert artifact.labels == {"build_id": "test-123", "arch": "x86_64", "namespace": "test-ns"}

    def test_artifact_file_properties(self) -> None:
        """Test ArtifactFile property accessors."""
        artifact = ArtifactFile(
            file="/path/to/test.rpm", labels={"build_id": "test-123", "arch": "x86_64", "namespace": "test-ns"}
        )
        assert artifact.file_name == "test.rpm"
        assert artifact.file_dir == "/path/to"
        assert artifact.build_id == "test-123"
        assert artifact.arch == "x86_64"
        assert artifact.namespace == "test-ns"


class TestPulledArtifacts:
    """Test PulledArtifacts model."""

    def test_create_pulled_artifacts_empty(self) -> None:
        """Test creating empty PulledArtifacts."""
        artifacts = PulledArtifacts()
        assert artifacts.rpms == {}
        assert artifacts.sboms == {}
        assert artifacts.logs == {}

    def test_create_pulled_artifacts_with_data(self) -> None:
        """Test creating PulledArtifacts with data."""
        artifacts = PulledArtifacts(
            rpms={"test.rpm": ArtifactFile(file="/tmp/test.rpm", labels={"build_id": "test-123"})},
            sboms={"sbom.json": ArtifactFile(file="/tmp/sbom.json", labels={"build_id": "test-123"})},
            logs={"build.log": ArtifactFile(file="/tmp/build.log", labels={"build_id": "test-123"})},
        )
        assert len(artifacts.rpms) == 1
        assert len(artifacts.sboms) == 1
        assert len(artifacts.logs) == 1
        assert "test.rpm" in artifacts.rpms
        assert artifacts.rpms["test.rpm"].file == "/tmp/test.rpm"
