"""
Tests for validation model classes.

This test file covers validation models from pulp_tool.models.validation:
- RpmCheckResult: RPM checking operation results
- ValidationResult: Generic validation results with error tracking
- ArtifactValidationResult: Artifact validation results

Note: Other data models are tested in test_all_models.py
"""

from pulp_tool.models.validation import (
    RpmCheckResult,
    ValidationResult,
    ArtifactValidationResult,
)


class TestRpmCheckResult:
    """Test RpmCheckResult model."""

    def test_properties(self):
        """Test RpmCheckResult properties."""
        result = RpmCheckResult(
            missing_rpms=["rpm1.rpm", "rpm2.rpm"], found_artifacts=[{"checksum": "abc123"}, {"checksum": "def456"}]
        )

        assert result.missing_count == 2
        assert result.found_count == 2
        assert result.total_count == 4


class TestValidationResult:
    """Test ValidationResult model."""

    def test_properties(self):
        """Test ValidationResult properties."""
        result = ValidationResult(is_valid=False, errors=["Error 1", "Error 2"])

        assert result.error_count == 2
        assert result.has_errors is True

    def test_add_error(self):
        """Test adding errors to ValidationResult."""
        result = ValidationResult(is_valid=True, errors=[])

        assert result.is_valid is True
        assert result.has_errors is False

        result.add_error("New error")

        assert result.is_valid is False
        assert result.has_errors is True
        assert result.error_count == 1
        assert "New error" in result.errors


class TestArtifactValidationResult:
    """Test ArtifactValidationResult model."""

    def test_creation(self):
        """Test creating ArtifactValidationResult."""
        result = ArtifactValidationResult(artifact_json={"artifacts": {"test.rpm": {}}}, artifacts={"test.rpm": {}})

        assert result.artifact_json == {"artifacts": {"test.rpm": {}}}
        assert result.artifacts == {"test.rpm": {}}


class TestPulpAPIModels:
    """Test additional Pulp API models."""

    def test_repository_response_default_labels(self):
        """Test RepositoryResponse with default labels."""
        from pulp_tool.models.pulp_api import RepositoryResponse

        repo = RepositoryResponse(pulp_href="/api/v3/repositories/rpm/rpm/123/", name="test-repo")

        assert repo.pulp_labels == {}
        assert repo.name == "test-repo"

    def test_distribution_response_default_labels(self):
        """Test DistributionResponse with default labels."""
        from pulp_tool.models.pulp_api import DistributionResponse

        dist = DistributionResponse(
            pulp_href="/api/v3/distributions/rpm/rpm/123/", name="test-dist", base_path="test/dist"
        )

        assert dist.pulp_labels == {}
        assert dist.base_path == "test/dist"

    def test_task_response_models(self):
        """Test TaskResponse models."""
        from pulp_tool.models.pulp_api import TaskResponse

        task = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/content/rpm/packages/1/"]
        )

        assert task.state == "completed"
        assert len(task.created_resources) == 1
