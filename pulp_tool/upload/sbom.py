"""SBOM upload for the upload pipeline."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from ..models.context import UploadContext
from ..models.pulp_results import PulpResultsDocument
from ..utils.pulp_tasks import create_file_content_and_wait
from ..utils.validation import validate_file_path
from .artifacts import create_labels

if TYPE_CHECKING:
    from ..api.pulp_client import PulpClient


def upload_sbom(
    client: PulpClient,
    context: UploadContext,
    sbom_repository_prn: str,
    date: str,
    results_model: PulpResultsDocument,
    sbom_path: str,
    *,
    distribution_urls: dict[str, str] | None = None,
    target_arch_repo: bool = False,
    target_arch_repo_build_scoped: bool = False,
) -> list[str]:
    """Upload SBOM file to repository."""
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
            target_arch_repo_build_scoped=target_arch_repo_build_scoped,
            file_relative_path=rel_path,
        )

    return task_response.created_resources
