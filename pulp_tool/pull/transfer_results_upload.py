"""Upload merged ``pulp_results.json`` to the destination artifacts repo after ``transfer``."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..api import PulpClient
from ..models.artifacts import ArtifactData
from ..models.context import PullContext
from ..models.pulp_results import (
    PULP_RESULTS_SCHEMA_VERSION,
    TRANSFER_ARTIFACTS_UPLOAD_OPERATION,
    PulpResultsDocument,
    document_last_updated,
    schema_version,
)
from ..upload.artifacts import create_labels
from ..utils import determine_build_id
from ..utils.constants import RESULTS_JSON_FILENAME
from ..utils.pulp_tasks import create_file_content_and_wait


def upload_transfer_pulp_results_json_to_artifacts(
    pulp_client: PulpClient,
    artifact_data: ArtifactData,
    upload_info: PulpResultsDocument,
    context: PullContext,
) -> None:
    """
    Persist ``pulp_results.json`` on the **destination** artifacts repo (non-side-tag ``transfer``).

    Side-tag ``transfer`` already publishes an updated document via
    :func:`~pulp_tool.pull.publish.publish_side_tag_results`.
    RPM-only pulls (e.g. ``--content-types rpm``) otherwise never upload file artifacts, so release-Pulp
    validation would see an empty artifacts repository.
    """
    if (context.operation_label or "").strip() != "transfer":
        return
    if (context.side_tag or "").strip():
        return
    repos = upload_info.repositories
    artifacts_prn = (getattr(repos, "artifacts_prn", None) or "").strip() if repos else ""
    if not artifacts_prn:
        return

    build_id = determine_build_id(context, artifact_json=artifact_data.artifact_json)
    parent_package = None
    for meta in artifact_data.artifacts.values():
        if meta.parent_package:
            parent_package = meta.parent_package
            break

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    labels = create_labels(build_id, "", context.namespace or "", parent_package, date_str)

    doc = PulpResultsDocument.from_artifact_json(artifact_data.artifact_json)
    doc.repositories = repos

    verified_slots: set[str] = set()
    for key in doc.distributions:
        verified_slots.add(str(key))
    verified_slots.update(artifact_data.artifact_json.distributions.keys())
    for row in artifact_data.artifacts.values():
        verified_slots.update(str(k) for k in row.distributions.keys())

    doc.merge_upload_outcomes(
        upload_info,
        operation=TRANSFER_ARTIFACTS_UPLOAD_OPERATION,
        signed_by=None,
        replace_signed_by=False,
        verified_distribution_slots=verified_slots,
    )

    doc.touch_last_updated()
    doc.normalize_in_place()
    doc.prepare_for_mutation(operation=TRANSFER_ARTIFACTS_UPLOAD_OPERATION)

    try:
        labels["document_schema_version"] = str(doc.version or schema_version(doc.to_canonical_dict()))
        labels["document_last_updated"] = str(
            doc.last_updated or document_last_updated(doc.to_canonical_dict()),
        )
    except (TypeError, ValueError):
        labels["document_schema_version"] = PULP_RESULTS_SCHEMA_VERSION
        labels["document_last_updated"] = document_last_updated({})

    logging.info(
        "Uploading pulp_results.json to destination artifacts repository after transfer (build_id=%s)",
        build_id,
    )
    create_file_content_and_wait(
        pulp_client,
        artifacts_prn,
        doc.to_canonical_json(),
        build_id=build_id,
        pulp_label=labels,
        filename=RESULTS_JSON_FILENAME,
        operation="upload pulp_results.json after transfer",
    )
    upload_info.uploaded_counts.files += 1


__all__ = ["upload_transfer_pulp_results_json_to_artifacts"]
