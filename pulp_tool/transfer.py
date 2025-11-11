#!/usr/bin/env python3
"""
Transfer operations for downloading artifacts from Pulp.

This module provides functionality for downloading RPM packages, logs, and SBOM files
from Pulp repositories and organizing them by type and architecture. It supports
concurrent downloads, filtering by content type and architecture, and optional
re-upload to destination repositories.

Key Functions:
    - load_and_validate_artifacts(): Load artifact metadata from local or remote sources
    - download_artifacts_concurrently(): Download artifacts with thread pool
    - upload_downloaded_files_to_pulp(): Re-upload artifacts to destination Pulp
    - generate_transfer_report(): Create comprehensive transfer reports
    - setup_repositories_if_needed(): Set up destination repositories

The module uses reusable utility functions for iteration, logging, and reporting
to maintain clean, DRY code.
"""

# Standard library imports
import json
import logging
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
import httpx

# Local imports
from .api import PulpClient, DistributionClient
from .utils import (
    PulpHelper,
    determine_build_id,
    extract_metadata_from_artifacts,
    extract_metadata_from_artifact_json,
    RepositoryRefs,
)
from .utils.rpm_operations import upload_rpms_parallel
from .models.artifacts import (
    DownloadTask,
    PulledArtifacts,
    ArtifactData,
    ArtifactMetadata,
    ArtifactJsonResponse,
)
from .models.results import DownloadResult, PulpResultsModel
from .models.context import TransferContext

# ============================================================================
# Utility Functions
# ============================================================================


def _categorize_artifacts(
    artifacts: Dict[str, Any],
    distros: Dict[str, str],
    content_types: Optional[List[str]] = None,
    archs: Optional[List[str]] = None,
) -> List[DownloadTask]:
    """Categorize artifacts and prepare download information.

    Args:
        artifacts: Dictionary of artifacts (can be ArtifactMetadata or dict)
        distros: Dictionary of distribution URLs
        content_types: Optional list of content types to filter (rpm, log, sbom)
        archs: Optional list of architectures to filter

    Returns:
        List of DownloadTask objects with download information
    """
    download_tasks = []

    for artifact, metadata in artifacts.items():
        # Handle both ArtifactMetadata objects and raw dicts
        if isinstance(metadata, ArtifactMetadata):
            arch = metadata.arch or "noarch"
        else:
            arch = metadata.get("labels", {}).get("arch", "noarch")

        # Determine artifact type
        artifact_type = None
        file_url = ""  # Initialize to satisfy pylint
        if "sbom" in artifact:
            artifact_type = "sbom"
            file_url = f"{distros['sbom']}{artifact}"
        elif "log" in artifact:
            artifact_type = "log"
            file_url = f"{distros['logs']}{artifact}"
        elif "rpm" in artifact:
            artifact_type = "rpm"
            file_url = f"{distros['rpms']}Packages/l/{artifact}"

        # Skip if no artifact type determined
        if not artifact_type:
            continue

        # Apply content type filter
        if content_types and artifact_type not in content_types:
            logging.debug("Skipping %s: content type %s not in filter %s", artifact, artifact_type, content_types)
            continue

        # Apply architecture filter
        if archs and arch not in archs:
            logging.debug("Skipping %s: architecture %s not in filter %s", artifact, arch, archs)
            continue

        # Add to download tasks
        download_tasks.append(
            DownloadTask(artifact_name=artifact, file_url=file_url, arch=arch, artifact_type=artifact_type)
        )

    return download_tasks


def load_artifact_metadata(artifact_location: str, distribution_client: Optional[DistributionClient]) -> Dict[str, Any]:
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
            raise ValueError("DistributionClient (cert_path and key_path) required for remote artifact locations")
        logging.debug("Loading artifact metadata from URL: %s", artifact_location)
        response = distribution_client.pull_artifact(artifact_location)
        return response.json()

    # Local file path
    logging.debug("Loading artifact metadata from local file: %s", artifact_location)
    try:
        with open(artifact_location, "r", encoding="utf-8") as f:
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


# ============================================================================
# Repository Setup Functions
# ============================================================================


