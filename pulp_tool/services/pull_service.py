"""
Pull service for high-level pull operations.

This module provides a service layer that orchestrates pull operations,
abstracting the complexity of downloading and optionally re-uploading artifacts.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from ..models.artifacts import ArtifactData, ArtifactJsonResponse, PulledArtifacts
from ..models.context import PullContext
from ..models.results import PulpResultsModel

if TYPE_CHECKING:
    from ..api import DistributionClient, PulpClient
    from ..models.repository import RepositoryRefs

from ..pull import (
    PullDestinationSetup,
    download_artifacts_concurrently,
    generate_pull_report,
    load_and_validate_artifacts,
    setup_repositories_if_needed,
    upload_downloaded_files_to_pulp,
)


class PullService:
    """
    High-level service for pull operations.

    This service provides a clean interface for downloading artifacts
    and optionally re-uploading them to destination repositories.
    """

    def __init__(self) -> None:
        """Initialize the pull service."""

    def load_artifacts(self, context: PullContext, distribution_client: Optional["DistributionClient"]) -> ArtifactData:
        """
        Load and validate artifact metadata.

        Args:
            context: Pull context with artifact location
            distribution_client: Optional DistributionClient for remote URLs

        Returns:
            ArtifactData containing validated artifact metadata

        Raises:
            SystemExit: If artifacts cannot be loaded or validated
        """
        logging.info("Loading artifact metadata from: %s", context.artifact_location)
        artifact_data = load_and_validate_artifacts(context, distribution_client)
        logging.info("Successfully loaded artifact metadata")
        return artifact_data

    def download_artifacts(
        self,
        artifact_data: ArtifactData,
        distribution_client: Optional["DistributionClient"],
        context: PullContext,
        max_workers: int,
    ) -> tuple[PulledArtifacts, int, int]:
        """
        Download artifacts concurrently.

        Args:
            artifact_data: Artifact metadata
            distribution_client: DistributionClient for downloading (required)
            context: Pull context with filters
            max_workers: Maximum number of concurrent workers

        Returns:
            Tuple of (pulled_artifacts, completed_count, failed_count)
        """
        logging.info("Starting artifact download with %d workers", max_workers)
        download_result = download_artifacts_concurrently(
            artifact_data.artifacts,
            artifact_data.get_distributions(),
            distribution_client,
            max_workers,
            context.content_types,
            context.archs,
        )
        logging.info(
            "Download completed: %d succeeded, %d failed",
            download_result.completed,
            download_result.failed,
        )
        return download_result.pulled_artifacts, download_result.completed, download_result.failed

    def upload_artifacts(
        self,
        pulp_client: "PulpClient",
        pulled_artifacts: PulledArtifacts,
        context: PullContext,
        *,
        repositories: "RepositoryRefs | None" = None,
    ) -> PulpResultsModel | None:
        """
        Upload downloaded artifacts to Pulp repositories.

        Args:
            pulp_client: PulpClient instance for destination repositories
            pulled_artifacts: Downloaded artifacts to upload
            context: Pull context with configuration

        Returns:
            PulpResultsModel containing upload information, or None if upload skipped
        """
        logging.info("Uploading downloaded artifacts to Pulp repositories")
        upload_info = upload_downloaded_files_to_pulp(pulp_client, pulled_artifacts, context, repositories=repositories)
        logging.info("Upload completed: %d total artifacts uploaded", upload_info.total_uploaded)
        return upload_info

    def setup_destination_repositories(
        self,
        context: PullContext,
        artifact_json: dict[str, Any] | ArtifactJsonResponse | None = None,
    ) -> PullDestinationSetup | None:
        """
        Set up destination repositories if configuration is provided.

        Args:
            context: Pull context with configuration
            artifact_json: Optional artifact metadata

        Returns:
            PullDestinationSetup if repositories were set up, None otherwise
        """
        if not context.config:
            logging.debug("No Pulp configuration provided, skipping repository setup")
            return None

        td = context.transfer_dest
        if td is None or not isinstance(td, str) or not td.strip():
            logging.debug("No transfer destination (--transfer-dest) specified, skipping repository setup")
            return None

        logging.info("Setting up destination repositories")
        destination = setup_repositories_if_needed(context, artifact_json)
        if destination:
            logging.info("Destination repositories set up successfully")
        return destination

    def generate_report(
        self,
        pulled_artifacts: PulledArtifacts,
        completed: int,
        failed: int,
        context: PullContext,
        upload_info: PulpResultsModel | None = None,
    ) -> None:
        """
        Generate and display pull report.

        Args:
            pulled_artifacts: Downloaded artifacts
            completed: Number of successful downloads
            failed: Number of failed downloads
            context: Pull context
            upload_info: Optional upload information
        """
        generate_pull_report(pulled_artifacts, completed, failed, context, upload_info)


__all__ = ["PullService"]
