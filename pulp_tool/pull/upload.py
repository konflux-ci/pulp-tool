"""
Upload operations for re-uploading downloaded artifacts to Pulp.

This module handles uploading downloaded artifacts to destination Pulp repositories.
"""

import logging

import httpx

from ..api import PulpClient
from ..models.artifacts import PulledArtifacts
from ..models.context import PullContext
from ..models.repository import RepositoryRefs
from ..models.results import PulpResultsModel
from ..utils import PulpHelper, determine_build_id, extract_metadata_from_artifacts
from ..utils.error_handling import handle_generic_error
from ..utils.pulp_tasks import create_file_content_and_wait, wait_for_successful_task
from ..utils.rpm_operations import upload_rpms_parallel
from .reporting import _log_upload_summary


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

        logging.warning("Uploading %d SBOM file(s)", len(sbom_items))
        for name, artifact in sbom_items:
            logging.warning("Uploading SBOM: %s", name)
            try:
                create_file_content_and_wait(
                    pulp_client,
                    repositories.sbom_prn,
                    artifact.file,
                    build_id=artifact.labels.get("build_id", ""),
                    pulp_label=artifact.labels,
                    filename=name,
                    operation=f"upload SBOM {name}",
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

        logging.warning("Uploading %d log file(s)", len(log_items))
        for name, artifact in log_items:
            logging.warning("Uploading log: %s", name)
            try:
                # Extract arch from labels for relative path construction
                arch = artifact.labels.get("arch")
                create_file_content_and_wait(
                    pulp_client,
                    repositories.logs_prn,
                    artifact.file,
                    build_id=artifact.labels.get("build_id", ""),
                    pulp_label=artifact.labels,
                    filename=name,
                    arch=arch,
                    operation=f"upload log {name}",
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

    logging.warning("Uploading %d RPM file(s)", len(rpm_infos))

    # Upload all RPMs in parallel using the consolidated function
    rpm_pairs, rpm_errors = upload_rpms_parallel(pulp_client, rpm_infos)
    rpm_artifacts = [href for _path, href in rpm_pairs]
    upload_info.upload_errors.extend(rpm_errors)

    # Add all successfully uploaded RPM artifacts to the repository
    if rpm_artifacts:
        logging.debug("Adding %d RPM artifacts to repository", len(rpm_artifacts))
        try:
            add_task = pulp_client.add_content(repositories.rpms_href, rpm_artifacts)
            wait_for_successful_task(pulp_client, add_task.pulp_href, "add RPMs to repository")
            upload_info.uploaded_counts.rpms = len(rpm_artifacts)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            handle_generic_error(e, "add RPMs to repository")
            upload_info.add_error(f"RPM repository addition: {e}")


def upload_downloaded_files_to_pulp(
    pulp_client: PulpClient, pulled_artifacts: PulledArtifacts, args: PullContext
) -> PulpResultsModel:
    """
    Upload downloaded files to the appropriate Pulp repositories.

    Args:
        pulp_client: PulpClient instance for API interactions
        pulled_artifacts: Dictionary containing downloaded artifacts organized by type
        args: Pull context with command arguments

    Returns:
        PulpResultsModel containing upload information including repository details
    """
    # Extract parent_package from artifacts for proper distribution base_path
    parent_package = extract_metadata_from_artifacts(pulled_artifacts, "parent_package")
    logging.debug("Extracted parent_package from artifacts: %s", parent_package)

    # Initialize PulpHelper to get repository information
    helper = PulpHelper(pulp_client, parent_package=parent_package)

    # Determine build ID and setup repositories
    build_id = determine_build_id(args, pulled_artifacts=pulled_artifacts)  # type: ignore[arg-type]
    repositories = helper.setup_repositories(build_id)

    # Initialize upload tracking with unified model
    upload_info = PulpResultsModel(build_id=build_id, repositories=repositories)

    # Upload different artifact types
    _upload_sboms_and_logs(pulp_client, pulled_artifacts, repositories, upload_info)
    _upload_rpms_to_repository(pulp_client, pulled_artifacts, repositories, upload_info)

    _log_upload_summary(upload_info)

    return upload_info


__all__ = ["upload_downloaded_files_to_pulp"]
