"""
Upload service for high-level upload operations.

This module provides a service layer that orchestrates upload operations,
abstracting the complexity of coordinating between repositories, distributions,
and content uploads.

Key Functions:
    - upload_sbom(): Upload SBOM files to repository
    - collect_results(): Gather and upload results JSON (implemented in ``upload_collect``)
    - Konflux result helpers live in ``upload_collect``

Program/library entry points:
    - **CLI and Konflux** use :class:`pulp_tool.utils.pulp_helper.PulpHelper` (``setup_repositories``,
 ``process_uploads``) as the primary orchestration API.
    - :class:`UploadService` is a thin wrapper for tests and programmatic use; it delegates to
      the same ``PulpHelper`` / ``UploadOrchestrator`` path as the CLI.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..models.artifacts import ExtraArtifactRef
from ..models.context import UploadContext, UploadRpmContext
from ..models.pulp_results import PulpResultsDocument
from ..models.repository import RepositoryRefs

if TYPE_CHECKING:
    from ..api.pulp_client import PulpClient

from ..utils import PulpHelper, create_labels, validate_file_path
from ..utils.constants import SBOM_EXTENSIONS, SUPPORTED_ARCHITECTURES
from ..utils.path_utils import resolve_path_under_base
from ..utils.pulp_tasks import create_file_content_and_wait
from .upload_collect import (
    _add_distributions_to_results,
    _build_artifact_map,
    _extract_results_url,
    _find_artifact_content,
    _gather_and_validate_content,
    _handle_sbom_results,
    _parse_oci_reference,
    _populate_results_model,
    _save_results_to_folder,
    _serialize_results_to_json,
    _upload_and_get_results_url,
)
from .upload_collect_public import collect_results
from .upload_common import _distribution_urls_for_context

# ============================================================================
# Constants
# ============================================================================

MAX_LOG_LINE_LENGTH = 114


class UploadService:
    """
    High-level service for upload operations.

    This service provides a clean interface for upload operations,
    coordinating between repositories, distributions, and content uploads.
    """

    def __init__(self, pulp_client: "PulpClient", parent_package: str | None = None) -> None:
        """
        Initialize the upload service.

        Args:
            pulp_client: PulpClient instance for API interactions
            parent_package: Optional parent package name for distribution paths
        """
        self.client = pulp_client
        self.helper = PulpHelper(pulp_client, parent_package=parent_package)

    def setup_repositories(self, build_id: str) -> RepositoryRefs:
        """
        Set up all required repositories for a build.

        Args:
            build_id: Build identifier

        Returns:
            RepositoryRefs containing all repository identifiers
        """
        logging.info("Setting up repositories for build: %s", build_id)
        repositories = self.helper.setup_repositories(build_id)
        logging.info("Repository setup completed")
        return repositories

    def upload_artifacts(self, context: UploadRpmContext, repositories: RepositoryRefs) -> str | None:
        """
        Upload all artifacts (RPMs, logs, SBOMs) and collect results.

        This method orchestrates the complete upload process including:
        - Processing architecture-specific uploads
        - Uploading SBOM files
        - Collecting and uploading results JSON

        Args:
            context: UploadRpmContext with all required parameters
            repositories: Repository references for upload targets

        Returns:
            URL of the uploaded results JSON, or None if upload failed
        """
        logging.info("Starting upload process for build: %s", context.build_id)
        results_json_url = self.helper.process_uploads(self.client, context, repositories, pulp_helper=self.helper)

        if not results_json_url:
            logging.error("Upload completed but results JSON was not created")
            return None

        logging.info("Upload completed successfully. Results JSON URL: %s", results_json_url)
        return results_json_url

    def get_distribution_urls(self, build_id: str) -> dict[str, str]:
        """
        Get distribution URLs for all repository types.

        Args:
            build_id: Build identifier

        Returns:
            Dictionary mapping repository types to distribution URLs
        """
        return self.helper.get_distribution_urls(build_id)


# ============================================================================
# SBOM and Results Functions
# ============================================================================


def upload_sbom(
    client: "PulpClient",
    context: UploadContext,
    sbom_repository_prn: str,
    date: str,
    results_model: PulpResultsDocument,
    sbom_path: str,
    *,
    distribution_urls: dict[str, str] | None = None,
    target_arch_repo: bool = False,
) -> list[str]:
    """
    Upload SBOM file to repository.

    Args:
        client: PulpClient instance for API interactions
        context: Upload context containing metadata
        sbom_repository_prn: SBOM repository PRN
        date: Build date string
        results_model: PulpResultsDocument to update with upload counts
        sbom_path: Path to the SBOM file to upload

    Returns:
        List of created resource hrefs from the upload task
    """
    if not os.path.exists(sbom_path):
        logging.error("SBOM file not found: %s", sbom_path)
        raise FileNotFoundError(f"SBOM file not found: {sbom_path}")

    if not sbom_repository_prn or not str(sbom_repository_prn).strip():
        raise ValueError(
            "Cannot upload SBOM: SBOM repository PRN is empty. "
            "Ensure the SBOM repository is created when uploading SBOM files."
        )

    logging.warning("Uploading SBOM: %s", sbom_path)
    labels = create_labels(context.build_id, "", context.namespace, context.parent_package, date)
    validate_file_path(sbom_path, "SBOM")

    task_response = create_file_content_and_wait(
        client,
        sbom_repository_prn,
        sbom_path,
        build_id=context.build_id,
        pulp_label=labels,
        operation=f"upload SBOM {sbom_path}",
    )
    logging.debug("SBOM uploaded successfully: %s", sbom_path)

    # Update upload counts
    results_model.increment_counts(sboms=1)

    if distribution_urls is not None:
        rel_path: str | None = None
        if task_response.result and isinstance(task_response.result, dict):
            rel_path = task_response.result.get("relative_path")
        if not rel_path:
            rel_path = os.path.basename(sbom_path)
        client.add_uploaded_artifact_to_results_model(
            results_model,
            local_path=sbom_path,
            labels=labels,
            is_rpm=False,
            distribution_urls=distribution_urls,
            target_arch_repo=target_arch_repo,
            file_relative_path=rel_path,
        )

    # Return the created resources from the task
    return task_response.created_resources


def _classify_artifact_from_key(key: str) -> str:
    """
    Classify artifact type from key (path/filename).

    Returns: "rpms", "logs", "sbom", or "artifacts"
    """
    key_lower = key.lower()
    if key_lower.endswith(".rpm"):
        return "rpms"
    if key_lower.endswith(".log"):
        return "logs"
    if "sbom" in key_lower:
        return "sbom"
    for ext in SBOM_EXTENSIONS:
        if key_lower.endswith(ext):
            if ext == ".json" and "sbom" not in key_lower:
                continue
            return "sbom"
    return "artifacts"


def scan_results_json_for_log_and_sbom_keys(results_json_path: str) -> tuple[bool, bool]:
    """
    Return (has_log_artifacts, has_sbom_artifacts) from keys in ``artifacts`` of a pulp_results.json.

    Missing or invalid JSON yields (False, False).
    """
    try:
        with open(results_json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False, False
    has_logs = False
    has_sbom = False
    artifacts = data.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return False, False
    for key in artifacts:
        kind = _classify_artifact_from_key(str(key))
        if kind == "logs":
            has_logs = True
        elif kind == "sbom":
            has_sbom = True
        if has_logs and has_sbom:
            break
    return has_logs, has_sbom


@dataclass
class UploadPlan:
    """Resolved local paths and labels for batch upload from a results document."""

    rpms_by_arch: dict[str, list[str]] = field(default_factory=dict)
    logs_to_upload: list[tuple[str, str]] = field(default_factory=list)
    sboms_to_upload: list[str] = field(default_factory=list)
    artifacts_to_upload: list[tuple[str, dict[str, str]]] = field(default_factory=list)


def _infer_arch_from_key(key: str, arch_hint: str) -> str:
    """Use label arch or infer from artifact key path (e.g. ``x86_64/pkg.rpm``)."""
    if arch_hint:
        return arch_hint
    parts = key.replace("\\", "/").split("/")
    for part in parts:
        if part in SUPPORTED_ARCHITECTURES:
            return part
    return "noarch"


def _load_results_document_for_upload(
    results_json_path: str,
    *,
    build_id: str,
    repositories: RepositoryRefs,
) -> PulpResultsDocument | None:
    """Load and normalize ``pulp_results.json``; return None when there are no artifacts."""
    try:
        with open(results_json_path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.error("Failed to read results JSON %s: %s", results_json_path, e)
        raise
    artifacts = raw.get("artifacts") or {}
    if not artifacts:
        logging.info("No artifacts in results JSON, creating minimal results")
        return None
    doc = PulpResultsDocument.from_raw(raw, repositories=repositories)
    if not doc.build_id.strip():
        doc.build_id = build_id
    return doc


def _plan_uploads_from_document(
    document: PulpResultsDocument,
    *,
    base_path: Path,
    context: UploadRpmContext,
) -> UploadPlan:
    """Classify document artifact keys into upload batches (pure path/plan logic)."""
    plan = UploadPlan()
    date_str = context.date_str
    for key, meta in document.artifacts.items():
        try:
            resolved_path = resolve_path_under_base(base_path, key)
        except ValueError as e:
            logging.error("Skipping unsafe artifact path %s: %s", key, e)
            continue
        if not resolved_path.exists():
            logging.warning("Skipping missing file: %s", resolved_path)
            continue
        labels = dict(meta.pulp_labels)
        labels.update(
            create_labels(
                context.build_id,
                labels.get("arch", ""),
                context.namespace,
                context.parent_package,
                date_str,
            )
        )
        art_type = _classify_artifact_from_key(key)
        arch = _infer_arch_from_key(key, labels.get("arch") or "")
        path_str = str(resolved_path)
        if art_type == "rpms":
            plan.rpms_by_arch.setdefault(arch, []).append(path_str)
        elif art_type == "logs":
            plan.logs_to_upload.append((path_str, arch))
        elif art_type == "sbom":
            plan.sboms_to_upload.append(path_str)
        else:
            plan.artifacts_to_upload.append((path_str, labels))
    return plan


def _validate_upload_plan_repositories(plan: UploadPlan, repositories: RepositoryRefs) -> None:
    if plan.logs_to_upload and not (repositories.logs_prn or "").strip():
        raise ValueError(
            "Cannot upload log artifacts: logs repository was not created. "
            "Use a run that creates the logs repository when results include log files."
        )
    if plan.sboms_to_upload and not (repositories.sbom_prn or "").strip():
        raise ValueError(
            "Cannot upload SBOM artifacts: SBOM repository was not created. "
            "Use a run that creates the SBOM repository when results include SBOM files."
        )


def _execute_upload_plan(
    plan: UploadPlan,
    *,
    client: "PulpClient",
    context: UploadRpmContext,
    repositories: RepositoryRefs,
    results_model: PulpResultsDocument,
    helper: PulpHelper,
    distribution_urls: dict[str, str],
    rpm_href: str,
    date_str: str,
) -> list[str]:
    from ..utils.uploads import upload_log, upload_rpms

    created_resources: list[str] = []
    logs_prn = repositories.logs_prn
    sbom_prn = repositories.sbom_prn
    artifacts_prn = repositories.artifacts_prn

    for arch, rpm_list in plan.rpms_by_arch.items():
        arch_href = (
            helper.ensure_rpm_repository_for_arch(context.build_id, arch) if context.target_arch_repo else rpm_href
        )
        created_resources.extend(
            upload_rpms(
                rpm_list,
                context,
                client,
                arch,
                rpm_repository_href=arch_href,
                date=date_str,
                results_model=results_model,
                distribution_urls=distribution_urls,
                target_arch_repo=context.target_arch_repo,
            )
        )

    for log_path, arch in plan.logs_to_upload:
        logging.warning("Uploading log: %s", os.path.basename(log_path))
        log_labels = create_labels(context.build_id, arch, context.namespace, context.parent_package, date_str)
        log_resources = upload_log(
            client,
            logs_prn,
            log_path,
            build_id=context.build_id,
            labels=log_labels,
            arch=arch,
            results_model=results_model,
            distribution_urls=distribution_urls,
            target_arch_repo=context.target_arch_repo,
        )
        created_resources.extend(log_resources)
        results_model.increment_counts(logs=1)

    for sbom_path in plan.sboms_to_upload:
        sbom_resources = upload_sbom(
            client,
            context,
            sbom_prn,
            date_str,
            results_model,
            sbom_path,
            distribution_urls=distribution_urls,
            target_arch_repo=context.target_arch_repo,
        )
        created_resources.extend(sbom_resources)

    for file_path, labels in plan.artifacts_to_upload:
        logging.warning("Uploading artifact: %s", os.path.basename(file_path))
        validate_file_path(file_path, "File")
        task_response = create_file_content_and_wait(
            client,
            artifacts_prn,
            file_path,
            build_id=context.build_id,
            pulp_label=labels,
            operation=f"upload file {file_path}",
        )
        if task_response.created_resources:
            created_resources.extend(task_response.created_resources)
        results_model.increment_counts(files=1)
        if distribution_urls is not None:
            fn = os.path.basename(file_path)
            arch_part = labels.get("arch") or None
            rel_path = f"{arch_part}/{fn}" if arch_part else fn
            client.add_uploaded_artifact_to_results_model(
                results_model,
                local_path=file_path,
                labels=labels,
                is_rpm=False,
                distribution_urls=distribution_urls,
                target_arch_repo=context.target_arch_repo,
                file_relative_path=rel_path,
            )
    return created_resources


def process_uploads_from_results_json(
    client: "PulpClient",
    context: UploadRpmContext,
    repositories: RepositoryRefs,
    *,
    pulp_helper: PulpHelper | None = None,
    defer_collect: bool = False,
) -> str | None | PulpResultsDocument:
    """
    Upload artifacts from pulp_results.json.

    Reads artifact keys from the JSON, resolves file paths (base_path / key),
    classifies each artifact, and uploads to the appropriate repo.
    When signed_by is set, uses signed repos and adds signed_by pulp_label.

    Args:
        client: PulpClient instance
        context: UploadRpmContext with results_json, files_base_path, signed_by
        repositories: RepositoryRefs (with signed refs when signed_by set)
        pulp_helper: Optional PulpHelper for per-arch RPM repos when ``target_arch_repo`` is set

    Returns:
        URL of the uploaded results JSON, or None if upload failed.
        When ``defer_collect`` is True, returns the populated ``PulpResultsDocument`` instead.
    """
    helper = pulp_helper or PulpHelper(client, parent_package=context.parent_package)
    distribution_urls = helper.get_distribution_urls_for_upload_context(context.build_id, context)

    if not context.results_json:
        return None

    document = _load_results_document_for_upload(
        context.results_json,
        build_id=context.build_id,
        repositories=repositories,
    )
    if document is None:
        results_model = PulpResultsDocument(build_id=context.build_id, repositories=repositories)
        if defer_collect:
            return results_model
        return collect_results(client, context, context.date_str, results_model, extra_artifacts=None)

    base_path = Path(context.files_base_path or os.path.dirname(context.results_json)).resolve()
    use_signed = bool(context.signed_by and context.signed_by.strip())
    rpm_href = (
        "" if context.target_arch_repo else (repositories.rpms_signed_href if use_signed else repositories.rpms_href)
    )
    if use_signed and not context.target_arch_repo and not rpm_href and not repositories.rpms_signed_prn:
        logging.error("signed_by set but signed repositories not available")
        raise ValueError("signed_by requires signed repositories")

    results_model = PulpResultsDocument(build_id=context.build_id, repositories=repositories)
    plan = _plan_uploads_from_document(document, base_path=base_path, context=context)
    _validate_upload_plan_repositories(plan, repositories)
    date_str = context.date_str
    created_resources = _execute_upload_plan(
        plan,
        client=client,
        context=context,
        repositories=repositories,
        results_model=results_model,
        helper=helper,
        distribution_urls=distribution_urls,
        rpm_href=rpm_href,
        date_str=date_str,
    )

    extra_artifacts = [ExtraArtifactRef(pulp_href=href) for href in created_resources]
    if defer_collect:
        return results_model
    return collect_results(client, context, date_str, results_model, extra_artifacts)


__all__ = [
    "UploadService",
    "upload_sbom",
    "collect_results",
    "process_uploads_from_results_json",
    "scan_results_json_for_log_and_sbom_keys",
    "_classify_artifact_from_key",
    "_serialize_results_to_json",
    "_save_results_to_folder",
    "_upload_and_get_results_url",
    "_extract_results_url",
    "_gather_and_validate_content",
    "_build_artifact_map",
    "_populate_results_model",
    "_add_distributions_to_results",
    "_find_artifact_content",
    "_parse_oci_reference",
    "_handle_sbom_results",
    "_distribution_urls_for_context",
]
