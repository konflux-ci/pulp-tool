"""
Pull operations for downloading artifacts from Pulp.

This package provides functionality for downloading RPM packages, logs, and SBOM files
from Pulp repositories and organizing them by type and architecture. It supports
concurrent downloads, filtering by content type and architecture, and optional
re-upload to destination repositories.

Modules:
    - download: Download operations and artifact loading
    - upload: Upload operations for re-uploading artifacts
    - reporting: Pull reporting and logging utilities
"""

from .download import (
    PullDestinationSetup,
    _categorize_artifacts,
    download_artifacts_concurrently,
    load_and_validate_artifacts,
    load_artifact_metadata,
    setup_repositories_if_needed,
)
from .reporting import generate_pull_report
from .upload import upload_downloaded_files_to_pulp

__all__ = [
    "PullDestinationSetup",
    "_categorize_artifacts",
    "download_artifacts_concurrently",
    "load_artifact_metadata",
    "load_and_validate_artifacts",
    "setup_repositories_if_needed",
    "upload_downloaded_files_to_pulp",
    "generate_pull_report",
]
