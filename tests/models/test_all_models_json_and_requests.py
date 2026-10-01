"""Tests for JSON artifact models and API requests."""

import pytest
from pydantic import ValidationError

from pulp_tool.models.artifacts import (
    ArtifactData,
    ArtifactMetadata,
)
from pulp_tool.models.context import PullContext, UploadContext
from pulp_tool.models.pulp_api import DistributionRequest, RepositoryRequest
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.statistics import UploadCounts


class TestPulpResultsDocumentPullLoad:
    """``PulpResultsDocument`` as loaded for ``pulp pull`` (optional ``distributions``)."""

    def test_valid_json_and_artifact_data_roundtrip(self) -> None:
        """Valid JSON validates, passes pull checks, and builds ArtifactData."""
        aj = PulpResultsDocument.model_validate(
            {
                "artifacts": {
                    "x.rpm": {
                        "pulp_labels": {"build_id": "b1", "arch": "x86_64"},
                        "url": "https://pulp.example/content/x.rpm",
                        "sha256": "ab" * 32,
                    }
                },
                "distributions": {"rpms": "https://pulp.example/rpms/"},
            }
        )
        aj.validate_for_pull()
        data = ArtifactData(artifact_json=aj, artifacts=dict(aj.artifacts))
        assert data.artifacts["x.rpm"].url == "https://pulp.example/content/x.rpm"
        assert data.artifacts["x.rpm"].sha256 == "ab" * 32
        assert data.artifact_json.distributions.get("rpms") == "https://pulp.example/rpms/"

    def test_omitted_distributions_optional(self) -> None:
        aj = PulpResultsDocument.model_validate(
            {
                "artifacts": {
                    "x.rpm": {"pulp_labels": {}, "url": "https://pulp.example/x.rpm", "sha256": "cd" * 32},
                },
            }
        )
        assert aj.distributions == {}
        aj.validate_for_pull()

    def test_empty_artifacts_rejected_on_validate_for_pull(self) -> None:
        aj = PulpResultsDocument.model_validate({"artifacts": {}})
        with pytest.raises(ValueError, match="at least one entry"):
            aj.validate_for_pull()

    def test_missing_url_rejected_on_validate_for_pull(self) -> None:
        aj = PulpResultsDocument.model_validate({"artifacts": {"a.rpm": {"pulp_labels": {}, "sha256": "c" * 64}}})
        with pytest.raises(ValueError, match="non-empty http"):
            aj.validate_for_pull()

    def test_empty_url_rejected_on_validate_for_pull(self) -> None:
        aj = PulpResultsDocument.model_validate({"artifacts": {"a.rpm": {"pulp_labels": {}, "url": "   "}}})
        with pytest.raises(ValueError, match="non-empty http"):
            aj.validate_for_pull()

    def test_sha256_none_and_whitespace_normalized_at_parse(self) -> None:
        aj = PulpResultsDocument.model_validate(
            {
                "artifacts": {
                    "a.rpm": {"pulp_labels": {}, "url": "https://x/a.rpm", "sha256": None},
                    "b.rpm": {"pulp_labels": {}, "url": "https://x/b.rpm", "sha256": "   "},
                }
            }
        )
        assert aj.artifacts["a.rpm"].sha256 is None
        assert aj.artifacts["b.rpm"].sha256 is None

    def test_missing_sha256_rejected_on_validate_for_pull(self) -> None:
        aj = PulpResultsDocument.model_validate(
            {"artifacts": {"a.rpm": {"pulp_labels": {}, "url": "https://x/a.rpm"}}},
        )
        with pytest.raises(ValueError, match="must include sha256"):
            aj.validate_for_pull()

    def test_artifact_metadata_properties(self) -> None:
        meta = ArtifactMetadata.model_validate(
            {"pulp_labels": {"build_id": "b", "namespace": "ns", "arch": "x86_64", "parent_package": "pkg"}}
        )
        assert meta.build_id == "b"
        assert meta.namespace == "ns"
        assert meta.arch == "x86_64"
        assert meta.parent_package == "pkg"

    def test_normalize_legacy_labels_strips_oci_fields(self) -> None:
        aj = PulpResultsDocument.from_raw(
            {
                "oci_manifest": "quay.io/r@sha256:abcd",
                "artifacts": {
                    "x.rpm": {
                        "pulp_labels": {},
                        "url": "https://pulp.example/content/x.rpm",
                        "sha256": "ab" * 32,
                    }
                },
            }
        )
        assert "oci_manifest" not in aj._mutable_dict()
        aj.validate_for_pull()

    def test_extra_top_level_field_ignored(self) -> None:
        aj = PulpResultsDocument.model_validate(
            {"artifacts": {"a.rpm": {"url": "https://x/a.rpm"}}, "parent_package": "legacy"}
        )
        assert "a.rpm" in aj.artifacts

    def test_non_http_url_rejected_on_validate_for_pull(self) -> None:
        aj = PulpResultsDocument.model_validate(
            {"artifacts": {"a.rpm": {"pulp_labels": {}, "url": "relative/path.rpm"}}}
        )
        with pytest.raises(ValueError, match="http or https URL"):
            aj.validate_for_pull()

    def test_invalid_distribution_base_url_rejected_at_parse(self) -> None:
        """Invalid distribution URLs are kept as strings (canonical document uses plain URLs)."""
        aj = PulpResultsDocument.model_validate(
            {
                "artifacts": {"a.rpm": {"pulp_labels": {}, "url": "https://x/y.rpm", "sha256": "a" * 64}},
                "distributions": {"rpms": "not-a-valid-url"},
            }
        )
        assert aj.distributions["rpms"] == "not-a-valid-url"

    def test_entry_ignores_unknown_artifact_keys(self) -> None:
        entry = ArtifactMetadata.model_validate({"pulp_labels": {}, "url": "https://x/y.rpm", "future_field": "ok"})
        assert entry.url == "https://x/y.rpm"


