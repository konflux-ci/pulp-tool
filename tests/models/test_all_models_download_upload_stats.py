"""Tests for download stats, results, download task models."""

import pytest
from pydantic import ValidationError

from pulp_tool.models.artifacts import (
    ArtifactFile,
    PulledArtifacts,
)
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.results import DownloadResult
from pulp_tool.models.statistics import DownloadStats, UploadCounts


class TestDownloadStats:
    """Test DownloadStats model."""

    def test_create_download_stats_defaults(self) -> None:
        """Test creating DownloadStats with defaults."""
        stats = DownloadStats()
        assert stats.pulled_artifacts == {}
        assert stats.completed == 0
        assert stats.failed == 0
        assert stats.total_attempted == 0

    def test_create_download_stats_with_values(self) -> None:
        """Test creating DownloadStats with values."""
        stats = DownloadStats(pulled_artifacts={"rpms": {}, "logs": {}}, completed=8, failed=2)
        assert stats.pulled_artifacts == {"rpms": {}, "logs": {}}
        assert stats.completed == 8
        assert stats.failed == 2
        assert stats.total_attempted == 10

    def test_download_stats_success_rate(self) -> None:
        """Test success rate calculation."""
        stats = DownloadStats(completed=8, failed=2)
        assert stats.success_rate == 80.0
        empty_stats = DownloadStats()
        assert empty_stats.success_rate == 0.0


class TestDownloadResult:
    """Test DownloadResult model."""

    def test_create_download_result_empty(self) -> None:
        """Test creating empty DownloadResult."""
        result = DownloadResult(pulled_artifacts=PulledArtifacts(), completed=0, failed=0)
        assert isinstance(result.pulled_artifacts, PulledArtifacts)
        assert result.completed == 0
        assert result.failed == 0
        assert result.total_attempted == 0
        assert result.has_failures is False

    def test_create_download_result_with_data(self) -> None:
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

    def test_create_upload_counts_defaults(self) -> None:
        """Test creating UploadCounts with defaults."""
        counts = UploadCounts()
        assert counts.rpms == 0
        assert counts.logs == 0
        assert counts.sboms == 0

    def test_create_upload_counts_with_values(self) -> None:
        """Test creating UploadCounts with values."""
        counts = UploadCounts(rpms=10, logs=5, sboms=1)
        assert counts.rpms == 10
        assert counts.logs == 5
        assert counts.sboms == 1


class TestPulpResultsDocument:
    """Test PulpResultsDocument - unified tracking and results model."""

    def test_create_pulp_results_model(self) -> None:
        """Test creating PulpResultsDocument instance."""
        from pulp_tool.models.pulp_results import PulpResultsDocument

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
        model = PulpResultsDocument(build_id="test-build-123", repositories=repositories)
        assert model.build_id == "test-build-123"
        assert isinstance(model.repositories, RepositoryRefs)
        assert model.artifacts == {}
        assert model.distributions == {}
        assert model.uploaded_counts.total == 0
        assert model.upload_errors == []

    def test_add_artifact(self) -> None:
        """Test adding artifacts to results model."""
        from pulp_tool.models.pulp_results import PulpResultsDocument

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
        model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        model.add_artifact(
            key="test.rpm",
            url="https://pulp.example.com/test.rpm",
            sha256="abc123",
            pulp_labels={"arch": "x86_64", "build_id": "test-build"},
        )
        assert model.artifact_count == 1
        assert "test.rpm" in model.artifacts
        assert model.artifacts["test.rpm"].url == "https://pulp.example.com/test.rpm"
        assert model.artifacts["test.rpm"].sha256 == "abc123"
        assert model.artifacts["test.rpm"].pulp_labels["arch"] == "x86_64"

    def test_add_distribution(self) -> None:
        """Test adding distributions to results model."""
        from pulp_tool.models.pulp_results import PulpResultsDocument

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
        model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        model.add_distribution("rpms", "https://pulp.example.com/rpms/")
        model.add_distribution("logs", "https://pulp.example.com/logs/")
        assert len(model.distributions) == 2
        assert str(model.distributions["rpms"]) == "https://pulp.example.com/rpms/"
        assert str(model.distributions["logs"]) == "https://pulp.example.com/logs/"

    def test_add_distribution_rejects_invalid_url(self) -> None:
        """Distribution base URLs must be valid http(s) URLs."""
        from pulp_tool.models.pulp_results import PulpResultsDocument

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
        model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        with pytest.raises(ValidationError):
            model.add_distribution("rpms", "not-a-valid-url")

    def test_to_canonical_dict(self) -> None:
        """Test converting model to JSON dict."""
        from pulp_tool.models.pulp_results import PulpResultsDocument

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
        model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        model.add_artifact("test.rpm", "https://pulp.example.com/test.rpm", "abc123", {"arch": "x86_64"})
        model.artifacts["test.rpm"].href = "/pulp/href/"
        model.artifacts["test.rpm"].distributions = {"rpms": "https://pulp.example.com/rpms/"}
        model.add_distribution("zebra", "https://pulp.example.com/zebra/")
        model.add_distribution("alpha", "https://pulp.example.com/alpha/")
        model.add_distribution("rpms", "https://pulp.example.com/rpms/")
        result = model.to_canonical_dict(namespace="my-ns", cluster="my-cluster")
        assert result["namespace"] == "my-ns"
        assert result["cluster"] == "my-cluster"
        assert result["artifacts"]["test.rpm"]["href"] == "/pulp/href/"
        assert result["artifacts"]["test.rpm"]["distributions"]["rpms"].startswith("https://")
        assert "artifacts" in result
        assert "distributions" in result
        assert "test.rpm" in result["artifacts"]
        assert result["artifacts"]["test.rpm"]["url"] == "https://pulp.example.com/test.rpm"
        assert list(result["distributions"].keys()) == ["alpha", "rpms", "zebra"]
        assert result["distributions"]["rpms"] == "https://pulp.example.com/rpms/"

    def test_tracking_functionality(self) -> None:
        """Test upload tracking functionality."""
        from pulp_tool.models.pulp_results import PulpResultsDocument

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
        model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        model.uploaded_counts.rpms = 5
        model.uploaded_counts.logs = 2
        model.uploaded_counts.sboms = 1
        assert model.total_uploaded == 8
        assert model.uploaded_counts.rpms == 5
        assert not model.has_errors
        model.add_error("Test error 1")
        model.add_error("Test error 2")
        assert model.has_errors
        assert model.error_count == 2
        assert "Test error 1" in model.upload_errors
