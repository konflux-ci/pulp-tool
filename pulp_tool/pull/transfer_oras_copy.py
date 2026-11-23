"""Post-transfer OCI copy (``oras cp`` / Pulp container-push) + snapshot ``containerImage`` updates."""

from __future__ import annotations

import logging
from typing import Any

from ..api.pulp_client.client import PulpClient
from ..models.context import PullContext
from ..utils.oci_pull import is_oci_artifact_reference, normalize_oci_artifact_reference
from ..utils.oras_publish import OrasPublishError, copy_oci_artifact
from ..utils.pulp_container_oci import (
    PulpContainerOciError,
    provision_pulp_oras_cp_target,
    uses_pulp_container_registry,
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


def _transfer_pulp_oras_copy_kwargs(context: PullContext) -> tuple[PulpClient, dict[str, Any]]:
    """Build ``copy_oci_artifact`` auth kwargs when destination Pulp config is available."""
    config_path = (context.transfer_dest or context.config or "").strip()
    if not config_path:
        raise ValueError("destination --config is required for Pulp registry oras cp auth")
    extra_cfg_paths: list[str] = []
    source_cfg = (getattr(context, "transfer_source_config_path", None) or "").strip()
    if source_cfg:
        extra_cfg_paths.append(source_cfg)
    client = PulpClient.create_from_config_file(
        config_path,
        correlation_namespace=context.namespace,
        correlation_build_id=context.build_id,
    )
    tls_cert = client.cert if client.config.get("cert") else None
    return client, {
        "pulp_client": client,
        "extra_config_paths": tuple(extra_cfg_paths),
        "client_tls_cert": tls_cert,
    }


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
    client: PulpClient | None = None
    try:
        copy_kwargs: dict[str, Any] = {}
        if (context.transfer_dest or context.config or "").strip():
            pulp_client, all_kwargs = _transfer_pulp_oras_copy_kwargs(context)
            if uses_pulp_container_registry(source, pulp_client) or uses_pulp_container_registry(target, pulp_client):
                copy_kwargs = all_kwargs
                client = pulp_client
            else:
                pulp_client.close()
        new_ref = copy_oci_artifact(source, target, **copy_kwargs)
    except OrasPublishError as exc:
        raise ValueError(str(exc)) from exc
    finally:
        if client is not None:
            client.close()
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

        extra_cfg_paths: list[str] = []
        source_cfg = (getattr(context, "transfer_source_config_path", None) or "").strip()
        if source_cfg:
            extra_cfg_paths.append(source_cfg)
        tls_cert = client.cert if client.config.get("cert") else None
        try:
            logger.info("oras cp %s -> %s (Pulp container-push) after transfer", source, target)
            new_ref = copy_oci_artifact(
                source,
                target,
                pulp_client=client,
                extra_config_paths=tuple(extra_cfg_paths),
                client_tls_cert=tls_cert,
            )
        except OrasPublishError as exc:
            raise ValueError(str(exc)) from exc
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
