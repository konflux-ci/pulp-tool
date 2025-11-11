"""Statistics and tracking models."""

from typing import List, Dict

from pydantic import Field

from .base import KonfluxBaseModel


class UploadStats(KonfluxBaseModel):
    """
    Statistics for artifact uploads.

    Attributes:
        existing_count: Number of artifacts that already existed
        uploaded_files: List of file names that were uploaded
    """

    existing_count: int = Field(default=0, ge=0)
    uploaded_files: List[str] = Field(default_factory=list)

    @property
    def uploaded_count(self) -> int:
        """Number of files that were uploaded."""
        return len(self.uploaded_files)

    @property
    def total_count(self) -> int:
        """Total number of files processed."""
        return self.existing_count + self.uploaded_count


class FileSizeStats(KonfluxBaseModel):
    """
    File count and size statistics.

    Attributes:
        file_count: Number of files
        total_size: Total size in bytes
    """

    file_count: int = Field(default=0, ge=0)
    total_size: int = Field(default=0, ge=0)

    @property
    def average_size(self) -> float:
        """Average file size in bytes."""
        if self.file_count == 0:
            return 0.0
        return self.total_size / self.file_count

    @property
    def size_mb(self) -> float:
        """Total size in megabytes."""
        return self.total_size / (1024 * 1024)

    @property
    def size_gb(self) -> float:
        """Total size in gigabytes."""
        return self.total_size / (1024 * 1024 * 1024)


class DownloadStats(KonfluxBaseModel):
    """
    Statistics from downloading artifacts.

    Attributes:
        pulled_artifacts: Dictionary of downloaded artifacts by type (rpms, logs, sboms)
        completed: Number of successfully downloaded artifacts
        failed: Number of failed downloads
    """

    pulled_artifacts: Dict[str, Dict] = Field(default_factory=dict)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)

    @property
    def total_attempted(self) -> int:
        """Total number of download attempts."""
        return self.completed + self.failed

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage (0-100)."""
        if self.total_attempted == 0:
            return 0.0
        return (self.completed / self.total_attempted) * 100


class UploadCounts(KonfluxBaseModel):
    """
    Count of uploaded artifacts by type.

    Attributes:
        sboms: Number of SBOM files uploaded
        logs: Number of log files uploaded
        rpms: Number of RPM files uploaded
    """

    sboms: int = Field(default=0, ge=0)
    logs: int = Field(default=0, ge=0)
    rpms: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        """Total number of uploaded artifacts."""
        return self.sboms + self.logs + self.rpms


__all__ = [
    "UploadStats",
    "FileSizeStats",
    "DownloadStats",
    "UploadCounts",
]
