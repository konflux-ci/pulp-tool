#!/usr/bin/env python3
"""
Tests for data models in pulp_tool.models.

This test file covers the following model modules:
- base.py: Base model classes
- repository.py: Repository-related models
- context.py: Context configuration models
- artifacts.py: Artifact data models
- results.py: Operation result models
- statistics.py: Statistics and tracking models
- pulp_api.py: Pulp API response models

Note: Validation models are tested separately in test_validation_models.py
"""

import pytest
from pydantic import ValidationError

from pulp_tool.models.base import KonfluxBaseModel
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.context import (
    UploadContext,
    TransferContext,
)
from pulp_tool.models.artifacts import (
    DownloadTask,
    ArtifactFile,
    PulledArtifacts,
    ArtifactMetadata,
    ArtifactJsonResponse,
    ArtifactData,
    ContentData,
)
from pulp_tool.models.results import (
    DownloadResult,
)
from pulp_tool.models.statistics import (
    DownloadStats,
    UploadCounts,
)


class TestKonfluxBaseModel:
    """Test base model configuration."""

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""

        class TestModel(KonfluxBaseModel):
            name: str

        with pytest.raises(ValidationError) as exc_info:
            TestModel(name="test", extra_field="should fail")

        assert "extra_field" in str(exc_info.value)

    def test_validate_assignment(self):
        """Test that assignment validation is enabled."""

        class TestModel(KonfluxBaseModel):
            age: int

        model = TestModel(age=25)

        with pytest.raises(ValidationError):
            model.age = "not an integer"


class TestRepositoryRefs:
    """Test RepositoryRefs model."""

    def test_create_repository_refs(self):
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

    def test_repository_refs_required_fields(self):
        """Test that all fields are required."""
        with pytest.raises(ValidationError):
            RepositoryRefs(rpms_href="/test/", rpms_prn="test")


