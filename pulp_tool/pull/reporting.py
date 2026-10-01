"""
Reporting and logging utilities for pull operations.

This module provides comprehensive reporting and logging functions for
pull operations including download summaries, upload information,
and build metadata.
"""

import logging
import os
from typing import Any

from ..models.artifacts import ArtifactFile, ArtifactMetadata, PulledArtifacts
from ..models.context import PullContext
from ..models.pulp_results import PulpResultsDocument


def _log_upload_summary(upload_info: PulpResultsDocument) -> None:
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


def _log_pull_summary(completed: int, failed: int, args: PullContext) -> None:
    """Log pull summary and source information."""
    total = completed + failed
    if failed > 0:
        logging.info("Pull: %d/%d successful (%d failed)", completed, total, failed)
    else:
        logging.info("Pull: %d artifacts successful", completed)

    logging.debug("Source: %s", args.artifact_location)
    logging.debug("Max workers: %d", args.max_workers)


def _extract_artifact_info(
    artifact_data: ArtifactFile | ArtifactMetadata | dict[str, Any],
) -> tuple[str, dict[str, str]]:
    """
    Extract file path and labels from artifact data.

    Args:
        artifact_data: Artifact data (model or dict)

    Returns:
        Tuple of (file_path, labels)
    """
    if isinstance(artifact_data, dict):
        return artifact_data["file"], artifact_data.get("pulp_labels", {})

    if hasattr(artifact_data, "file"):
        labels = getattr(artifact_data, "labels", {})
        return artifact_data.file, labels

    raise ValueError(f"Unexpected artifact_data type: {type(artifact_data)}")


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


def _get_file_size_safe(file_path: str) -> tuple[int, str]:
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


def _log_single_artifact(artifact_name: str, artifact_data: ArtifactFile | ArtifactMetadata | dict[str, Any]) -> int:
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


def _calculate_artifact_totals(pulled_artifacts: PulledArtifacts) -> tuple[int, int]:
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
    from ..utils.iteration_utils import iterate_all_artifacts

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
    from ..utils.iteration_utils import count_artifacts
    from ..utils.logging_utils import format_artifact_counts

    counts = count_artifacts(pulled_artifacts)
    counts_str = format_artifact_counts(counts)

    if counts_str == "No artifacts":
        return "Downloaded: No files"

    return f"Downloaded: {counts_str} ({_format_file_size(total_size)})"


def _log_artifacts_downloaded(pulled_artifacts: PulledArtifacts) -> tuple[int, int]:
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
    from ..utils.iteration_utils import iterate_all_artifacts

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


def _log_pulp_upload_info(upload_info: PulpResultsDocument | None) -> None:
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


def generate_pull_report(
    pulled_artifacts: PulledArtifacts,
    completed: int,
    failed: int,
    args: PullContext,
    upload_info: PulpResultsDocument | None = None,
) -> None:
    """
    Generate and display a comprehensive report of what was pulled and where it was stored.

    Args:
        pulled_artifacts: Dictionary containing all pulled artifacts organized by type
        completed: Number of successfully downloaded artifacts
        failed: Number of failed downloads
        args: Pull context with command arguments
        upload_info: Optional dictionary containing upload information from Pulp
    """
    _log_pull_summary(completed, failed, args)
    total_files, _ = _log_artifacts_downloaded(pulled_artifacts)
    _log_storage_summary(total_files, pulled_artifacts)
    _log_pulp_upload_info(upload_info)
    _log_build_information(pulled_artifacts)

    logging.info("Pull completed successfully")


__all__ = [
    "generate_pull_report",
    "_log_upload_summary",
    "_format_file_size",
]
