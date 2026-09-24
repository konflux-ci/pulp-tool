"""
Download operations for pulling artifacts from Pulp.

This module handles downloading artifacts, loading metadata, and setting up
repositories for pull operations.
"""

import json
import logging
import traceback
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from ..api import DistributionClient, PulpClient
from ..exceptions import PulpToolError
from ..models.artifacts import ArtifactData, ArtifactJsonResponse, DownloadTask
from ..models.context import PullContext
from ..models.repository import RepositoryRefs
from ..models.results import DownloadResult
from ..utils import PulpHelper, determine_build_id, extract_metadata_from_artifact_json
from ..utils.artifact_detection import categorize_artifacts_by_type
from ..utils.config_manager import ConfigManager


@dataclass(frozen=True, slots=True)
class PullDestinationSetup:
    """Destination Pulp client and repositories created for a pull transfer."""

    client: PulpClient
    repositories: RepositoryRefs


def _categorize_artifacts(
    artifacts: dict[str, Any],
    distros: dict[str, str],
    content_types: list[str] | None = None,
    archs: list[str] | None = None,
    *,
    embedded_urls_only: bool = True,
) -> list[DownloadTask]:
    """Categorize artifacts and prepare download information.

    Args:
        artifacts: Dictionary of artifacts (can be ArtifactMetadata or dict)
        distros: Distribution base URLs from artifact JSON (ignored for URL building when
            ``embedded_urls_only`` is True)
        content_types: Optional list of content types to filter (rpm, log, sbom)
        archs: Optional list of architectures to filter
        embedded_urls_only: When True (default), only each artifact's ``url`` field is used for download.

    Returns:
        List of DownloadTask objects with download information
    """
    # Use centralized artifact detection utility
    categorized = categorize_artifacts_by_type(
        artifacts,
        distros,
        content_types,
        archs,
        embedded_urls_only=embedded_urls_only,
    )

    # Convert to DownloadTask objects
    download_tasks = [
        DownloadTask(
            artifact_name=name,
            file_url=TypeAdapter(AnyHttpUrl).validate_python(url),
            arch=arch,
            artifact_type=artifact_type,
        )
        for name, url, arch, artifact_type in categorized
    ]

    return download_tasks