class TestPulpResultsDocument:
    """Test PulpResultsDocument model."""

    def test_create_artifact_json_response_empty(self) -> None:
        """Test creating empty PulpResultsDocument."""
        response = PulpResultsDocument()
        assert response.artifacts == {}
        assert response.distributions == {}

    def test_create_artifact_json_response_with_data(self) -> None:
        """Test creating PulpResultsDocument with data."""
        response = PulpResultsDocument(
            artifacts={
                "test.rpm": ArtifactMetadata(pulp_labels={"build_id": "test-123", "arch": "x86_64"}),
                "test2.rpm": ArtifactMetadata(pulp_labels={"build_id": "test-123", "arch": "aarch64"}),
            },
            distributions={
                "rpms": "https://pulp.example.com/rpms/",
                "logs": "https://pulp.example.com/logs/",
                "sbom": "https://pulp.example.com/sbom/",
            },
        )
        assert len(response.artifacts) == 2
        dists = response.distributions
        assert len(dists) == 3
        assert "test.rpm" in response.artifacts
        assert dists["rpms"] == "https://pulp.example.com/rpms/"

    def test_artifact_json_response_artifact_count(self) -> None:
        """Test artifact_count property."""
        response = PulpResultsDocument(
            artifacts={
                "test1.rpm": ArtifactMetadata(pulp_labels={}),
                "test2.rpm": ArtifactMetadata(pulp_labels={}),
                "test3.rpm": ArtifactMetadata(pulp_labels={}),
            }
        )
        assert response.artifact_count == 3

    def test_artifact_json_response_has_distributions(self) -> None:
        """Test has_distributions property."""
        response_empty = PulpResultsDocument()
        assert response_empty.has_distributions is False
        response_with_dists = PulpResultsDocument(distributions={"rpms": "https://example.com/rpms/"})
        assert response_with_dists.has_distributions is True

    def test_artifact_json_response_distribution_urls(self) -> None:
        """Test distribution URL properties."""
        response = PulpResultsDocument(
            distributions={
                "rpms": "https://pulp.example.com/rpms/",
                "logs": "https://pulp.example.com/logs/",
                "sbom": "https://pulp.example.com/sbom/",
            }
        )
        assert response.rpms_distribution_url == "https://pulp.example.com/rpms/"
        assert response.logs_distribution_url == "https://pulp.example.com/logs/"
        assert response.sbom_distribution_url == "https://pulp.example.com/sbom/"

    def test_artifact_json_response_distribution_urls_missing(self) -> None:
        """Test distribution URL properties when missing."""
        response = PulpResultsDocument()
        assert response.rpms_distribution_url is None
        assert response.logs_distribution_url is None
        assert response.sbom_distribution_url is None

    def test_artifact_json_response_get_artifact(self) -> None:
        """Test get_artifact method."""
        metadata = ArtifactMetadata(pulp_labels={"build_id": "test-123"})
        response = PulpResultsDocument(artifacts={"test.rpm": metadata})
        retrieved = response.get_artifact("test.rpm")
        assert retrieved is not None
        assert retrieved.build_id == "test-123"
        missing = response.get_artifact("nonexistent.rpm")
        assert missing is None


