"""
Upload utilities for Pulp operations.

This module provides utilities for uploading RPMs, logs, SBOM files,
and other artifacts to Pulp repositories.
"""

import glob
import logging
import os
from typing import TYPE_CHECKING, Any

import httpx

from ..models.context import UploadContext
from ..models.results import PulpResultsModel, RpmUploadResult
from .constants import SUPPORTED_ARCHITECTURES
from .error_handling import handle_generic_error
from .pulp_tasks import create_file_content_and_wait, wait_for_successful_task
from .rpm_operations import upload_rpms_parallel
from .rpm_overwrite import remove_rpms_matching_local_files_from_repository
from .validation import validate_file_path

if TYPE_CHECKING:
    from ..api.pulp_client import PulpClient

# Constants used in this module
RPM_FILE_PATTERN = "*.rpm"
LOG_FILE_PATTERN = "*.log"


def create_labels(build_id: str, arch: str, namespace: str, parent_package: str | None, date: str) -> dict[str, str]:
    """
    Create standard labels for Pulp content.

    Args:
        build_id: Unique build identifier
        arch: Architecture (e.g., 'x86_64', 'aarch64')
        namespace: Namespace for the content
        parent_package: Optional parent package name (will not be added to labels if None)
        date: Build date string

    Returns:
        Dictionary containing standard labels for Pulp content
    """
    labels = {
        "date": date,
        "build_id": build_id,
        "arch": arch,
        "namespace": namespace,
    }
    if parent_package:
        labels["parent_package"] = parent_package
    return labels


def upload_log(
    client: "PulpClient",
    file_repository_prn: str,
    log_path: str,
    *,
    build_id: str,
    labels: dict[str, str],
    arch: str,
    results_model: PulpResultsModel | None = None,
    distribution_urls: dict[str, str] | None = None,
    target_arch_repo: bool = False,
) -> list[str]:
    """
    Upload a log file to the specified file repository.

    Args:
        client: PulpClient instance for API interactions
        file_repository_prn: File repository PRN for log uploads
        log_path: Path to the log file to upload
        build_id: Build identifier for the log
        labels: Labels to attach to the log content
        arch: Architecture for the log content

    Returns:
        List of created resource hrefs from the upload task
    """
    validate_file_path(log_path, "Log")

    if not file_repository_prn or not str(file_repository_prn).strip():
        raise ValueError(
            "Log upload requires a logs repository PRN. Create the logs repository or unset skip_logs_repo."
        )

    task_response = create_file_content_and_wait(
        client,
        file_repository_prn,
        log_path,
        build_id=build_id,
        pulp_label=labels,
        arch=arch,
        operation=f"upload log {log_path}",
    )

    if results_model is not None and distribution_urls is not None:
        rel_path: str | None = None
        if task_response.result and isinstance(task_response.result, dict):
            rel_path = task_response.result.get("relative_path")
        if not rel_path:
            fn = os.path.basename(log_path)
            rel_path = f"{arch}/{fn}" if arch else fn
        client.add_uploaded_artifact_to_results_model(
            results_model,
            local_path=log_path,
            labels=labels,
            is_rpm=False,
            distribution_urls=distribution_urls,
            target_arch_repo=target_arch_repo,
            file_relative_path=rel_path,
        )

    # Return the created resources from the task
    return task_response.created_resources if task_response.created_resources else []


def _upload_logs_sequential(
    client: "PulpClient",
    logs: list[str],
    *,
    file_repository_prn: str,
    build_id: str,
    labels: dict[str, str],
    arch: str,
    results_model: PulpResultsModel | None = None,
    distribution_urls: dict[str, str] | None = None,
    target_arch_repo: bool = False,
) -> None:
    """
    Upload logs sequentially.

    This function uploads log files one by one to avoid overwhelming the server
    with concurrent file uploads.

    Args:
        client: PulpClient instance for API interactions
        logs: List of log file paths to upload
        file_repository_prn: File repository PRN for log uploads
        build_id: Build identifier for the logs
        labels: Labels to attach to the uploaded content
        arch: Architecture for the uploaded logs
    """
    logging.warning("Uploading %d log file(s) for %s", len(logs), arch)
    for log in logs:
        logging.warning("Uploading log: %s", os.path.basename(log))
        upload_log(
            client,
            file_repository_prn,
            log,
            build_id=build_id,
            labels=labels,
            arch=arch,
            results_model=results_model,
            distribution_urls=distribution_urls,
            target_arch_repo=target_arch_repo,
        )