def load_artifact_metadata(artifact_location: str, distribution_client: DistributionClient | None) -> dict[str, Any]:
    """
    Load artifact metadata from either a local file or HTTP URL.

    Args:
        artifact_location: Path to local file or HTTP URL
        distribution_client: Optional DistributionClient instance for HTTP requests (required for URLs)

    Returns:
        Dictionary containing artifact metadata
    """
    if artifact_location.startswith(("http://", "https://")):
        # HTTP URL - use distribution client
        if distribution_client is None:
            raise ValueError(
                "DistributionClient (cert/key or username/password) required for remote artifact locations. "
                "Provide via config file."
            )
        logging.debug("Loading artifact metadata from URL: %s", artifact_location)
        response = distribution_client.pull_artifact(artifact_location)
        return response.json()

    # Local file path
    logging.debug("Loading artifact metadata from local file: %s", artifact_location)
    try:
        with open(artifact_location, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("Artifact file not found: %s", artifact_location)
        raise
    except json.JSONDecodeError as e:
        logging.error("Invalid JSON in artifact file %s: %s", artifact_location, e)
        raise
    except Exception as e:
        logging.error("Failed to read artifact file %s: %s", artifact_location, e)
        raise


def setup_repositories_if_needed(
    args: PullContext,
    artifact_json: dict[str, Any] | ArtifactJsonResponse | None = None,
) -> PullDestinationSetup | None:
    """
    Set up repositories using PulpClient if configuration is provided.

    Args:
        args: Pull context with command arguments
        artifact_json: Optional artifact metadata to extract build_id from

    Returns:
        PullDestinationSetup if repositories were set up, None otherwise
    """
    if not args.config:
        logging.debug("No Pulp configuration provided, skipping repository setup")
        return None

    transfer_dest = getattr(args, "transfer_dest", None)
    if transfer_dest is None or not isinstance(transfer_dest, str) or not transfer_dest.strip():
        logging.debug(
            "No transfer destination (--transfer-dest) specified, skipping repository and distribution setup",
        )
        return None

    try:
        # Initialize Pulp client - domain will be read from config file
        # Note: Pull uses the DESTINATION domain from config, not the SOURCE domain from artifact_json
        # For pull operations, add "konflux-" prefix to the domain if not already present
        config_manager = ConfigManager(args.config)
        config_manager.load()
        domain = config_manager.get("cli.domain", "")
        if domain and not domain.startswith("konflux-"):
            domain = f"konflux-{domain}"
            logging.debug("Added 'konflux-' prefix to domain for pull: %s", domain)
        elif domain:
            logging.debug("Using domain for pull (already has 'konflux-' prefix or empty): %s", domain)
        build_id = determine_build_id(args, artifact_json=artifact_json)
        client = PulpClient.create_from_config_file(
            path=args.config,
            domain=domain if domain else None,
            correlation_namespace=args.namespace or None,
            correlation_build_id=build_id or None,
        )

        # Extract parent_package from artifact_json for proper distribution base_path
        parent_package = None
        if artifact_json:
            parent_package = extract_metadata_from_artifact_json(artifact_json, "parent_package")
            logging.debug("Extracted parent_package from artifact_json: %s", parent_package)

        logging.info("Setting up repositories for pull operations: %s", build_id)
        repository_helper = PulpHelper(client, parent_package=parent_package)
        repositories = repository_helper.setup_repositories(build_id)
        logging.info("Repository setup completed for pull operations")

        return PullDestinationSetup(client=client, repositories=repositories)

    except (PulpToolError, ValueError, RuntimeError, httpx.HTTPError) as e:
        logging.warning("Failed to setup repositories: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
        logging.warning("Continuing with distribution-only mode")
        return None


def load_and_validate_artifacts(args: PullContext, distribution_client: DistributionClient | None) -> ArtifactData:
    """Load artifact metadata and validate it matches the pull artifact results model.

    The payload is validated as :class:`~pulp_tool.models.artifacts.ArtifactJsonResponse`; pull
    requires non-empty ``artifacts``, each with an ``http`` or ``https`` ``url``. Top-level
    ``distributions`` is optional.

    Args:
        args: Pull context with command arguments
        distribution_client: DistributionClient for loading metadata

    Returns:
        ArtifactData containing artifact JSON and artifacts dictionary

    Raises:
        SystemExit: If the location is missing, or validation fails
        FileNotFoundError: If the artifact path does not exist (propagated from load)
    """
    import sys

    if not args.artifact_location:
        logging.error("No artifact location provided")
        sys.exit(1)

    logging.debug("Loading artifact metadata from %s", args.artifact_location)
    artifact_json_raw = load_artifact_metadata(args.artifact_location, distribution_client)

    try:
        artifact_json_typed = ArtifactJsonResponse.model_validate(artifact_json_raw)
        artifact_json_typed.validate_for_pull()
    except (ValidationError, ValueError) as exc:
        logging.error("Artifact results JSON does not match the expected model for pull:")
        logging.error("%s", exc)
        sys.exit(1)

    artifacts_typed = dict(artifact_json_typed.artifacts)
    return ArtifactData(artifact_json=artifact_json_typed, artifacts=artifacts_typed)


def download_artifacts_concurrently(
    artifacts: dict[str, Any],
    distros: dict[str, str],
    distribution_client: DistributionClient | None,
    max_workers: int,
    content_types: list[str] | None = None,
    archs: list[str] | None = None,
    *,
    embedded_urls_only: bool = True,
) -> DownloadResult:
    """Download all artifacts concurrently using thread pool.

    Args:
        artifacts: Dictionary of artifacts to download
        distros: Dictionary of distribution URLs from artifact results (not used to build download
            URLs when ``embedded_urls_only`` is True)
        distribution_client: Optional DistributionClient for downloading (required for downloads)
        max_workers: Maximum number of concurrent workers
        content_types: Optional list of content types to filter (rpm, log, sbom)
        archs: Optional list of architectures to filter
        embedded_urls_only: When True (default for ``pulp pull``), use only per-artifact ``url``
            fields from the artifact results JSON.

    Returns:
        DownloadResult containing pulled artifacts, completed count, and failed count
    """
    import traceback
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import httpx

    from ..models.artifacts import ArtifactMetadata, PulledArtifacts

    # Prepare download tasks
    download_tasks = _categorize_artifacts(
        artifacts,
        distros,
        content_types,
        archs,
        embedded_urls_only=embedded_urls_only,
    )
    total_artifacts = len(download_tasks)

    logging.debug("Starting download of %d artifacts with %d workers", total_artifacts, max_workers)

    # Initialize artifact storage structure
    pulled_artifacts = PulledArtifacts()

    # Download artifacts concurrently
    completed = 0
    failed = 0

    if distribution_client is None:
        raise ValueError(
            "DistributionClient (cert/key or username/password) required for downloading artifacts. "
            "Provide via config file."
        )

    logging.info("Downloading %d artifact(s)", total_artifacts)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks
        future_to_artifact = {
            executor.submit(distribution_client.pull_data_async, task.to_tuple()): task.artifact_name
            for task in download_tasks
        }

        # Process completed downloads
        for future in as_completed(future_to_artifact):
            artifact_name = future_to_artifact[future]
            try:
                artifact_name, file_path = future.result()
                logging.warning("Downloading artifact: %s", artifact_name)

                # Find the original artifact info to get labels
                artifact_info = artifacts[artifact_name]

                # Extract labels (handle both ArtifactMetadata and dict)
                if isinstance(artifact_info, ArtifactMetadata):
                    labels = artifact_info.labels
                else:
                    labels = artifact_info.get("labels", {})

                # Store artifact by type using centralized detection
                from ..utils.artifact_detection import detect_artifact_type

                artifact_type = detect_artifact_type(artifact_name)
                if artifact_type == "sbom":
                    pulled_artifacts.add_sbom(artifact_name, file_path, labels)
                elif artifact_type == "log":
                    pulled_artifacts.add_log(artifact_name, file_path, labels)
                elif artifact_type == "rpm":
                    pulled_artifacts.add_rpm(artifact_name, file_path, labels)

                completed += 1

            except httpx.HTTPError as e:
                failed += 1
                logging.error("Failed to download %s: %s", artifact_name, e)
                logging.debug("Traceback: %s", traceback.format_exc())
    return DownloadResult(pulled_artifacts=pulled_artifacts, completed=completed, failed=failed)


__all__ = [
    "_categorize_artifacts",
    "download_artifacts_concurrently",
    "load_artifact_metadata",
    "load_and_validate_artifacts",
    "PullDestinationSetup",
    "setup_repositories_if_needed",
]
