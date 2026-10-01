"""Update-build: mutate versioned ``pulp_results.json`` after signing / BTS uploads."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..models.context import UploadRpmContext
from ..models.pulp_results import PulpResultsDocument
from ..services.upload_collect import _write_konflux_oci_results
from ..services.upload_service import process_uploads_from_results_json
from ..utils import PulpHelper, create_labels
from ..utils.correlation import resolve_correlation_id
from ..utils.oci_pull import is_oci_artifact_reference, normalize_oci_artifact_reference
from ..utils.pulp_results_oci_publish import sync_pulp_results_with_oci_registry
from ..utils.results_json_io import load_results_document

if TYPE_CHECKING:
    from ..api.pulp_client import PulpClient


def _log_correlation_id(context: UploadRpmContext) -> None:
    cid = resolve_correlation_id(
        config_value=None,
        namespace=context.namespace,
        build_id=context.build_id,
    )
    if cid:
        logging.info("Correlation ID for update-build: %s", cid)


def run_update_build(
    client: PulpClient,
    context: UploadRpmContext,
    *,
    operation: str,
    replace_signed_by: bool,
    oci_temp_dir: Path,
) -> str | None:
    """
    Load results JSON, upload workspace artifacts, ORAS-publish updated document.

    ``context.results_json`` may be a local path or OCI digest-pinned ref.
    """
    if not context.results_json:
        raise ValueError("results_json is required for update-build")
    if not context.artifact_results or "," not in context.artifact_results.strip():
        raise ValueError("--artifact-results url_path,digest_path is required for update-build")

    _log_correlation_id(context)

    results_json_location = context.results_json.strip()
    document = load_results_document(results_json_location, dest_dir=oci_temp_dir)
    if not context.build_id:
        context.build_id = (document.build_id or "").strip()
    if not context.namespace:
        context.namespace = (document.namespace or "").strip()
    if not context.build_id or not context.namespace:
        raise ValueError("build_id and namespace required (document or CLI flags)")

    local_json = oci_temp_dir / "pulp_results_input.json"
    local_json.write_text(document.to_canonical_json(), encoding="utf-8")
    context.results_json = str(local_json)

    helper = PulpHelper(client, parent_package=context.parent_package)
    repositories = helper.setup_repositories(
        context.build_id,
        signed_by=context.signed_by,
        skip_artifacts_repo=False,
        target_arch_repo=context.target_arch_repo,
        skip_logs_repo=context.skip_logs_repo,
        skip_sbom_repo=context.skip_sbom_repo,
    )

    upload_outcome = process_uploads_from_results_json(
        client,
        context,
        repositories,
        pulp_helper=helper,
        defer_collect=True,
    )
    results_model = (
        upload_outcome
        if isinstance(upload_outcome, PulpResultsDocument)
        else PulpResultsDocument(
            build_id=context.build_id,
            repositories=repositories,
        )
    )

    verified_slots: set[str] = set()
    for key in results_model.distributions:
        verified_slots.add(str(key))
    verified_slots.update(document.distributions.keys())
    for row in document.artifacts.values():
        verified_slots.update(str(k) for k in row.distributions.keys())

    document.merge_upload_outcomes(
        results_model,
        operation=operation,
        signed_by=context.signed_by,
        replace_signed_by=replace_signed_by,
        verified_distribution_slots=verified_slots,
    )

    oci_storage = (context.oci_storage or "").strip()
    if not oci_storage:
        raise ValueError("--oci-storage is required for update-build")

    labels = create_labels(context.build_id, "", context.namespace, context.parent_package, context.date_str)
    attach_subject = (
        normalize_oci_artifact_reference(results_json_location)
        if is_oci_artifact_reference(results_json_location)
        else None
    )
    oci_ref, _task = sync_pulp_results_with_oci_registry(
        client,
        repositories.artifacts_prn,
        document,
        oci_storage,
        labels,
        build_id=context.build_id,
        operation=operation,
        attach_subject=attach_subject,
    )

    url_path, digest_path = context.artifact_results.split(",", 1)
    _write_konflux_oci_results(oci_ref, url_path.strip(), digest_path.strip())
    logging.info("update-build published pulp_results.json to %s", oci_ref)
    return oci_ref


__all__ = ["run_update_build"]
