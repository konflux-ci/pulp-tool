"""Publish merged pulp_results.json after side-tag pull transfer."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..api import PulpClient
from ..models.artifacts import ArtifactData
from ..models.context import PullContext
from ..models.results import PulpResultsModel
from ..services.upload_collect import _write_konflux_oci_results
from ..utils import PulpHelper, create_labels, determine_build_id
from ..utils.pulp_results_document import (
    SideTagRpmTransfer,
    apply_side_tag_transfer_to_document,
    document_from_artifact_json,
)
from ..utils.pulp_results_oci_publish import sync_pulp_results_with_oci_registry
from ..utils.snapshot_update import update_snapshot_pulp_results_manifest


def publish_side_tag_results(
    pulp_client: PulpClient,
    artifact_data: ArtifactData,
    context: PullContext,
    upload_info: PulpResultsModel,
    transfers: list[SideTagRpmTransfer],
) -> None:
    """
    Merge side-tag transfer into pulp_results.json, upload to Pulp, ORAS-push, and write Tekton results.
    """
    side_tag = (context.side_tag or "").strip()
    if not side_tag or not transfers:
        return

    oci_storage = (context.oci_storage or "").strip()
    artifact_results = (context.artifact_results or "").strip()
    if not oci_storage:
        raise ValueError("--oci-storage or cli.oci_storage is required for side-tag transfer")

    build_id = determine_build_id(context, artifact_json=artifact_data.artifact_json)
    parent_package = None
    for meta in artifact_data.artifacts.values():
        if meta.parent_package:
            parent_package = meta.parent_package
            break

    helper = PulpHelper(pulp_client, parent_package=parent_package)
    _repo_href, distribution_base = helper.ensure_side_tag_rpm_repository(build_id, side_tag)

    source_doc = document_from_artifact_json(artifact_data.artifact_json)
    merged = apply_side_tag_transfer_to_document(
        source_doc,
        transfers,
        side_tag=side_tag,
        top_level_side_tag_distribution_url=distribution_base,
    )

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    labels = create_labels(build_id, "", context.namespace or "", parent_package, date_str)

    oci_ref, _task = sync_pulp_results_with_oci_registry(
        pulp_client,
        upload_info.repositories.artifacts_prn,
        merged,
        oci_storage,
        labels,
        build_id=build_id,
        record_manifest_history=True,
    )

    if artifact_results and "," in artifact_results:
        url_path, digest_path = artifact_results.split(",", 1)
        _write_konflux_oci_results(oci_ref, url_path, digest_path)

    snapshot_path = (getattr(context, "snapshot_path", None) or "").strip()
    if snapshot_path:
        update_snapshot_pulp_results_manifest(snapshot_path, oci_ref)

    logging.info("Side-tag transfer published; OCI manifest at %s", oci_ref)


__all__ = ["publish_side_tag_results"]
