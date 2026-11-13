"""Post-transfer OCI copy (``oras cp`` / Pulp container-push) + snapshot ``containerImage`` updates."""

from __future__ import annotations

import logging
from pathlib import Path

from ..api.pulp_client.client import PulpClient
from ..models.context import PullContext
from ..utils.oci_pull import is_oci_artifact_reference, normalize_oci_artifact_reference
from ..utils.oras_publish import OrasPublishError, copy_oci_artifact
from ..utils.pulp_container_oci import (
    PulpContainerOciError,
    provision_pulp_oras_cp_target,
    pulp_registry_oras_destination_flags,
    write_pulp_registry_auth_config,
)
from ..utils.snapshot_update import update_snapshot_component_container_images

logger = logging.getLogger(__name__)


def _resolve_copy_source(context: PullContext) -> str:
    source = (getattr(context, "oras_cp_source", None) or "").strip()
    if not source:
        source = (context.artifact_location or "").strip()
    if not is_oci_artifact_reference(source):
        raise ValueError("--oras-cp-source or digest-pinned OCI --artifact-location is required for OCI copy")
    return normalize_oci_artifact_reference(source)


def _require_snapshot_path(context: PullContext) -> str:
    snapshot_path = (getattr(context, "snapshot_path", None) or "").strip()
    if not snapshot_path:
        raise ValueError("--snapshot-path is required when using --oras-cp-target or --pulp-oras-cp-target")
    return snapshot_path


def _apply_snapshot_update(context: PullContext, source: str, new_ref: str) -> None:
    snapshot_path = _require_snapshot_path(context)
    updated = update_snapshot_component_container_images(
        snapshot_path,
        new_ref,
        match_source_ref=source,
    )
    logger.info(
        "Updated %d snapshot component(s) containerImage -> %s (%s)",
        updated,
        new_ref,
        snapshot_path,
    )
    if updated == 0:
        logger.warning(
            "No snapshot components matched source containerImage %s; snapshot unchanged except prior fields",
            source,
        )


def finalize_transfer_oras_copy(context: PullContext) -> None:
    """
    When ``--oras-cp-target`` is set, copy the source OCI artifact and rewrite snapshot ``containerImage``.

    Mirrors the release workspace pattern from ``upload-src-rpm-sbom-attestation`` (mutate snapshot JSON
    before ``create-trusted-artifact``), but updates ``components[].containerImage`` instead of
    ``rpmsToPublish`` SBOM paths.
    """
    target = (getattr(context, "oras_cp_target", None) or "").strip()
    if not target:
        return

    source = _resolve_copy_source(context)
    _require_snapshot_path(context)
    logger.info("oras cp %s -> %s after transfer", source, target)
    try:
        new_ref = copy_oci_artifact(source, target)
    except OrasPublishError as exc:
        raise ValueError(str(exc)) from exc
    _apply_snapshot_update(context, source, new_ref)


def finalize_transfer_pulp_oras_cp(context: PullContext) -> None:
    """
    When ``--pulp-oras-cp-target`` is set, provision Pulp container registry storage (path ``namespace/oci/build-id``),
    ``oras cp`` the source bundle into it, and rewrite snapshot ``containerImage``.
    """
    if not getattr(context, "pulp_oras_cp_target", False):
        return

    source = _resolve_copy_source(context)
    _require_snapshot_path(context)

    config_path = (context.transfer_dest or context.config or "").strip()
    if not config_path:
        raise ValueError("destination --config is required for --pulp-oras-cp-target")

    client = PulpClient.create_from_config_file(
        config_path,
        correlation_namespace=context.namespace,
        correlation_build_id=context.build_id,
    )
    try:
        try:
            target = provision_pulp_oras_cp_target(client, context.namespace, context.build_id)
        except PulpContainerOciError as exc:
            raise ValueError(str(exc)) from exc

        registry_host = target.split("/", 1)[0]
        extra_registry_config = write_pulp_registry_auth_config(client, registry_host)
        destination_flags = pulp_registry_oras_destination_flags(client)
        tls_cert = client.cert if client.config.get("cert") else None
        try:
            logger.info("oras cp %s -> %s (Pulp container-push) after transfer", source, target)
            new_ref = copy_oci_artifact(
                source,
                target,
                extra_registry_config_path=extra_registry_config,
                client_tls_cert=tls_cert,
                destination_cp_flags=destination_flags,
            )
        except OrasPublishError as exc:
            raise ValueError(str(exc)) from exc
        finally:
            Path(extra_registry_config).unlink(missing_ok=True)
    finally:
        client.close()

    _apply_snapshot_update(context, source, new_ref)


def finalize_transfer_oci_post_copy(context: PullContext) -> None:
    """Run post-transfer OCI copy for ``--oras-cp-target`` and/or ``--pulp-oras-cp-target``."""
    if (getattr(context, "oras_cp_target", None) or "").strip():
        finalize_transfer_oras_copy(context)
    if getattr(context, "pulp_oras_cp_target", False):
        finalize_transfer_pulp_oras_cp(context)


__all__ = [
    "finalize_transfer_oci_post_copy",
    "finalize_transfer_oras_copy",
    "finalize_transfer_pulp_oras_cp",
]
