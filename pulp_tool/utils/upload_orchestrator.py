"""
Upload workflow orchestration for Pulp operations.

This module handles orchestrating upload workflows including
architecture processing and result collection.
"""

from __future__ import annotations

import glob
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from ..models.artifacts import ExtraArtifactRef
from ..models.context import UploadFilesContext, UploadRpmContext
from ..models.repository import RepositoryRefs
from ..models.results import PulpResultsModel, RpmUploadResult
from .artifact_detection import detect_arch_from_filepath, group_rpm_paths_by_arch
from .constants import ARCH_DETECT_WARNING_MSG, ARCHITECTURE_THREAD_PREFIX, SUPPORTED_ARCHITECTURES
from .error_handling import handle_generic_error
from .pulp_tasks import create_file_content_and_wait
from .uploads import RPM_FILE_PATTERN, create_labels, upload_log, upload_rpms, upload_rpms_logs
from .validation import validate_file_path

if TYPE_CHECKING:
    from ..api.pulp_client import PulpClient
    from .pulp_helper import PulpHelper


def _use_signed_rpm_repository(context: UploadRpmContext) -> bool:
    """True when RPMs should use the signed aggregate repo (not per-arch target repo)."""
    signed_by = getattr(context, "signed_by", None)
    return bool(signed_by and str(signed_by).strip()) and not context.target_arch_repo


def _rpm_repository_href_for_upload(context: UploadRpmContext, repositories: RepositoryRefs) -> str:
    """Return the RPM repository href for uploads (signed repo when ``signed_by`` is set)."""
    if _use_signed_rpm_repository(context):
        if not repositories.rpms_signed_href:
            raise ValueError("signed_by requires signed RPM repository href")
        return repositories.rpms_signed_href
    if not repositories.rpms_href:
        raise ValueError("RPM repository href is required but not found")
    return repositories.rpms_href


