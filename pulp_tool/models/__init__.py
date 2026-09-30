"""
Pydantic models for pulp-tool.

This package contains all Pydantic models used in the application:
- pulp_api: Models for Pulp API responses
- base, repository, context, artifacts, results, validation, statistics: Domain models
"""

# Pulp API Response Models
from .artifacts import ArtifactFile, FileInfoModel, PulledArtifacts

# Domain Models
from .base import KonfluxBaseModel
from .context import PullContext, UploadContext, UploadFilesContext, UploadRpmContext
from .pulp_api import (
    ContentResponse,
    DistributionResponse,
    FileResponse,
    OAuthTokenResponse,
    PaginatedResponse,
    PulpBaseModel,
    RepositoryResponse,
    RpmPackageResponse,
    TaskResponse,
)
from .pulp_results import PULP_RESULTS_SCHEMA_VERSION, PulpResultsDocument
from .repository import RepositoryRefs
from .results import ArtifactInfo, DownloadResult, RpmUploadResult
from .statistics import UploadCounts
from .validation import RpmCheckResult

__all__ = [
    # Pulp API Models
    "PulpBaseModel",
    "PaginatedResponse",
    "TaskResponse",
    "RepositoryResponse",
    "DistributionResponse",
    "ContentResponse",
    "RpmPackageResponse",
    "FileResponse",
    "OAuthTokenResponse",
    # Domain Models
    "KonfluxBaseModel",
    "RepositoryRefs",
    "RpmCheckResult",
    "ArtifactFile",
    "PulledArtifacts",
    "FileInfoModel",
    "UploadCounts",
    "ArtifactInfo",
    "DownloadResult",
    "RpmUploadResult",
    "PulpResultsDocument",
    "PULP_RESULTS_SCHEMA_VERSION",
    "UploadContext",
    "UploadRpmContext",
    "UploadFilesContext",
    "PullContext",
]