class TestArtifactData:
    """Test ArtifactData model."""

    def test_create_artifact_data_empty(self) -> None:
        """Test creating empty ArtifactData."""
        data = ArtifactData()
        assert isinstance(data.artifact_json, PulpResultsDocument)
        assert data.artifacts == {}

    def test_create_artifact_data_with_data(self) -> None:
        """Test creating ArtifactData with data."""
        artifact_json = PulpResultsDocument(
            artifacts={"test.rpm": ArtifactMetadata(pulp_labels={"build_id": "test-123"})},
            distributions={"rpms": "https://pulp.example.com/rpms/"},
        )
        data = ArtifactData(
            artifact_json=artifact_json, artifacts={"test.rpm": ArtifactMetadata(pulp_labels={"build_id": "test-123"})}
        )
        assert isinstance(data.artifact_json, PulpResultsDocument)
        assert len(data.artifacts) == 1
        assert "test.rpm" in data.artifacts

    def test_artifact_data_artifact_count(self) -> None:
        """Test artifact_count property."""
        data = ArtifactData(
            artifacts={"test1.rpm": ArtifactMetadata(pulp_labels={}), "test2.rpm": ArtifactMetadata(pulp_labels={})}
        )
        assert data.artifact_count == 2

    def test_artifact_data_has_distributions(self) -> None:
        """Test has_distributions property."""
        data_without = ArtifactData()
        assert data_without.has_distributions is False
        data_with = ArtifactData(artifact_json=PulpResultsDocument(distributions={"rpms": "https://example.com/rpms/"}))
        assert data_with.has_distributions is True

    def test_artifact_data_get_distributions(self) -> None:
        """Test get_distributions method."""
        data = ArtifactData(
            artifact_json=PulpResultsDocument(
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

    def test_artifact_data_get_distributions_when_none(self) -> None:
        """get_distributions returns empty dict when JSON omitted distributions."""
        data = ArtifactData(artifact_json=PulpResultsDocument(artifacts={}))
        assert data.get_distributions() == {}


class TestModelValidation:
    """Test Pydantic validation features."""

    def test_type_validation(self) -> None:
        """Test that type validation works."""
        with pytest.raises(ValidationError):
            UploadCounts(rpms="not an integer")

    def test_required_fields_validation(self) -> None:
        """Test that required fields are enforced."""
        with pytest.raises(ValidationError):
            UploadContext(build_id="test")

    def test_default_values(self) -> None:
        """Test that default values work correctly."""
        context = PullContext(artifact_location="test", key_path="/path/to/key.pem")
        assert context.max_workers == 10
        assert context.debug == 0

    def test_nested_model_validation(self) -> None:
        """Test that nested models are validated."""
        from pulp_tool.models.pulp_results import PulpResultsDocument

        with pytest.raises(ValidationError):
            PulpResultsDocument(build_id="test", repositories="not a RepositoryRefs object")


class TestRepositoryRequest:
    """Test RepositoryRequest validation errors"""

    def test_empty_name_error(self) -> None:
        """Test that empty(only white space) name raises validation error"""
        with pytest.raises(ValueError, match="Invalid repository name"):
            RepositoryRequest(name=" ")


class TestDistributionRequest:
    """Test DistributionRequest validation errors"""

    def test_empty_name_error(self) -> None:
        """Test that empty(only white space) name raises validation error"""
        with pytest.raises(ValueError, match="Invalid distribution name"):
            DistributionRequest(name=" ", base_path="test")

    def test_empty_base_path_error(self) -> None:
        """Test that empty(only white space) base_path raises validation error"""
        with pytest.raises(ValueError, match="Invalid distribution base_path"):
            DistributionRequest(name="test", base_path=" ")
