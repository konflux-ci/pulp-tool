"""Result models for upload and download operations."""

from typing import Any, List, Dict, Optional

from pydantic import Field

from .base import KonfluxBaseModel
from .artifacts import PulledArtifacts
from .repository import RepositoryRefs
from .statistics import UploadCounts


class UploadResult(KonfluxBaseModel):
    """
    Result of an upload operation.

    Attributes:
        uploaded_files: List of successfully uploaded file names
        task_id: Pulp task ID for the upload operation
        repository_href: Repository href where files were uploaded
    """

    uploaded_files: List[str] = Field(default_factory=list)
    task_id: Optional[str] = None
    repository_href: Optional[str] = None

    @property
    def total_files(self) -> int:
        """Total number of files processed."""
        return len(self.uploaded_files)


class RpmUploadResult(KonfluxBaseModel):
    """
    Result from uploading RPMs and logs for a specific architecture.

    Attributes:
        uploaded_rpms: List of RPM files that were uploaded
        created_resources: List of content hrefs created from add_content task
    """

    uploaded_rpms: List[str] = Field(default_factory=list)
    created_resources: List[str] = Field(default_factory=list)

    @property
    def upload_count(self) -> int:
        """Total number of RPMs uploaded."""
        return len(self.uploaded_rpms)

    @property
    def resource_count(self) -> int:
        """Total number of created resources."""
        return len(self.created_resources)


class DownloadResult(KonfluxBaseModel):
    """
    Result from downloading artifacts concurrently.

    Attributes:
        pulled_artifacts: Collection of downloaded artifacts
        completed: Number of successfully downloaded artifacts
        failed: Number of failed downloads
    """

    pulled_artifacts: PulledArtifacts = Field(default_factory=PulledArtifacts)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)

    @property
    def total_attempted(self) -> int:
        """Total number of download attempts."""
        return self.completed + self.failed

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage."""
        if self.total_attempted == 0:
            return 0.0
        return (self.completed / self.total_attempted) * 100

    @property
    def has_failures(self) -> bool:
        """Check if there were any failures."""
        return self.failed > 0


class ArtifactInfo(KonfluxBaseModel):
    """
    Information about a single artifact in results.

    Attributes:
        labels: Labels associated with the artifact (build_id, arch, etc.)
        url: Download URL for the artifact
        sha256: SHA256 checksum of the artifact
    """

    labels: Dict[str, str] = Field(default_factory=dict)
    url: str
    sha256: str


class PulpResultsModel(KonfluxBaseModel):
    """
    Unified model for tracking uploads and building pulp_results.json.

    This model combines upload progress tracking with results structure building.
    It can be passed around and incrementally built during the upload process.

    Attributes:
        build_id: Build identifier for the upload
        repositories: Repository references where artifacts are uploaded
        artifacts: Dictionary of artifacts (key: artifact path, value: artifact info)
        distributions: Dictionary of distribution URLs by repository type
        uploaded_counts: Count of uploaded artifacts by type
        upload_errors: List of error messages encountered during upload

    Example:
        >>> results = PulpResultsModel(build_id="build-123", repositories=repos)
        >>> results.add_artifact("test.rpm", "https://...", "sha256...", {"arch": "x86_64"})
        >>> results.add_distribution("rpms", "https://pulp.example.com/rpms/")
        >>> json_dict = results.to_json_dict()  # Get final JSON structure
    """

    # Metadata
    build_id: str
    repositories: RepositoryRefs

    # Results structure (matches pulp_results.json)
    artifacts: Dict[str, ArtifactInfo] = Field(default_factory=dict)
    distributions: Dict[str, str] = Field(default_factory=dict)

    # Progress tracking
    uploaded_counts: UploadCounts = Field(default_factory=UploadCounts)
    upload_errors: List[str] = Field(default_factory=list)

    def add_artifact(self, key: str, url: str, sha256: str, labels: Dict[str, str]) -> None:
        """
        Add an artifact to the results.

        Args:
            key: Artifact identifier (path/filename)
            url: Download URL for the artifact
            sha256: SHA256 checksum
            labels: Labels associated with the artifact
        """
        # pylint: disable=unsupported-assignment-operation  # Pydantic mutable field
        self.artifacts[key] = ArtifactInfo(labels=labels, url=url, sha256=sha256)

    def add_distribution(self, repo_type: str, url: str) -> None:
        """
        Add a distribution URL.

        Args:
            repo_type: Type of repository (rpms, logs, sbom, artifacts)
            url: Distribution base URL
        """
        # pylint: disable=unsupported-assignment-operation  # Pydantic mutable field
        self.distributions[repo_type] = url

    def add_error(self, error: str) -> None:
        """
        Add an upload error.

        Args:
            error: Error message to record
        """
        self.upload_errors.append(error)  # pylint: disable=no-member  # Pydantic field

    def to_json_dict(self) -> Dict[str, Any]:
        """
        Export artifacts and distributions only (for pulp_results.json).

        Returns:
            Dictionary containing artifacts and distributions in the format
            expected by pulp_results.json
        """
        return {
            "artifacts": {
                key: {
                    "labels": info.labels,
                    "url": info.url,
                    "sha256": info.sha256,
                }
                for key, info in self.artifacts.items()  # pylint: disable=no-member  # Pydantic field
            },
            "distributions": self.distributions,
        }

    @property
    def total_uploaded(self) -> int:
        """Total number of artifacts uploaded."""
        return self.uploaded_counts.total  # pylint: disable=no-member  # Pydantic field

    @property
    def has_errors(self) -> bool:
        """Check if there are any upload errors."""
        return len(self.upload_errors) > 0

    @property
    def error_count(self) -> int:
        """Number of upload errors."""
        return len(self.upload_errors)

    @property
    def artifact_count(self) -> int:
        """Number of artifacts in results."""
        return len(self.artifacts)


__all__ = [
    "UploadResult",
    "RpmUploadResult",
    "DownloadResult",
    "ArtifactInfo",
    "PulpResultsModel",
]