class UploadOrchestrator:
    """
    Orchestrates upload workflows for Pulp operations.

    This class handles processing uploads for multiple architectures
    and coordinating the complete upload process.
    """

    def __init__(self) -> None:
        """Initialize the upload orchestrator."""

    def _find_existing_architectures(self, rpm_path: str) -> list[str]:
        """
        Find architectures that have existing directories.

        Args:
            rpm_path: Base path containing architecture subdirectories

        Returns:
            List of architecture names that have existing directories
        """
        existing_archs = []
        for arch in SUPPORTED_ARCHITECTURES:
            arch_path = os.path.join(rpm_path, arch)
            if os.path.exists(arch_path):
                existing_archs.append(arch)
            else:
                logging.debug("Skipping %s - path does not exist: %s", arch, arch_path)
        return existing_archs

    def _submit_architecture_tasks(
        self,
        executor: ThreadPoolExecutor,
        existing_archs: list[str],
        rpm_path: str,
        args: UploadRpmContext,
        client: PulpClient,
        rpm_href: str,
        logs_prn: str,
        date_str: str,
        results_model: PulpResultsModel,
        distribution_urls: dict[str, str],
        *,
        pulp_helper: PulpHelper | None = None,
        target_arch_repo: bool = False,
    ) -> dict[Any, str]:
        """
        Submit architecture upload tasks to the executor.

        Args:
            executor: ThreadPoolExecutor instance
            existing_archs: List of architecture names to process
            rpm_path: Base path containing architecture subdirectories
            args: Upload context with command arguments
            client: PulpClient instance for API interactions
            rpm_href: RPM repository href for adding content
            logs_prn: Logs repository PRN
            date_str: Build date string
            results_model: PulpResultsModel to update with upload counts

        Returns:
            Dictionary mapping futures to architecture names
        """
        future_to_arch = {}
        for arch in existing_archs:
            arch_path = os.path.join(rpm_path, arch)
            if args.target_arch_repo:
                if pulp_helper is None:
                    raise ValueError("target_arch_repo requires PulpHelper for per-arch RPM repositories")
                arch_rpm_href = pulp_helper.ensure_rpm_repository_for_arch(args.build_id, arch)
            else:
                arch_rpm_href = rpm_href
            future = executor.submit(
                upload_rpms_logs,
                arch_path,
                args,
                client,
                arch,
                rpm_repository_href=arch_rpm_href,
                file_repository_prn=logs_prn,
                date=date_str,
                results_model=results_model,
                distribution_urls=distribution_urls,
                target_arch_repo=target_arch_repo,
            )
            future_to_arch[future] = arch
        return future_to_arch

    def _collect_architecture_results(self, future_to_arch: dict[Any, str]) -> dict[str, RpmUploadResult]:
        """
        Collect results from architecture upload futures.

        Args:
            future_to_arch: Dictionary mapping futures to architecture names

        Returns:
            Dictionary mapping architecture names to their upload results

        Raises:
            Exception: If any architecture upload fails
        """
        processed_archs: dict[str, RpmUploadResult] = {}
        for future in as_completed(future_to_arch):
            arch = future_to_arch[future]
            try:
                logging.debug("Processing architecture: %s", arch)
                result = future.result()
                processed_archs[arch] = result
                logging.debug(
                    "Completed processing architecture: %s with %d created resources",
                    arch,
                    len(result.created_resources),
                )
            except Exception as e:
                handle_generic_error(e, f"process architecture {arch}")
                raise

        logging.debug("Processed architectures: %s", ", ".join(processed_archs.keys()))
        return processed_archs

    def process_architecture_uploads(
        self,
        client: PulpClient,
        args: UploadRpmContext,
        repositories: RepositoryRefs,
        *,
        date_str: str,
        rpm_href: str,
        results_model: PulpResultsModel,
        distribution_urls: dict[str, str],
        pulp_helper: PulpHelper | None = None,
        target_arch_repo: bool = False,
    ) -> dict[str, RpmUploadResult]:
        """
        Process uploads for all supported architectures.

        This function processes uploads for all supported architectures in parallel,
        handling RPM and log uploads for each architecture directory found.

        Args:
            client: PulpClient instance for API interactions
            args: Command line arguments
            repositories: Dictionary of repository identifiers
            date_str: Build date string
            rpm_href: RPM repository href for adding content
            results_model: PulpResultsModel to update with upload counts

        Returns:
            Mapping of architecture name to RpmUploadResult (uploaded RPM paths and created_resources hrefs)
        """
        # Ensure rpm_path is set (should be set by CLI, but check for safety)
        if not args.rpm_path:
            logging.warning("rpm_path is not set, cannot process architecture uploads")
            return {}

        # Find architectures that exist
        existing_archs = self._find_existing_architectures(args.rpm_path)

        if not existing_archs:
            logging.warning("No architecture directories found in %s", args.rpm_path)
            return {}

        # Process architectures in parallel for better performance
        with ThreadPoolExecutor(
            thread_name_prefix=ARCHITECTURE_THREAD_PREFIX, max_workers=len(existing_archs)
        ) as executor:
            # Submit all architecture processing tasks
            future_to_arch = self._submit_architecture_tasks(
                executor,
                existing_archs,
                args.rpm_path,
                args,
                client,
                rpm_href,
                repositories.logs_prn,
                date_str,
                results_model,
                distribution_urls,
                pulp_helper=pulp_helper,
                target_arch_repo=target_arch_repo,
            )

            # Collect results as they complete
            processed_archs = self._collect_architecture_results(future_to_arch)

        return processed_archs

    def process_uploads(
        self,
        client: PulpClient,
        args: UploadRpmContext,
        repositories: RepositoryRefs,
        *,
        pulp_helper: PulpHelper | None = None,
    ) -> str | None:
        """
        Process all upload operations.

        This function orchestrates the complete upload process including processing
        all architectures, uploading SBOM, and collecting results.
        When args.results_json is set, uploads from that file instead.

        Args:
            client: PulpClient instance for API interactions
            args: UploadRpmContext with command line arguments (including date_str)
            repositories: RepositoryRefs containing all repository identifiers
            pulp_helper: Optional PulpHelper; required when ``target_arch_repo`` is True

        Returns:
            URL of the uploaded results JSON, or None if upload failed
        """
        # Import here to avoid circular import
        from ..services.upload_service import collect_results, process_uploads_from_results_json, upload_sbom
        from .pulp_helper import PulpHelper as PulpHelperCls

        if args.results_json:
            return process_uploads_from_results_json(client, args, repositories, pulp_helper=pulp_helper)

        if args.target_arch_repo:
            if pulp_helper is None:
                raise ValueError("target_arch_repo requires PulpHelper for per-arch RPM repositories")
        elif not _use_signed_rpm_repository(args) and not repositories.rpms_href:
            raise ValueError("RPM repository href is required but not found")
        elif _use_signed_rpm_repository(args) and not repositories.rpms_signed_href:
            raise ValueError("signed_by requires signed RPM repository href")

        # Get date_str from args
        date_str = args.date_str

        # Create unified results model at the start
        results_model = PulpResultsModel(build_id=args.build_id, repositories=repositories)

        repo_helper = pulp_helper or PulpHelperCls(client, parent_package=args.parent_package)
        distribution_urls = repo_helper.get_distribution_urls_for_upload_context(args.build_id, args)
        rpm_href = "" if args.target_arch_repo else _rpm_repository_href_for_upload(args, repositories)

        # Process each architecture - now updates results_model internally
        processed_uploads = self.process_architecture_uploads(
            client,
            args,
            repositories,
            date_str=date_str,
            rpm_href=rpm_href,
            results_model=results_model,
            distribution_urls=distribution_urls,
            pulp_helper=pulp_helper,
            target_arch_repo=args.target_arch_repo,
        )

        # Collect all created resources from add_content operations
        created_resources: list[str] = []
        for upload in processed_uploads.values():
            created_resources.extend(upload.created_resources)

        # Always search the base rpm_path for root-level RPMs (e.g. .src.rpm, .noarch.rpm).
        # OCI/oras layouts often put these in the root while logs live in arch subdirs (e.g. aarch64/).
        if args.rpm_path:
            rpm_glob_path = os.path.join(args.rpm_path, RPM_FILE_PATTERN)
            root_rpm_files = [p for p in glob.glob(rpm_glob_path) if os.path.isfile(p)]
            if root_rpm_files:
                logging.warning(
                    "Found %d RPM(s) in base path %s (root-level), uploading by detected architecture",
                    len(root_rpm_files),
                    args.rpm_path,
                )
                rpms_by_arch = group_rpm_paths_by_arch(root_rpm_files)
                for arch, rpm_list in rpms_by_arch.items():
                    logging.warning("Uploading %d root-level RPM(s) for architecture %s", len(rpm_list), arch)
                    if args.target_arch_repo:
                        assert pulp_helper is not None  # noqa: S101  # enforced at start when target_arch_repo is set
                        root_rpm_href = pulp_helper.ensure_rpm_repository_for_arch(args.build_id, arch)
                    else:
                        root_rpm_href = rpm_href
                    created_resources.extend(
                        upload_rpms(
                            rpm_list,
                            args,
                            client,
                            arch,
                            rpm_repository_href=root_rpm_href,
                            date=date_str,
                            results_model=results_model,
                            distribution_urls=distribution_urls,
                            target_arch_repo=args.target_arch_repo,
                        )
                    )

        # Upload SBOM and capture its created resources - updates results_model internally
        # Only upload SBOM if sbom_path is provided
        if args.sbom_path:
            sbom_created_resources = upload_sbom(
                client,
                args,
                repositories.sbom_prn,
                date_str,
                results_model,
                args.sbom_path,
                distribution_urls=distribution_urls,
                target_arch_repo=args.target_arch_repo,
            )
            created_resources.extend(sbom_created_resources)
        else:
            logging.debug("Skipping SBOM upload - no sbom_path provided")

        logging.info("Collected %d created resource hrefs from upload operations", len(created_resources))

        # Convert created_resources hrefs into artifact format for extra_artifacts
        extra_artifacts = [ExtraArtifactRef(pulp_href=href) for href in created_resources]
        logging.info("Total artifacts to include in results: %d", len(extra_artifacts))

        # Collect and save results, passing the results_model and all artifacts
        results_json_url = collect_results(client, args, date_str, results_model, extra_artifacts)

        # Summary logging
        total_architectures = len(processed_uploads)
        logging.debug(
            "Upload process completed: %d architectures processed",
            total_architectures,
        )

        return results_json_url

    def process_file_uploads(
        self, client: PulpClient, context: UploadFilesContext, repositories: RepositoryRefs
    ) -> str | None:
        """
        Process upload of individual files to Pulp repositories.

        This function handles uploading RPMs, generic files, logs, and SBOMs
        from individual file paths specified in the context.

        Args:
            client: PulpClient instance for API interactions
            context: UploadFilesContext with file paths and metadata
            repositories: RepositoryRefs containing all repository identifiers

        Returns:
            URL of the uploaded results JSON, or None if upload failed
        """
        # Import here to avoid circular import
        from ..services.upload_service import collect_results, upload_sbom
        from .pulp_helper import PulpHelper as PulpHelperCls

        # Create unified results model
        results_model = PulpResultsModel(build_id=context.build_id, repositories=repositories)
        repo_helper = PulpHelperCls(client, parent_package=context.parent_package)
        distribution_urls = repo_helper.get_distribution_urls_for_upload_context(context.build_id, context)
        target_arch_repo = bool(getattr(context, "target_arch_repo", False))

        # Store created resources from add_content operations
        created_resources = []

        # Upload RPMs
        if context.rpm_files:
            logging.warning("Uploading %d RPM file(s)", len(context.rpm_files))
            rpms_by_arch = group_rpm_paths_by_arch(context.rpm_files, explicit_arch=context.arch)

            # Upload RPMs for each architecture
            for arch, rpm_list in rpms_by_arch.items():
                arch_created_resources = upload_rpms(
                    rpm_list,
                    context,
                    client,
                    arch,
                    rpm_repository_href=repositories.rpms_href,
                    date=context.date_str,
                    results_model=results_model,
                    distribution_urls=distribution_urls,
                    target_arch_repo=target_arch_repo,
                )
                created_resources.extend(arch_created_resources)

        # Upload generic files
        if context.file_files:
            logging.warning("Uploading %d generic file(s)", len(context.file_files))
            for file_path in context.file_files:
                logging.warning("Uploading file: %s", os.path.basename(file_path))
                labels = create_labels(
                    context.build_id, "", context.namespace, context.parent_package, context.date_str
                )
                validate_file_path(file_path, "File")

                task_response = create_file_content_and_wait(
                    client,
                    repositories.artifacts_prn,
                    file_path,
                    build_id=context.build_id,
                    pulp_label=labels,
                    operation=f"upload file {file_path}",
                )
                if task_response.created_resources:
                    created_resources.extend(task_response.created_resources)
                results_model.increment_counts(files=1)
                rel_path = os.path.basename(file_path)
                client.add_uploaded_artifact_to_results_model(
                    results_model,
                    local_path=file_path,
                    labels=labels,
                    is_rpm=False,
                    distribution_urls=distribution_urls,
                    target_arch_repo=target_arch_repo,
                    file_relative_path=rel_path,
                )

        # Upload logs
        if context.log_files:
            logging.warning("Uploading %d log file(s)", len(context.log_files))
            for log_path in context.log_files:
                logging.warning("Uploading log: %s", os.path.basename(log_path))
                log_arch = context.arch or detect_arch_from_filepath(log_path)
                if not log_arch:
                    logging.warning(ARCH_DETECT_WARNING_MSG, os.path.basename(log_path))
                    continue

                labels = create_labels(
                    context.build_id, log_arch, context.namespace, context.parent_package, context.date_str
                )

                log_created_resources = upload_log(
                    client,
                    repositories.logs_prn,
                    log_path,
                    build_id=context.build_id,
                    labels=labels,
                    arch=log_arch,
                    results_model=results_model,
                    distribution_urls=distribution_urls,
                    target_arch_repo=target_arch_repo,
                )
                created_resources.extend(log_created_resources)
                results_model.increment_counts(logs=1)

        # Upload SBOMs
        if context.sbom_files:
            logging.warning("Uploading %d SBOM file(s)", len(context.sbom_files))
            for sbom_path in context.sbom_files:
                logging.warning("Uploading SBOM: %s", os.path.basename(sbom_path))
                sbom_created_resources = upload_sbom(
                    client,
                    context,
                    repositories.sbom_prn,
                    context.date_str,
                    results_model,
                    sbom_path,
                    distribution_urls=distribution_urls,
                    target_arch_repo=target_arch_repo,
                )
                created_resources.extend(sbom_created_resources)

        logging.info("Collected %d created resource hrefs from upload operations", len(created_resources))

        # Convert created_resources hrefs into artifact format for extra_artifacts
        extra_artifacts = [ExtraArtifactRef(pulp_href=href) for href in created_resources]
        logging.info("Total artifacts to include in results: %d", len(extra_artifacts))

        # Collect and save results, passing the results_model and all artifacts
        results_json_url = collect_results(client, context, context.date_str, results_model, extra_artifacts)

        return results_json_url


__all__ = ["UploadOrchestrator"]
