"""Tests for content metadata and artifact models."""

from collections.abc import Callable
from typing import Any, cast

import pytest
from pydantic import ValidationError

from pulp_tool.models.artifacts import (
    ArtifactMetadata,
    ContentData,
    DownloadTask,
    ExtraArtifactRef,
    PulpContentRow,
)
from tests.support.model_test_helpers import _http_url


class TestDownloadTask:
    """Test DownloadTask model."""

    def test_create_download_task(self) -> None:
        """Test creating a DownloadTask."""
        task = DownloadTask(
            artifact_name="test.rpm",
            file_url=_http_url("https://example.com/rpms/Packages/t/test.rpm"),
            arch="x86_64",
            artifact_type="rpm",
        )
        assert task.artifact_name == "test.rpm"
        assert str(task.file_url) == "https://example.com/rpms/Packages/t/test.rpm"
        assert task.arch == "x86_64"
        assert task.artifact_type == "rpm"

    def test_download_task_to_tuple(self) -> None:
        """Test converting DownloadTask to tuple."""
        task = DownloadTask(
            artifact_name="test.sbom",
            file_url=_http_url("https://example.com/sbom/test.sbom"),
            arch="noarch",
            artifact_type="sbom",
        )
        task_tuple = task.to_tuple()
        assert task_tuple == ("test.sbom", "https://example.com/sbom/test.sbom", "noarch", "sbom", None)
        assert isinstance(task_tuple, tuple)
        assert len(task_tuple) == 5

    def test_download_task_types(self) -> None:
        """Test DownloadTask for different artifact types."""
        rpm_task = DownloadTask(
            artifact_name="test.rpm", file_url=_http_url("https://example.com/u1"), arch="x86_64", artifact_type="rpm"
        )
        sbom_task = DownloadTask(
            artifact_name="test.sbom", file_url=_http_url("https://example.com/u2"), arch="noarch", artifact_type="sbom"
        )
        log_task = DownloadTask(
            artifact_name="test.log", file_url=_http_url("https://example.com/u3"), arch="noarch", artifact_type="log"
        )
        assert rpm_task.artifact_type == "rpm"
        assert sbom_task.artifact_type == "sbom"
        assert log_task.artifact_type == "log"

    def test_download_task_rejects_non_http_file_url(self) -> None:
        """Distribution download tasks require an absolute http(s) URL."""
        with pytest.raises(ValidationError):
            DownloadTask.model_validate(
                {"artifact_name": "a.rpm", "file_url": "not-a-url", "arch": "x86_64", "artifact_type": "rpm"}
            )


class TestContentData:
    """Test ContentData model."""

    def test_create_content_data_empty(self) -> None:
        """Test creating empty ContentData."""
        data = ContentData()
        assert data.content_results == []
        assert data.artifacts == []

    def test_create_content_data_with_results(self) -> None:
        """Test creating ContentData with results."""
        data = ContentData(
            content_results=[
                PulpContentRow.model_validate({"pulp_href": "/pulp/api/v3/content/rpm/1/", "name": "test.rpm"})
            ],
            artifacts=[{"pulp_href": "/pulp/api/v3/artifacts/1/", "sha256": "abc123"}],
        )
        assert len(data.content_results) == 1
        assert len(data.artifacts) == 1
        assert data.content_results[0].model_dump().get("name") == "test.rpm"
        assert data.artifacts[0]["sha256"] == "abc123"


class TestExtraArtifactRef:
    """ExtraArtifactRef model."""

    def test_explicit_pulp_href(self) -> None:
        assert ExtraArtifactRef(pulp_href="/content/1/").pulp_href == "/content/1/"

    def test_validator_passthrough_non_dict(self) -> None:
        ref = ExtraArtifactRef(pulp_href="/z/")
        same = ExtraArtifactRef.model_validate(ref)
        assert same.pulp_href == "/z/"


class TestArtifactMetadata:
    """Test ArtifactMetadata model."""

    def test_create_artifact_metadata_empty(self) -> None:
        """Test creating empty ArtifactMetadata."""
        metadata = ArtifactMetadata()
        assert metadata.pulp_labels == {}

    def test_create_artifact_metadata_with_labels(self) -> None:
        """Test creating ArtifactMetadata with labels."""
        metadata = ArtifactMetadata(
            pulp_labels={
                "build_id": "test-build-123",
                "arch": "x86_64",
                "namespace": "test-namespace",
                "parent_package": "test-package",
            }
        )
        assert metadata.pulp_labels["build_id"] == "test-build-123"
        assert metadata.pulp_labels["arch"] == "x86_64"
        assert metadata.pulp_labels["namespace"] == "test-namespace"
        assert metadata.pulp_labels["parent_package"] == "test-package"

    def test_artifact_metadata_properties(self) -> None:
        """Test ArtifactMetadata property accessors."""
        metadata = ArtifactMetadata(
            pulp_labels={
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

    def test_artifact_metadata_properties_missing(self) -> None:
        """Test ArtifactMetadata properties when labels are missing."""
        metadata = ArtifactMetadata(pulp_labels={})
        assert metadata.build_id is None
        assert metadata.arch is None
        assert metadata.namespace is None
        assert metadata.parent_package is None

    def test_artifact_metadata_with_url_and_sha256(self) -> None:
        """Test ArtifactMetadata with url and sha256 fields."""
        metadata = ArtifactMetadata(
            pulp_labels={"build_id": "test-123", "arch": "x86_64"},
            url="https://example.com/artifacts/test.rpm",
            sha256="a1b2c3d4e5f6",
        )
        assert metadata.url == "https://example.com/artifacts/test.rpm"
        assert metadata.sha256 == "a1b2c3d4e5f6"
        assert metadata.build_id == "test-123"
        assert metadata.arch == "x86_64"

    def test_artifact_metadata_without_url_and_sha256(self) -> None:
        """Test ArtifactMetadata without url and sha256 fields."""
        metadata = ArtifactMetadata(pulp_labels={"build_id": "test-123"})
        assert metadata.url is None
        assert metadata.sha256 is None
        assert metadata.build_id == "test-123"

    def test_artifact_metadata_explicit_null_url_from_dict(self) -> None:
        """Explicit null url runs url normalizer early-return branch."""
        metadata = ArtifactMetadata.model_validate({"pulp_labels": {}, "url": None})
        assert metadata.url is None

    def test_artifact_metadata_href_history_coerce_non_dict(self) -> None:
        coerce = cast(Callable[[Any], Any], ArtifactMetadata._coerce_href_history)
        assert coerce("plain") == "plain"
