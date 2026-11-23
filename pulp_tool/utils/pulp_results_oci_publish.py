"""Upload ``pulp_results.json`` to Pulp and ORAS (shared by upload-build and pull side-tag)."""

from __future__ import annotations

import logging

from ..api import PulpClient
from ..models.pulp_api import TaskResponse
from ..models.pulp_results import (
    BUILD_UPLOAD_OPERATION,
    PULP_RESULTS_SCHEMA_VERSION,
    PulpResultsDocument,
    document_last_updated,
    schema_version,
)
from .constants import RESULTS_JSON_FILENAME
from .oras_publish import (
    OrasPublishError,
    attach_pulp_results_manifest,
    push_pulp_results_manifest,
    resolve_oci_manifest,
)
from .pulp_container_oci import pulp_registry_oras_auth, uses_pulp_container_registry
from .pulp_tasks import create_file_content_and_wait


def _format_oci_ref(image_ref: str, digest: str) -> str:
    digest_value = digest if digest.startswith("sha256:") else f"sha256:{digest}"
    return f"{image_ref}@{digest_value}"


def sync_pulp_results_with_oci_registry(
    pulp_client: PulpClient,
    artifacts_prn: str,
    document: PulpResultsDocument,
    oci_storage: str,
    pulp_label: dict[str, str],
    *,
    build_id: str,
    operation: str = BUILD_UPLOAD_OPERATION,
    record_manifest_history: bool | None = None,
    attach_subject: str | None = None,
    attach_to_resolved_subject: bool = False,
) -> tuple[str, TaskResponse]:
    """
    Upload results JSON to Pulp and ORAS.

    OCI identity is the registry digest (``repo@sha256:…``); it is **not** stored inside ``pulp_results.json``.
    Registry lineage uses OCI referrers / Tekton ``--artifact-results``, not JSON history fields.

    When ``attach_subject`` is set (digest-pinned ``repo@sha256:…``), publish uses ``oras attach`` to
    the subject instead of ``oras push`` to ``oci_storage`` (``update-build``), preserving attestations
    on the original OCI object.

    When ``attach_to_resolved_subject`` is true (``upload-build`` after import-to-quay RPM ORAS push),
    resolve ``oci_storage`` and attach ``pulp_results.json`` to that manifest so RPM layers are not
    replaced.

    Returns ``(oci_ref, last_pulp_task_response)`` where ``oci_ref`` is ``image@sha256:…``.
    """
    target = oci_storage.strip()
    if not target:
        raise ValueError("oci_storage is required")

    document.normalize_in_place()
    if document.last_updated is None or not str(document.last_updated).strip():
        document.touch_last_updated()

    should_mutate = (
        record_manifest_history if record_manifest_history is not None else bool((attach_subject or "").strip())
    )
    if should_mutate:
        document.prepare_for_mutation(operation=operation)

    def upload_to_pulp(upload_operation: str) -> TaskResponse:
        labels = dict(pulp_label)
        try:
            labels["document_schema_version"] = str(document.version or schema_version(document.to_canonical_dict()))
            labels["document_last_updated"] = str(
                document.last_updated or document_last_updated(document.to_canonical_dict())
            )
        except (TypeError, ValueError):
            labels["document_schema_version"] = PULP_RESULTS_SCHEMA_VERSION
            labels["document_last_updated"] = document_last_updated({})
        return create_file_content_and_wait(
            pulp_client,
            artifacts_prn,
            document.to_canonical_json(),
            build_id=build_id,
            pulp_label=labels,
            filename=RESULTS_JSON_FILENAME,
            operation=upload_operation,
        )

    def _with_pulp_registry_auth(refs: list[str]):
        unique = [r for r in refs if r and uses_pulp_container_registry(r, pulp_client)]
        auth_ref = unique[0] if unique else target
        return pulp_registry_oras_auth(pulp_client, auth_ref)

    def oras_publish() -> tuple[str, str]:
        payload = document.to_canonical_json()
        try:
            auth_refs = [target]
            if attach_subject:
                auth_refs.insert(0, attach_subject.strip())
            with _with_pulp_registry_auth(auth_refs) as (reg_override, tls):
                if attach_subject:
                    if reg_override:
                        return attach_pulp_results_manifest(
                            attach_subject,
                            payload,
                            client_tls_cert=tls,
                            registry_config_override=reg_override,
                        )
                    return attach_pulp_results_manifest(attach_subject, payload)
                if attach_to_resolved_subject:
                    if reg_override:
                        subject_image_ref, subject_digest = resolve_oci_manifest(
                            target,
                            client_tls_cert=tls,
                            registry_config_override=reg_override,
                        )
                    else:
                        subject_image_ref, subject_digest = resolve_oci_manifest(target)
                    subject_ref = _format_oci_ref(subject_image_ref, subject_digest)
                    with pulp_registry_oras_auth(pulp_client, subject_ref) as (attach_reg, attach_tls):
                        if attach_reg:
                            return attach_pulp_results_manifest(
                                subject_ref,
                                payload,
                                client_tls_cert=attach_tls,
                                registry_config_override=attach_reg,
                            )
                        return attach_pulp_results_manifest(subject_ref, payload)
                if reg_override:
                    return push_pulp_results_manifest(
                        target,
                        payload,
                        client_tls_cert=tls,
                        registry_config_override=reg_override,
                    )
                return push_pulp_results_manifest(target, payload)
        except OrasPublishError as e:
            logging.error("ORAS publish failed: %s", e)
            raise

    used_attach = bool((attach_subject or "").strip()) or attach_to_resolved_subject
    last_task = upload_to_pulp("upload pulp_results.json before ORAS publish")
    image_ref, digest = oras_publish()
    if not used_attach:
        with pulp_registry_oras_auth(pulp_client, target) as (reg_override, tls):
            if reg_override:
                image_ref, digest = resolve_oci_manifest(
                    target,
                    client_tls_cert=tls,
                    registry_config_override=reg_override,
                )
            else:
                image_ref, digest = resolve_oci_manifest(target)
    last_task = upload_to_pulp("upload final pulp_results.json after ORAS publish")

    oci_ref = _format_oci_ref(image_ref, digest)
    logging.info("pulp_results.json published to OCI at %s", oci_ref)
    return oci_ref, last_task


__all__ = ["sync_pulp_results_with_oci_registry"]