def upload_artifacts_to_repository(
    client: "PulpClient", artifacts: dict[str, Any], repository_prn: str, file_type: str
) -> tuple[int, list[str]]:
    """
    Upload artifacts to a specific repository.

    Args:
        client: PulpClient instance for API interactions
        artifacts: Dictionary of artifacts to upload (either Dict[str, Dict] or Dict[str, ArtifactFile])
        repository_prn: Repository PRN to upload to
        file_type: Type of file being uploaded (for logging)

    Returns:
        Tuple of (upload_count, error_list)
    """
    upload_count = 0
    errors = []

    for artifact_name, artifact_info in artifacts.items():
        try:
            logging.warning("Uploading %s: %s", file_type, artifact_name)

            # Support both dict and ArtifactFile objects
            if isinstance(artifact_info, dict):
                file_path = artifact_info["file"]
                labels = artifact_info["labels"]
            else:  # ArtifactFile model
                file_path = artifact_info.file
                labels = artifact_info.labels

            # Upload the file content
            content_response = client.create_file_content(
                repository_prn,
                file_path,
                build_id=labels.get("build_id", "unknown"),
                pulp_label=labels,
                filename=os.path.basename(file_path),
                arch=labels.get("arch", "unknown"),
            )

            # Check if response contains a task or if it's already complete
            response_data = content_response.json()
            if "task" in response_data:
                task_href = response_data["task"]
                wait_for_successful_task(client, task_href, f"upload {file_type} {artifact_name}")
            else:
                # Response might be immediate success, log it
                logging.debug("File upload completed immediately: %s", artifact_name)
            upload_count += 1
            logging.debug("Successfully uploaded %s: %s", file_type, artifact_name)

        except (httpx.HTTPError, ValueError, FileNotFoundError, KeyError) as e:
            handle_generic_error(e, f"upload {file_type} {artifact_name}")
            errors.append(f"{file_type} {artifact_name}: {e}")

    return upload_count, errors


def upload_rpms(
    rpms: list[str],
    context: UploadContext,
    client: "PulpClient",
    arch: str,
    *,
    rpm_repository_href: str,
    date: str,
    results_model: PulpResultsModel,
    distribution_urls: dict[str, str] | None = None,
    target_arch_repo: bool = False,
) -> list[str]:
    """
    Upload RPMs for a specific architecture.

    This function handles uploading RPMs in parallel and adding them to the repository.

    Args:
        rpms: List of RPM file paths to upload
        context: Upload context containing build metadata
        client: PulpClient instance for API interactions
        arch: Architecture being processed
        rpm_repository_href: RPM repository href for adding content
        date: Build date string
        results_model: PulpResultsModel to update with upload counts

    When context has overwrite=True (UploadRpmContext), existing RPM package units in the
    target repository matching local RPM NVRA filenames (and signed_by when set) are removed before upload.

    Returns:
        List of created resource hrefs from the add_content operation
    """
    if not rpms:
        logging.debug("No new RPMs to upload for %s", arch)
        return []

    logging.warning("Uploading %d RPMs for %s", len(rpms), arch)
    labels = create_labels(context.build_id, arch, context.namespace, context.parent_package, date)
    signed_by_val = getattr(context, "signed_by", None)
    if signed_by_val and isinstance(signed_by_val, str) and signed_by_val.strip():
        labels["signed_by"] = signed_by_val.strip()

    # Use `is True` so unittest.Mock without overwrite does not enable (getattr returns MagicMock).
    if getattr(context, "overwrite", False) is True:
        sb_for_search = (
            signed_by_val.strip()
            if signed_by_val and isinstance(signed_by_val, str) and signed_by_val.strip()
            else None
        )
        remove_rpms_matching_local_files_from_repository(client, rpms, rpm_repository_href, sb_for_search)

    # Upload RPMs in parallel
    rpm_path_href_pairs, upload_errors = upload_rpms_parallel(client, rpms, labels, arch)
    rpm_results_artifacts = [href for _path, href in rpm_path_href_pairs]

    if distribution_urls is not None:
        for rpm_path, _href in rpm_path_href_pairs:
            client.add_uploaded_artifact_to_results_model(
                results_model,
                local_path=rpm_path,
                labels=labels,
                is_rpm=True,
                distribution_urls=distribution_urls,
                target_arch_repo=target_arch_repo,
            )

    for err in upload_errors:
        results_model.add_error(err)

    # Update upload counts with successful uploads only
    results_model.increment_counts(rpms=len(rpm_path_href_pairs))

    if len(rpm_path_href_pairs) != len(rpms):
        failed_count = len(rpms) - len(rpm_path_href_pairs)
        detail = "; ".join(upload_errors) if upload_errors else f"{failed_count} RPM(s) failed without error details"
        raise ValueError(f"Failed to upload {failed_count} of {len(rpms)} RPM(s) for {arch}: {detail}")

    # Store created resources from add_content operations
    created_resources = []

    # Add uploaded RPMs to the repository
    if rpm_results_artifacts:
        logging.debug("Adding %s RPM artifacts to repository", len(rpm_results_artifacts))
        rpm_repo_task = client.add_content(rpm_repository_href, rpm_results_artifacts)
        wait_for_successful_task(client, rpm_repo_task.pulp_href, f"add RPM content to repository ({arch})")
        # Content unit hrefs for gather-by-href fallback (add_content task resources are often repo versions).
        created_resources.extend(rpm_results_artifacts)
        logging.debug(
            "Recorded %d RPM content href(s) for results gather fallback",
            len(rpm_results_artifacts),
        )

    return created_resources