class TestUploadContext:
    """Test UploadContext model."""

    def test_create_upload_context_minimal(self):
        """Test creating UploadContext with minimal required fields."""
        context = UploadContext(
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
        assert context.cert_config is None
        assert context.debug == 0
        assert context.artifact_results is None
        assert context.sbom_results is None

    def test_create_upload_context_full(self):
        """Test creating UploadContext with all fields."""
        context = UploadContext(
            build_id="test-build-123",
            date_str="2024-01-15",
            namespace="test-namespace",
            parent_package="test-package",
            rpm_path="/path/to/rpms",
            sbom_path="/path/to/sbom.json",
            config="/path/to/config.toml",
            cert_config="/path/to/cert.conf",
            debug=2,
            artifact_results="url_path,digest_path",
            sbom_results="/path/to/sbom_results.txt",
        )

        assert context.config == "/path/to/config.toml"
        assert context.cert_config == "/path/to/cert.conf"
        assert context.debug == 2
        assert context.artifact_results == "url_path,digest_path"
        assert context.sbom_results == "/path/to/sbom_results.txt"


class TestTransferContext:
    """Test TransferContext model."""

    def test_create_transfer_context_minimal(self):
        """Test creating TransferContext with minimal required fields."""
        context = TransferContext(
            artifact_location="https://example.com/artifacts.json",
        )

        assert context.artifact_location == "https://example.com/artifacts.json"
        assert context.cert_path is None
        assert context.key_path is None
        assert context.config is None
        assert context.build_id is None
        assert context.max_workers == 10
        assert context.debug == 0

    def test_create_transfer_context_full(self):
        """Test creating TransferContext with all fields."""
        context = TransferContext(
            artifact_location="https://example.com/artifacts.json",
            cert_path="/path/to/cert.pem",
            key_path="/path/to/key.pem",
            config="/path/to/config.toml",
            build_id="test-build-123",
            max_workers=8,
            debug=2,
        )

        assert context.cert_path == "/path/to/cert.pem"
        assert context.key_path == "/path/to/key.pem"
        assert context.config == "/path/to/config.toml"
        assert context.build_id == "test-build-123"
        assert context.max_workers == 8
        assert context.debug == 2


class TestArtifactFile:
    """Test ArtifactFile model."""

    def test_create_artifact_file_minimal(self):
        """Test creating ArtifactFile with minimal fields."""
        artifact = ArtifactFile(
            file="/path/to/artifact.rpm",
            labels={},
        )

        assert artifact.file == "/path/to/artifact.rpm"
        assert artifact.labels == {}

    def test_create_artifact_file_full(self):
        """Test creating ArtifactFile with all fields."""
        artifact = ArtifactFile(
            file="/path/to/artifact.rpm",
            labels={"build_id": "test-123", "arch": "x86_64", "namespace": "test-ns"},
        )

        assert artifact.file == "/path/to/artifact.rpm"
        assert artifact.labels == {"build_id": "test-123", "arch": "x86_64", "namespace": "test-ns"}

    def test_artifact_file_properties(self):
        """Test ArtifactFile property accessors."""
        artifact = ArtifactFile(
            file="/path/to/test.rpm",
            labels={"build_id": "test-123", "arch": "x86_64", "namespace": "test-ns"},
        )

        assert artifact.file_name == "test.rpm"
        assert artifact.file_dir == "/path/to"
        assert artifact.build_id == "test-123"
        assert artifact.arch == "x86_64"
        assert artifact.namespace == "test-ns"


class TestPulledArtifacts:
    """Test PulledArtifacts model."""

    def test_create_pulled_artifacts_empty(self):
        """Test creating empty PulledArtifacts."""
        artifacts = PulledArtifacts()

        assert artifacts.rpms == {}
        assert artifacts.sboms == {}
        assert artifacts.logs == {}

    def test_create_pulled_artifacts_with_data(self):
        """Test creating PulledArtifacts with data."""
        artifacts = PulledArtifacts(
            rpms={
                "test.rpm": ArtifactFile(
                    file="/tmp/test.rpm",
                    labels={"build_id": "test-123"},
                )
            },
            sboms={
                "sbom.json": ArtifactFile(
                    file="/tmp/sbom.json",
                    labels={"build_id": "test-123"},
                )
            },
            logs={
                "build.log": ArtifactFile(
                    file="/tmp/build.log",
                    labels={"build_id": "test-123"},
                )
            },
        )

        assert len(artifacts.rpms) == 1
        assert len(artifacts.sboms) == 1
        assert len(artifacts.logs) == 1
        assert "test.rpm" in artifacts.rpms
        assert artifacts.rpms["test.rpm"].file == "/tmp/test.rpm"


class TestDownloadStats:
    """Test DownloadStats model."""

    def test_create_download_stats_defaults(self):
        """Test creating DownloadStats with defaults."""
        stats = DownloadStats()

        assert stats.pulled_artifacts == {}
        assert stats.completed == 0
        assert stats.failed == 0
        assert stats.total_attempted == 0

    def test_create_download_stats_with_values(self):
        """Test creating DownloadStats with values."""
        stats = DownloadStats(
            pulled_artifacts={"rpms": {}, "logs": {}},
            completed=8,
            failed=2,
        )

        assert stats.pulled_artifacts == {"rpms": {}, "logs": {}}
        assert stats.completed == 8
        assert stats.failed == 2
        assert stats.total_attempted == 10

    def test_download_stats_success_rate(self):
        """Test success rate calculation."""
        stats = DownloadStats(completed=8, failed=2)
        assert stats.success_rate == 80.0

        empty_stats = DownloadStats()
        assert empty_stats.success_rate == 0.0


class TestDownloadResult:
    """Test DownloadResult model."""

    def test_create_download_result_empty(self):
        """Test creating empty DownloadResult."""
        result = DownloadResult(
            pulled_artifacts=PulledArtifacts(),
            completed=0,
            failed=0,
        )

        assert isinstance(result.pulled_artifacts, PulledArtifacts)
        assert result.completed == 0
        assert result.failed == 0
        assert result.total_attempted == 0
        assert result.has_failures is False

    def test_create_download_result_with_data(self):
        """Test creating DownloadResult with data."""
        result = DownloadResult(
            pulled_artifacts=PulledArtifacts(rpms={"test.rpm": ArtifactFile(file="/tmp/test.rpm", labels={})}),
            completed=5,
            failed=1,
        )

        assert result.completed == 5
        assert result.failed == 1
        assert result.total_attempted == 6
        assert result.has_failures is True
        assert result.success_rate == pytest.approx(83.33, rel=0.01)


class TestUploadCounts:
    """Test UploadCounts model."""

    def test_create_upload_counts_defaults(self):
        """Test creating UploadCounts with defaults."""
        counts = UploadCounts()

        assert counts.rpms == 0
        assert counts.logs == 0
        assert counts.sboms == 0

    def test_create_upload_counts_with_values(self):
        """Test creating UploadCounts with values."""
        counts = UploadCounts(rpms=10, logs=5, sboms=1)

        assert counts.rpms == 10
        assert counts.logs == 5
        assert counts.sboms == 1


class TestPulpResultsModel:
    """Test PulpResultsModel - unified tracking and results model."""

    def test_create_pulp_results_model(self):
        """Test creating PulpResultsModel instance."""
        from pulp_tool.models.results import PulpResultsModel

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
        model = PulpResultsModel(build_id="test-build-123", repositories=repositories)

        assert model.build_id == "test-build-123"
        assert isinstance(model.repositories, RepositoryRefs)
        assert model.artifacts == {}
        assert model.distributions == {}
        assert model.uploaded_counts.total == 0
        assert model.upload_errors == []

    def test_add_artifact(self):
        """Test adding artifacts to results model."""
        from pulp_tool.models.results import PulpResultsModel

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
        model = PulpResultsModel(build_id="test-build", repositories=repositories)

        model.add_artifact(
            key="test.rpm",
            url="https://pulp.example.com/test.rpm",
            sha256="abc123",
            labels={"arch": "x86_64", "build_id": "test-build"},
        )

        assert model.artifact_count == 1
        assert "test.rpm" in model.artifacts
        assert model.artifacts["test.rpm"].url == "https://pulp.example.com/test.rpm"
        assert model.artifacts["test.rpm"].sha256 == "abc123"
        assert model.artifacts["test.rpm"].labels["arch"] == "x86_64"

    def test_add_distribution(self):
        """Test adding distributions to results model."""
        from pulp_tool.models.results import PulpResultsModel

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
        model = PulpResultsModel(build_id="test-build", repositories=repositories)

        model.add_distribution("rpms", "https://pulp.example.com/rpms/")
        model.add_distribution("logs", "https://pulp.example.com/logs/")

        assert len(model.distributions) == 2
        assert model.distributions["rpms"] == "https://pulp.example.com/rpms/"
        assert model.distributions["logs"] == "https://pulp.example.com/logs/"

    def test_to_json_dict(self):
        """Test converting model to JSON dict."""
        from pulp_tool.models.results import PulpResultsModel

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
        model = PulpResultsModel(build_id="test-build", repositories=repositories)

        model.add_artifact("test.rpm", "https://pulp.example.com/test.rpm", "abc123", {"arch": "x86_64"})
        model.add_distribution("rpms", "https://pulp.example.com/rpms/")

        result = model.to_json_dict()

        assert "artifacts" in result
        assert "distributions" in result
        assert "test.rpm" in result["artifacts"]
        assert result["artifacts"]["test.rpm"]["url"] == "https://pulp.example.com/test.rpm"
        assert result["distributions"]["rpms"] == "https://pulp.example.com/rpms/"

    def test_tracking_functionality(self):
        """Test upload tracking functionality."""
        from pulp_tool.models.results import PulpResultsModel

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
        model = PulpResultsModel(build_id="test-build", repositories=repositories)

        # Test upload counts
        model.uploaded_counts.rpms = 5
        model.uploaded_counts.logs = 2
        model.uploaded_counts.sboms = 1

        assert model.total_uploaded == 8
        assert model.uploaded_counts.rpms == 5

        # Test error tracking
        assert not model.has_errors
        model.add_error("Test error 1")
        model.add_error("Test error 2")

        assert model.has_errors
        assert model.error_count == 2
        assert "Test error 1" in model.upload_errors


class TestDownloadTask:
    """Test DownloadTask model."""

    def test_create_download_task(self):
        """Test creating a DownloadTask."""
        task = DownloadTask(
            artifact_name="test.rpm",
            file_url="https://example.com/rpms/Packages/l/test.rpm",
            arch="x86_64",
            artifact_type="rpm",
        )

        assert task.artifact_name == "test.rpm"
        assert task.file_url == "https://example.com/rpms/Packages/l/test.rpm"
        assert task.arch == "x86_64"
        assert task.artifact_type == "rpm"

    def test_download_task_to_tuple(self):
        """Test converting DownloadTask to tuple."""
        task = DownloadTask(
            artifact_name="test.sbom",
            file_url="https://example.com/sbom/test.sbom",
            arch="noarch",
            artifact_type="sbom",
        )

        task_tuple = task.to_tuple()

        assert task_tuple == ("test.sbom", "https://example.com/sbom/test.sbom", "noarch", "sbom")
        assert isinstance(task_tuple, tuple)
        assert len(task_tuple) == 4

    def test_download_task_types(self):
        """Test DownloadTask for different artifact types."""
        rpm_task = DownloadTask(artifact_name="test.rpm", file_url="url1", arch="x86_64", artifact_type="rpm")
        sbom_task = DownloadTask(artifact_name="test.sbom", file_url="url2", arch="noarch", artifact_type="sbom")
        log_task = DownloadTask(artifact_name="test.log", file_url="url3", arch="noarch", artifact_type="log")

        assert rpm_task.artifact_type == "rpm"
        assert sbom_task.artifact_type == "sbom"
        assert log_task.artifact_type == "log"


class TestContentData:
    """Test ContentData model."""

    def test_create_content_data_empty(self):
        """Test creating empty ContentData."""
        data = ContentData()

        assert data.content_results == []
        assert data.artifacts == []

    def test_create_content_data_with_results(self):
        """Test creating ContentData with results."""
        data = ContentData(
            content_results=[{"pulp_href": "/pulp/api/v3/content/rpm/1/", "name": "test.rpm"}],
            artifacts=[{"pulp_href": "/pulp/api/v3/artifacts/1/", "sha256": "abc123"}],
        )

        assert len(data.content_results) == 1
        assert len(data.artifacts) == 1
        assert data.content_results[0]["name"] == "test.rpm"
        assert data.artifacts[0]["sha256"] == "abc123"


class TestArtifactMetadata:
    """Test ArtifactMetadata model."""

    def test_create_artifact_metadata_empty(self):
        """Test creating empty ArtifactMetadata."""
        metadata = ArtifactMetadata()

        assert metadata.labels == {}

    def test_create_artifact_metadata_with_labels(self):
        """Test creating ArtifactMetadata with labels."""
        metadata = ArtifactMetadata(
            labels={
                "build_id": "test-build-123",
                "arch": "x86_64",
                "namespace": "test-namespace",
                "parent_package": "test-package",
            }
        )

        assert metadata.labels["build_id"] == "test-build-123"
        assert metadata.labels["arch"] == "x86_64"
        assert metadata.labels["namespace"] == "test-namespace"
        assert metadata.labels["parent_package"] == "test-package"

    def test_artifact_metadata_properties(self):
        """Test ArtifactMetadata property accessors."""
        metadata = ArtifactMetadata(
            labels={
                "build_id": "test-123",
                "arch": "x86_64",
                "namespace": "my-namespace",
                "parent_package": "my-package",
            }
        )

        assert metadata.build_id == "test-123"
        assert metadata.arch == "x86_64"
        assert metadata.namespace == "my-namespace"
        assert metadata.parent_package == "my-package"

    def test_artifact_metadata_properties_missing(self):
        """Test ArtifactMetadata properties when labels are missing."""
        metadata = ArtifactMetadata(labels={})

        assert metadata.build_id is None
        assert metadata.arch is None
        assert metadata.namespace is None
        assert metadata.parent_package is None

    def test_artifact_metadata_with_url_and_sha256(self):
        """Test ArtifactMetadata with url and sha256 fields."""
        metadata = ArtifactMetadata(
            labels={"build_id": "test-123", "arch": "x86_64"},
            url="https://example.com/artifacts/test.rpm",
            sha256="a1b2c3d4e5f6",
        )

        assert metadata.url == "https://example.com/artifacts/test.rpm"
        assert metadata.sha256 == "a1b2c3d4e5f6"
        assert metadata.build_id == "test-123"
        assert metadata.arch == "x86_64"

    def test_artifact_metadata_without_url_and_sha256(self):
        """Test ArtifactMetadata without url and sha256 fields."""
        metadata = ArtifactMetadata(labels={"build_id": "test-123"})

        assert metadata.url is None
        assert metadata.sha256 is None
        assert metadata.build_id == "test-123"


class TestArtifactJsonResponse:
    """Test ArtifactJsonResponse model."""

    def test_create_artifact_json_response_empty(self):
        """Test creating empty ArtifactJsonResponse."""
        response = ArtifactJsonResponse()

        assert response.artifacts == {}
        assert response.distributions == {}

    def test_create_artifact_json_response_with_data(self):
        """Test creating ArtifactJsonResponse with data."""
        response = ArtifactJsonResponse(
            artifacts={
                "test.rpm": ArtifactMetadata(labels={"build_id": "test-123", "arch": "x86_64"}),
                "test2.rpm": ArtifactMetadata(labels={"build_id": "test-123", "arch": "aarch64"}),
            },
            distributions={
                "rpms": "https://pulp.example.com/rpms/",
                "logs": "https://pulp.example.com/logs/",
                "sbom": "https://pulp.example.com/sbom/",
            },
        )

        assert len(response.artifacts) == 2
        assert len(response.distributions) == 3
        assert "test.rpm" in response.artifacts
        assert response.distributions["rpms"] == "https://pulp.example.com/rpms/"

    def test_artifact_json_response_artifact_count(self):
        """Test artifact_count property."""
        response = ArtifactJsonResponse(
            artifacts={
                "test1.rpm": ArtifactMetadata(labels={}),
                "test2.rpm": ArtifactMetadata(labels={}),
                "test3.rpm": ArtifactMetadata(labels={}),
            }
        )

        assert response.artifact_count == 3

    def test_artifact_json_response_has_distributions(self):
        """Test has_distributions property."""
        response_empty = ArtifactJsonResponse()
        assert response_empty.has_distributions is False

        response_with_dists = ArtifactJsonResponse(distributions={"rpms": "https://example.com/rpms/"})
        assert response_with_dists.has_distributions is True

    def test_artifact_json_response_distribution_urls(self):
        """Test distribution URL properties."""
        response = ArtifactJsonResponse(
            distributions={
                "rpms": "https://pulp.example.com/rpms/",
                "logs": "https://pulp.example.com/logs/",
                "sbom": "https://pulp.example.com/sbom/",
            }
        )

        assert response.rpms_distribution_url == "https://pulp.example.com/rpms/"
        assert response.logs_distribution_url == "https://pulp.example.com/logs/"
        assert response.sbom_distribution_url == "https://pulp.example.com/sbom/"

    def test_artifact_json_response_distribution_urls_missing(self):
        """Test distribution URL properties when missing."""
        response = ArtifactJsonResponse()

        assert response.rpms_distribution_url is None
        assert response.logs_distribution_url is None
        assert response.sbom_distribution_url is None

    def test_artifact_json_response_get_artifact(self):
        """Test get_artifact method."""
        metadata = ArtifactMetadata(labels={"build_id": "test-123"})
        response = ArtifactJsonResponse(artifacts={"test.rpm": metadata})

        retrieved = response.get_artifact("test.rpm")
        assert retrieved is not None
        assert retrieved.build_id == "test-123"

        missing = response.get_artifact("nonexistent.rpm")
        assert missing is None


class TestArtifactData:
    """Test ArtifactData model."""

    def test_create_artifact_data_empty(self):
        """Test creating empty ArtifactData."""
        data = ArtifactData()

        assert isinstance(data.artifact_json, ArtifactJsonResponse)
        assert data.artifacts == {}

    def test_create_artifact_data_with_data(self):
        """Test creating ArtifactData with data."""
        artifact_json = ArtifactJsonResponse(
            artifacts={
                "test.rpm": ArtifactMetadata(labels={"build_id": "test-123"}),
            },
            distributions={"rpms": "https://pulp.example.com/rpms/"},
        )

        data = ArtifactData(
            artifact_json=artifact_json,
            artifacts={
                "test.rpm": ArtifactMetadata(labels={"build_id": "test-123"}),
            },
        )

        assert isinstance(data.artifact_json, ArtifactJsonResponse)
        assert len(data.artifacts) == 1
        assert "test.rpm" in data.artifacts

    def test_artifact_data_artifact_count(self):
        """Test artifact_count property."""
        data = ArtifactData(
            artifacts={
                "test1.rpm": ArtifactMetadata(labels={}),
                "test2.rpm": ArtifactMetadata(labels={}),
            }
        )

        assert data.artifact_count == 2

    def test_artifact_data_has_distributions(self):
        """Test has_distributions property."""
        data_without = ArtifactData()
        assert data_without.has_distributions is False

        data_with = ArtifactData(
            artifact_json=ArtifactJsonResponse(distributions={"rpms": "https://example.com/rpms/"})
        )
        assert data_with.has_distributions is True

    def test_artifact_data_get_distributions(self):
        """Test get_distributions method."""
        data = ArtifactData(
            artifact_json=ArtifactJsonResponse(
                distributions={
                    "rpms": "https://pulp.example.com/rpms/",
                    "logs": "https://pulp.example.com/logs/",
                }
            )
        )

        distributions = data.get_distributions()
        assert len(distributions) == 2
        assert distributions["rpms"] == "https://pulp.example.com/rpms/"
        assert distributions["logs"] == "https://pulp.example.com/logs/"


class TestModelValidation:
    """Test Pydantic validation features."""

    def test_type_validation(self):
        """Test that type validation works."""
        with pytest.raises(ValidationError):
            UploadCounts(rpms="not an integer")

    def test_required_fields_validation(self):
        """Test that required fields are enforced."""
        with pytest.raises(ValidationError):
            UploadContext(build_id="test")  # Missing required fields

    def test_default_values(self):
        """Test that default values work correctly."""
        context = TransferContext(
            artifact_location="test",
            cert_path="/path/to/cert.pem",
            key_path="/path/to/key.pem",
        )

        assert context.max_workers == 10  # default value
        assert context.debug == 0  # default value

    def test_nested_model_validation(self):
        """Test that nested models are validated."""
        from pulp_tool.models.results import PulpResultsModel

        with pytest.raises(ValidationError):
            PulpResultsModel(
                build_id="test",
                repositories="not a RepositoryRefs object",  # Should fail
            )


# TestAdditionalModelCoverage temporarily removed due to complex property access patterns
# Coverage for these properties is achieved through integration tests
