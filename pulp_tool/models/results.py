"""Result models for upload and download operations."""

from pydantic import Field

from .artifacts import ArtifactMetadata, PulledArtifacts
from .base import KonfluxBaseModel

# Same model as ``pulp_results.json`` artifact entries (push and pull).
ArtifactInfo = ArtifactMetadata


class RpmUploadResult(KonfluxBaseModel):
    """
    Result from uploading RPMs and logs for a specific architecture.

    Attributes:
        uploaded_rpms: List of RPM files that were uploaded
        created_resources: List of content hrefs created from add_content task
    """

    uploaded_rpms: list[str] = Field(default_factory=list)
    created_resources: list[str] = Field(default_factory=list)


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


__all__ = [
    "RpmUploadResult",
    "DownloadResult",
    "ArtifactInfo",
]
