"""Upload ``pulp_results.json`` to Pulp and ORAS (shared by upload-build and pull side-tag)."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..api import PulpClient
from ..models.pulp_api import TaskResponse
from .constants import RESULTS_JSON_FILENAME
from .oras_publish import OrasPublishError, push_pulp_results_manifest, resolve_oci_manifest
from .pulp_results_document import append_oci_manifest_history, set_oci_manifest
from .pulp_tasks import create_file_content_and_wait


def _ensure_document_version(document: dict[str, Any]) -> None:
    if document.get("version") is None:
        document["version"] = 1


def _document_to_json(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2)


def sync_pulp_results_with_oci_registry(
    pulp_client: PulpClient,
    artifacts_prn: str,
    document: dict[str, Any],
    oci_storage: str,
    pulp_label: dict[str, str],
    *,
    build_id: str,
    record_manifest_history: bool = False,
) -> tuple[str, TaskResponse]:
    """
    Upload results JSON to Pulp and ORAS, embedding ``oci_manifest`` aligned with the registry digest.

    Returns ``(oci_ref, last_pulp_task_response)`` where ``oci_ref`` is ``image@sha256:…``.
    """
    target = oci_storage.strip()
    if not target:
        raise ValueError("oci_storage is required")

    if record_manifest_history:
        append_oci_manifest_history(document)
    _ensure_document_version(document)

    def upload_to_pulp(operation: str) -> TaskResponse:
        return create_file_content_and_wait(
            pulp_client,
            artifacts_prn,
            _document_to_json(document),
            build_id=build_id,
            pulp_label=pulp_label,
            filename=RESULTS_JSON_FILENAME,
            operation=operation,
        )

    def oras_push() -> tuple[str, str]:
        try:
            return push_pulp_results_manifest(target, _document_to_json(document))
        except OrasPublishError as e:
            logging.error("ORAS publish failed: %s", e)
            raise

    last_task = upload_to_pulp("upload pulp_results.json before ORAS publish")
    image_ref, digest = oras_push()
    set_oci_manifest(document, image_ref, digest)

    upload_to_pulp("upload pulp_results.json with oci_manifest after ORAS push")
    image_ref, digest = oras_push()
    set_oci_manifest(document, image_ref, digest)

    image_ref, digest = resolve_oci_manifest(target)
    set_oci_manifest(document, image_ref, digest)
    last_task = upload_to_pulp("upload final pulp_results.json aligned with OCI registry digest")

    digest_value = digest if digest.startswith("sha256:") else f"sha256:{digest}"
    oci_ref = f"{image_ref}@{digest_value}"
    logging.info("pulp_results.json published to OCI at %s", oci_ref)
    return oci_ref, last_task


__all__ = ["sync_pulp_results_with_oci_registry"]