def upload_rpms_logs(
    rpm_path: str,
    context: UploadContext,
    client: "PulpClient",
    arch: str,
    *,
    rpm_repository_href: str,
    file_repository_prn: str,
    date: str,
    results_model: PulpResultsModel,
    distribution_urls: dict[str, str] | None = None,
    target_arch_repo: bool = False,
) -> RpmUploadResult:
    """
    Upload RPMs and logs for a specific architecture.

    This function handles the complete upload process for a single architecture,
    including checking existing RPMs on Pulp, uploading new RPMs, and uploading logs.

    Args:
        rpm_path: Path to directory containing RPM and log files
        context: Upload context containing build metadata
        client: PulpClient instance for API interactions
        arch: Architecture being processed
        rpm_repository_href: RPM repository href for adding content
        file_repository_prn: File repository PRN for log uploads
        date: Build date string
        results_model: PulpResultsModel to update with upload counts

    Returns:
        RpmUploadResult containing uploaded RPMs, existing artifacts, and created resources
    """
    # Find RPM and log files
    rpms = glob.glob(os.path.join(rpm_path, RPM_FILE_PATTERN))
    logs = glob.glob(os.path.join(rpm_path, LOG_FILE_PATTERN))

    if not rpms and not logs:
        logging.debug("No RPMs or logs found in %s", rpm_path)
        return RpmUploadResult()

    if logs:
        if not file_repository_prn or not str(file_repository_prn).strip():
            raise ValueError(
                "Log files are present but logs repository PRN is empty. "
                "Create the logs repository when uploading logs (do not set skip_logs_repo)."
            )

    logging.warning("Processing %s: %d RPMs, %d logs", arch, len(rpms), len(logs))
    labels = create_labels(context.build_id, arch, context.namespace, context.parent_package, date)

    # Store created resources from add_content operations
    created_resources = []

    # Upload RPMs in parallel
    if rpms:
        created_resources = upload_rpms(
            rpms,
            context,
            client,
            arch,
            rpm_repository_href=rpm_repository_href,
            date=date,
            results_model=results_model,
            distribution_urls=distribution_urls,
            target_arch_repo=target_arch_repo,
        )

    # Upload logs sequentially
    if logs:
        logging.warning("Uploading %d logs for %s", len(logs), arch)
        _upload_logs_sequential(
            client,
            logs,
            file_repository_prn=file_repository_prn,
            build_id=context.build_id,
            labels=labels,
            arch=arch,
            results_model=results_model,
            distribution_urls=distribution_urls,
            target_arch_repo=target_arch_repo,
        )
        # Update upload counts
        results_model.increment_counts(logs=len(logs))
    else:
        logging.debug("No logs to upload for %s", arch)

    return RpmUploadResult(
        uploaded_rpms=rpms,
        created_resources=created_resources,
    )


def rpm_directory_has_log_files(rpm_path: str) -> bool:
    """
    Return True if ``rpm_path`` contains any ``*.log`` under a supported arch subdirectory or at root.
    """
    if not rpm_path or not os.path.isdir(rpm_path):
        return False

    for arch in SUPPORTED_ARCHITECTURES:
        arch_dir = os.path.join(rpm_path, arch)
        if os.path.isdir(arch_dir) and glob.glob(os.path.join(arch_dir, LOG_FILE_PATTERN)):
            return True
    return bool(glob.glob(os.path.join(rpm_path, LOG_FILE_PATTERN)))


__all__ = [
    "create_labels",
    "upload_log",
    "upload_artifacts_to_repository",
    "upload_rpms",
    "upload_rpms_logs",
    "rpm_directory_has_log_files",
]