def setup_repositories_if_needed(args: TransferContext, artifact_json=None) -> Optional[PulpClient]:
    """
    Set up repositories using PulpClient if configuration is provided.

    Args:
        args: Transfer context with command arguments
        artifact_json: Optional artifact metadata to extract build_id from

    Returns:
        PulpClient instance if repositories were set up, None otherwise
    """
    if not args.config:
        logging.debug("No Pulp configuration provided, skipping repository setup")
        return None

    try:
        # Initialize Pulp client - domain will be read from config file
        # Note: Transfer uses the DESTINATION domain from config, not the SOURCE domain from artifact_json
        client = PulpClient.create_from_config_file(path=args.config)

        # Extract parent_package from artifact_json for proper distribution base_path
        parent_package = None
        if artifact_json:
            parent_package = extract_metadata_from_artifact_json(artifact_json, "parent_package")
            logging.debug("Extracted parent_package from artifact_json: %s", parent_package)

        # Determine build_id using consolidated function
        build_id = determine_build_id(args, artifact_json=artifact_json)

        logging.info("Setting up repositories for pull operations: %s", build_id)
        repository_helper = PulpHelper(
            client, None, parent_package=parent_package
        )  # TODO: Add cert_config support to pulp-transfer
        repository_helper.setup_repositories(build_id)
        logging.info("Repository setup completed for pull operations")

        return client

    except (ValueError, RuntimeError, httpx.HTTPError) as e:
        logging.warning("Failed to setup repositories: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
        logging.warning("Continuing with distribution-only mode")
        return None


# ============================================================================
# Upload Functions
# ============================================================================


def _upload_sboms_and_logs(
    pulp_client: PulpClient,
    pulled_artifacts: PulledArtifacts,
    repositories: RepositoryRefs,
    upload_info: PulpResultsModel,
) -> None:
    """Upload SBOM and log files to their respective repositories.

    Args:
        pulp_client: PulpClient instance for API interactions
        pulled_artifacts: Downloaded artifacts organized by type
        repositories: Repository information
        upload_info: Upload tracking dictionary to update
    """
    # Upload SBOMs
    if pulled_artifacts.sboms:
        sbom_items = list(pulled_artifacts.sboms.items())
        upload_count = 0
        errors = []

        logging.info("Uploading %d SBOM file(s)", len(sbom_items))
        for name, artifact in sbom_items:
            logging.warning("Uploading SBOM: %s", name)
            try:
                pulp_client.create_file_content(
                    repositories.sbom_prn,
                    artifact.file,
                    build_id=artifact.labels.get("build_id", ""),
                    pulp_label=artifact.labels,
                    filename=name,
                )
                upload_count += 1
            except Exception as e:
                errors.append(f"SBOM {name}: {e}")
                logging.error("Failed to upload SBOM %s: %s", name, e)

        upload_info.uploaded_counts.sboms = upload_count
        upload_info.upload_errors = upload_info.upload_errors + errors

    # Upload logs
    if pulled_artifacts.logs:
        log_items = list(pulled_artifacts.logs.items())
        upload_count = 0
        errors = []

        logging.info("Uploading %d log file(s)", len(log_items))
        for name, artifact in log_items:
            logging.warning("Uploading log: %s", name)
            try:
                # Extract arch from labels for relative path construction
                arch = artifact.labels.get("arch")
                pulp_client.create_file_content(
                    repositories.logs_prn,
                    artifact.file,
                    build_id=artifact.labels.get("build_id", ""),
                    pulp_label=artifact.labels,
                    filename=name,
                    arch=arch,
                )
                upload_count += 1
            except Exception as e:
                errors.append(f"log {name}: {e}")
                logging.error("Failed to upload log %s: %s", name, e)

        upload_info.uploaded_counts.logs = upload_count
        upload_info.upload_errors = upload_info.upload_errors + errors


def _upload_rpms_to_repository(
    pulp_client: PulpClient,
    pulled_artifacts: PulledArtifacts,
    repositories: RepositoryRefs,
    upload_info: PulpResultsModel,
) -> None:
    """Upload RPM files to the RPM repository.

    Args:
        pulp_client: PulpClient instance for API interactions
        pulled_artifacts: Downloaded artifacts organized by type
        repositories: Repository information
        upload_info: Upload tracking dictionary to update
    """
    if not pulled_artifacts.rpms:
        return

    # Prepare RPM upload information - each RPM has its own labels and arch
    rpm_infos = [
        (artifact_info.file, artifact_info.labels, artifact_info.arch or "noarch")
        for artifact_info in pulled_artifacts.rpms.values()
    ]

    logging.info("Uploading %d RPM file(s)", len(rpm_infos))

    # Upload all RPMs in parallel using the consolidated function
    rpm_artifacts = upload_rpms_parallel(pulp_client, rpm_infos)

    # Add all successfully uploaded RPM artifacts to the repository
    if rpm_artifacts:
        logging.debug("Adding %d RPM artifacts to repository", len(rpm_artifacts))
        try:
            add_task = pulp_client.add_content(repositories.rpms_href, rpm_artifacts)
            pulp_client.wait_for_finished_task(add_task.pulp_href)
            upload_info.uploaded_counts.rpms = len(rpm_artifacts)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            logging.error("Failed to add RPMs to repository: %s", e)
            logging.error("Traceback: %s", traceback.format_exc())
            upload_info.add_error(f"RPM repository addition: {e}")


def upload_downloaded_files_to_pulp(
    pulp_client: PulpClient, pulled_artifacts: PulledArtifacts, args: TransferContext
) -> PulpResultsModel:
    """
    Upload downloaded files to the appropriate Pulp repositories.

    Args:
        pulp_client: PulpClient instance for API interactions
        pulled_artifacts: Dictionary containing downloaded artifacts organized by type
        args: Transfer context with command arguments

    Returns:
        PulpResultsModel containing upload information including repository details
    """
    # Extract parent_package from artifacts for proper distribution base_path
    parent_package = extract_metadata_from_artifacts(pulled_artifacts, "parent_package")
    logging.debug("Extracted parent_package from artifacts: %s", parent_package)

    # Initialize PulpHelper to get repository information
    helper = PulpHelper(
        pulp_client, None, parent_package=parent_package
    )  # TODO: Add cert_config support to pulp-transfer

    # Determine build ID and setup repositories
    build_id = determine_build_id(args, pulled_artifacts=pulled_artifacts)  # type: ignore[arg-type]
    repositories = helper.setup_repositories(build_id)

    # Initialize upload tracking with unified model
    upload_info = PulpResultsModel(build_id=build_id, repositories=repositories)

    # Upload different artifact types
    _upload_sboms_and_logs(pulp_client, pulled_artifacts, repositories, upload_info)
    _upload_rpms_to_repository(pulp_client, pulled_artifacts, repositories, upload_info)

    # Log upload summary at WARNING level so it's always visible
    _log_upload_summary(upload_info)

    return upload_info


# ============================================================================
# Reporting Functions
# ============================================================================


def _log_upload_summary(upload_info: PulpResultsModel) -> None:
    """Log upload summary at WARNING level so it's always visible.

    Args:
        upload_info: Upload tracking model containing counts and repositories
    """
    if upload_info.total_uploaded == 0:
        logging.warning("Upload complete: No files uploaded to Pulp")
        return

    # Build summary of what was uploaded
    parts = []
    if upload_info.uploaded_counts.rpms > 0:
        parts.append(f"{upload_info.uploaded_counts.rpms} RPM{'s' if upload_info.uploaded_counts.rpms != 1 else ''}")
    if upload_info.uploaded_counts.sboms > 0:
        parts.append(f"{upload_info.uploaded_counts.sboms} SBOM{'s' if upload_info.uploaded_counts.sboms != 1 else ''}")
    if upload_info.uploaded_counts.logs > 0:
        parts.append(f"{upload_info.uploaded_counts.logs} log{'s' if upload_info.uploaded_counts.logs != 1 else ''}")

    # Get domain from repository PRN (format: domain:namespace/repo)
    domain = "unknown"
    if upload_info.repositories and upload_info.repositories.rpms_prn:
        # Extract domain from PRN like "domain:namespace/repo"
        prn_parts = upload_info.repositories.rpms_prn.split(":")
        if len(prn_parts) > 1:
            domain = prn_parts[0]

    logging.warning(
        "Upload complete: %s uploaded to Pulp domain '%s' for build '%s'",
        ", ".join(parts),
        domain,
        upload_info.build_id,
    )


def _log_transfer_summary(completed: int, failed: int, args: TransferContext) -> None:
    """Log transfer summary and source information."""
    total = completed + failed
    if failed > 0:
        logging.info("Transfer: %d/%d successful (%d failed)", completed, total, failed)
    else:
        logging.info("Transfer: %d artifacts successful", completed)

    logging.debug("Source: %s", args.artifact_location)
    logging.debug("Max workers: %d", args.max_workers)


def _extract_artifact_info(artifact_data) -> Tuple[str, Dict[str, str]]:
    """
    Extract file path and labels from artifact data.

    Args:
        artifact_data: Artifact data (model or dict)

    Returns:
        Tuple of (file_path, labels)
    """
    if hasattr(artifact_data, "file"):
        file_path = artifact_data.file
        labels = artifact_data.labels if hasattr(artifact_data, "labels") else {}
    else:
        file_path = artifact_data["file"]
        labels = artifact_data.get("labels", {})

    return file_path, labels


def _get_file_size_safe(file_path: str) -> Tuple[int, str]:
    """
    Get file size with error handling.

    Args:
        file_path: Path to file

    Returns:
        Tuple of (size_bytes, size_string)
    """
    try:
        file_size = os.path.getsize(file_path)
        size_str = _format_file_size(file_size)
        return file_size, size_str
    except OSError:
        return 0, "Unknown size"


def _log_single_artifact(artifact_name: str, artifact_data) -> int:
    """
    Log information for a single artifact and return file size.

    Args:
        artifact_name: Name of the artifact
        artifact_data: Artifact data (model or dict)

    Returns:
        File size in bytes
    """
    file_path, labels = _extract_artifact_info(artifact_data)
    file_size, size_str = _get_file_size_safe(file_path)

    # Extract key information from labels
    build_id = labels.get("build_id", "Unknown")
    arch = labels.get("arch", "Unknown")
    namespace = labels.get("namespace", "Unknown")

    logging.debug("    - %s", artifact_name)
    logging.debug("      Location: %s", file_path)
    logging.debug("      Size: %s", size_str)
    logging.debug("      Build ID: %s", build_id)
    logging.debug("      Architecture: %s", arch)
    logging.debug("      Namespace: %s", namespace)

    return file_size


def _calculate_artifact_totals(pulled_artifacts: PulledArtifacts) -> Tuple[int, int]:
    """
    Calculate total file count and size for all artifacts.

    Args:
        pulled_artifacts: Downloaded artifacts

    Returns:
        Tuple of (total_files, total_size_bytes)
    """
    total_files = 0
    total_size = 0

    # Import iteration utility
    from .utils.iteration_utils import iterate_all_artifacts

    # Calculate totals using iteration utility
    for _, artifact_name, artifact_data in iterate_all_artifacts(pulled_artifacts):
        file_size = _log_single_artifact(artifact_name, artifact_data)
        total_files += 1
        total_size += file_size

    return total_files, total_size


def _format_download_summary(pulled_artifacts: PulledArtifacts, total_size: int) -> str:
    """
    Format download summary message.

    Args:
        pulled_artifacts: Downloaded artifacts
        total_size: Total size in bytes

    Returns:
        Formatted summary string
    """
    # Import logging utility
    from .utils.logging_utils import format_artifact_counts
    from .utils.iteration_utils import count_artifacts

    counts = count_artifacts(pulled_artifacts)
    counts_str = format_artifact_counts(counts)

    if counts_str == "No artifacts":
        return "Downloaded: No files"

    return f"Downloaded: {counts_str} ({_format_file_size(total_size)})"


def _log_artifacts_downloaded(pulled_artifacts: PulledArtifacts) -> Tuple[int, int]:
    """
    Log breakdown of downloaded artifacts and return totals.

    Args:
        pulled_artifacts: Downloaded artifacts

    Returns:
        Tuple of (total_files, total_size)
    """
    total_files, total_size = _calculate_artifact_totals(pulled_artifacts)
    summary_message = _format_download_summary(pulled_artifacts, total_size)
    logging.info(summary_message)

    return total_files, total_size


def _extract_storage_locations(pulled_artifacts: PulledArtifacts) -> set:
    """
    Extract unique storage locations from artifacts.

    Args:
        pulled_artifacts: Downloaded artifacts

    Returns:
        Set of unique directory paths
    """
    from .utils.iteration_utils import iterate_all_artifacts

    storage_locations = set()
    for _, _, artifact_data in iterate_all_artifacts(pulled_artifacts):
        file_path = artifact_data.file
        storage_dir = os.path.dirname(file_path)
        storage_locations.add(storage_dir)

    return storage_locations


def _log_storage_summary(total_files: int, pulled_artifacts: PulledArtifacts) -> None:
    """
    Log storage summary and locations.

    Args:
        total_files: Number of total files
        pulled_artifacts: Pulled artifacts to extract storage locations from
    """
    if total_files == 0:
        return

    storage_locations = _extract_storage_locations(pulled_artifacts)

    logging.debug("Storage locations:")
    for location in sorted(storage_locations):
        logging.debug("  - %s", location)


def _log_pulp_upload_info(upload_info: Optional[PulpResultsModel]) -> None:
    """Log Pulp upload information."""
    if upload_info:
        # Repository information (DEBUG)
        repositories = upload_info.repositories
        if repositories:
            logging.debug("Repositories:")
            logging.debug("  - RPMs: %s", repositories.rpms_prn)
            logging.debug("  - Logs: %s", repositories.logs_prn)
            logging.debug("  - SBOMs: %s", repositories.sbom_prn)

        # Upload counts (concise)
        if upload_info.total_uploaded > 0:
            parts = []
            if upload_info.uploaded_counts.sboms > 0:
                sbom_count = upload_info.uploaded_counts.sboms
                parts.append(f"{sbom_count} SBOM{'s' if sbom_count != 1 else ''}")
            if upload_info.uploaded_counts.logs > 0:
                log_count = upload_info.uploaded_counts.logs
                parts.append(f"{log_count} log{'s' if log_count != 1 else ''}")
            if upload_info.uploaded_counts.rpms > 0:
                rpm_count = upload_info.uploaded_counts.rpms
                parts.append(f"{rpm_count} RPM{'s' if rpm_count != 1 else ''}")

            logging.info("Uploaded to Pulp (build: %s): %s", upload_info.build_id, ", ".join(parts))
        else:
            logging.info("No files uploaded to Pulp")

        # Upload errors
        if upload_info.has_errors:
            logging.warning("Upload errors (%d):", len(upload_info.upload_errors))
            for error in upload_info.upload_errors:
                logging.warning("  - %s", error)


def _log_build_information(pulled_artifacts: PulledArtifacts) -> None:
    """Log build information summary."""
    # Use the model's helper methods for cleaner code
    build_ids = pulled_artifacts.get_all_build_ids()
    architectures = pulled_artifacts.get_all_architectures()
    namespaces = pulled_artifacts.get_all_namespaces()

    if build_ids:
        logging.debug("Build IDs: %s", ", ".join(sorted(build_ids)))
    if architectures:
        logging.debug("Architectures: %s", ", ".join(sorted(architectures)))
    if namespaces:
        logging.debug("Namespaces: %s", ", ".join(sorted(namespaces)))


def generate_transfer_report(
    pulled_artifacts: PulledArtifacts,
    completed: int,
    failed: int,
    args: TransferContext,
    upload_info: Optional[PulpResultsModel] = None,
) -> None:
    """
    Generate and display a comprehensive report of what was transferred and where it was stored.

    Args:
        pulled_artifacts: Dictionary containing all pulled artifacts organized by type
        completed: Number of successfully downloaded artifacts
        failed: Number of failed downloads
        args: Transfer context with command arguments
        upload_info: Optional dictionary containing upload information from Pulp
    """
    _log_transfer_summary(completed, failed, args)
    total_files, _ = _log_artifacts_downloaded(pulled_artifacts)
    _log_storage_summary(total_files, pulled_artifacts)
    _log_pulp_upload_info(upload_info)
    _log_build_information(pulled_artifacts)

    logging.info("Transfer completed successfully")


def _format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted size string
    """
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes = size_bytes / 1024.0  # type: ignore[assignment]
        i += 1

    return f"{size_bytes:.1f} {size_names[i]}"


# ============================================================================
# Main Functions
# ============================================================================


def load_and_validate_artifacts(
    args: TransferContext, distribution_client: Optional[DistributionClient]
) -> ArtifactData:
    """Load artifact metadata and validate it contains artifacts.

    Args:
        args: Transfer context with command arguments
        distribution_client: DistributionClient for loading metadata

    Returns:
        ArtifactData containing artifact JSON and artifacts dictionary

    Raises:
        SystemExit: If no artifacts are found
    """
    if not args.artifact_location:
        logging.error("No artifact location provided")
        sys.exit(1)

    logging.debug("Loading artifact metadata from %s", args.artifact_location)
    artifact_json_raw = load_artifact_metadata(args.artifact_location, distribution_client)

    artifacts_raw = artifact_json_raw.get("artifacts", {})
    if not artifacts_raw:
        logging.error("No artifacts found in the artifact metadata")
        logging.error("The artifact metadata file must contain an 'artifacts' section with at least one artifact")
        sys.exit(1)

    # Convert raw dictionaries to typed models
    artifacts_typed = {name: ArtifactMetadata(**metadata) for name, metadata in artifacts_raw.items()}

    artifact_json_typed = ArtifactJsonResponse(
        artifacts=artifacts_typed, distributions=artifact_json_raw.get("distributions", {})
    )

    return ArtifactData(artifact_json=artifact_json_typed, artifacts=artifacts_typed)


def download_artifacts_concurrently(
    artifacts: Dict[str, Any],
    distros: Dict[str, str],
    distribution_client: Optional[DistributionClient],
    max_workers: int,
    content_types: Optional[List[str]] = None,
    archs: Optional[List[str]] = None,
) -> DownloadResult:
    """Download all artifacts concurrently using thread pool.

    Args:
        artifacts: Dictionary of artifacts to download
        distros: Dictionary of distribution URLs
        distribution_client: Optional DistributionClient for downloading (required for downloads)
        max_workers: Maximum number of concurrent workers
        content_types: Optional list of content types to filter (rpm, log, sbom)
        archs: Optional list of architectures to filter

    Returns:
        DownloadResult containing pulled artifacts, completed count, and failed count
    """
    # Prepare download tasks
    download_tasks = _categorize_artifacts(artifacts, distros, content_types, archs)
    total_artifacts = len(download_tasks)

    logging.debug("Starting download of %d artifacts with %d workers", total_artifacts, max_workers)

    # Initialize artifact storage structure
    pulled_artifacts = PulledArtifacts()

    # Download artifacts concurrently
    completed = 0
    failed = 0

    if distribution_client is None:
        raise ValueError("DistributionClient (cert_path and key_path) required for downloading artifacts")

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

                # Handle both ArtifactMetadata objects and raw dicts
                if isinstance(artifact_info, ArtifactMetadata):
                    labels = artifact_info.labels
                else:
                    labels = artifact_info.get("labels", {})

                # Determine artifact type and store
                if "sbom" in artifact_name:
                    pulled_artifacts.add_sbom(artifact_name, file_path, labels)
                elif "log" in artifact_name:
                    pulled_artifacts.add_log(artifact_name, file_path, labels)
                elif "rpm" in artifact_name:
                    pulled_artifacts.add_rpm(artifact_name, file_path, labels)

                completed += 1

            except httpx.HTTPError as e:
                failed += 1
                logging.error("Failed to download %s: %s", artifact_name, e)
                logging.debug("Traceback: %s", traceback.format_exc())
    return DownloadResult(pulled_artifacts=pulled_artifacts, completed=completed, failed=failed)
