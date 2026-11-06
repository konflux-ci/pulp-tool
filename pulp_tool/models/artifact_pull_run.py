"""CLI options and resolved settings for ``pull`` / ``transfer`` artifact flows."""

from __future__ import annotations

import logging
from typing import Self

from pydantic import Field, field_validator, model_validator

from ..utils.config_manager import ConfigManager
from ..utils.oci_storage_resolve import resolve_oci_storage
from .base import KonfluxBaseModel
from .context import PullContext


def _strip_optional_str(value: object) -> object:
    if value is None or not isinstance(value, str):
        return value
    stripped = value.strip()
    return stripped or None


class SideTagResolution(KonfluxBaseModel):
    """Resolved side-tag ORAS target and cluster from destination config."""

    resolved_oci_storage: str | None = None
    cluster: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_message is None


class GpgPullSettings(KonfluxBaseModel):
    """Effective GPG verification settings for transfer."""

    verify_rpm_gpg: bool = False
    gpg_keyring: str | None = None


class ArtifactPullRunOptions(KonfluxBaseModel):
    """Inputs for ``run_artifact_pull_flow`` (``pull`` or ``transfer``)."""

    artifact_location: str | None = None
    content_types: str | None = None
    archs: str | None = None
    cert_path: str | None = None
    key_path: str | None = None
    source_config_path: str | None = None
    dest_config_path: str | None = None
    distribution_config: str | None = None
    side_tag: str | None = None
    artifact_results: str | None = None
    snapshot_path: str | None = None
    oci_storage: str | None = None
    verify_rpm_gpg: bool = False
    gpg_keyring: str | None = None
    namespace: str | None = None
    build_id: str | None = None
    debug: int = 0
    max_workers: int = Field(default=4, ge=1, le=100)
    operation_label: str = "pull"

    @field_validator(
        "artifact_location",
        "source_config_path",
        "dest_config_path",
        "distribution_config",
        "side_tag",
        "snapshot_path",
        "gpg_keyring",
        "cert_path",
        "key_path",
        mode="before",
    )
    @classmethod
    def strip_optional_strings(cls, value: object) -> object:
        return _strip_optional_str(value)

    @field_validator("operation_label")
    @classmethod
    def validate_operation_label(cls, value: str) -> str:
        label = (value or "").strip() or "pull"
        if label not in {"pull", "transfer"}:
            raise ValueError("operation_label must be 'pull' or 'transfer'")
        return label

    @model_validator(mode="after")
    def transfer_requires_dest_config(self) -> Self:
        if self.operation_label == "transfer" and not self.dest_config_path:
            raise ValueError("dest_config_path is required for transfer")
        return self

    def parsed_content_types(self) -> list[str] | None:
        if not self.content_types:
            return None
        return [part.strip() for part in self.content_types.split(",") if part.strip()]

    def parsed_archs(self) -> list[str] | None:
        if not self.archs:
            return None
        return [part.strip() for part in self.archs.split(",") if part.strip()]

    def distribution_auth_config_path(self) -> str | None:
        return self.distribution_config or self.source_config_path or self.dest_config_path

    def pulp_client_config_path(self) -> str | None:
        return self.dest_config_path or self.source_config_path

    def resolve_side_tag(self) -> SideTagResolution:
        if not self.side_tag:
            return SideTagResolution()
        if not self.dest_config_path:
            return SideTagResolution(
                error_message="Error: --side-tag requires destination --config (use the transfer command)",
            )
        resolved_oci_storage = resolve_oci_storage(self.oci_storage, self.dest_config_path)
        cluster: str | None = None
        try:
            transfer_cfg = ConfigManager(self.dest_config_path)
            transfer_cfg.load()
            raw_cluster = transfer_cfg.get("cli.cluster")
            cluster = str(raw_cluster).strip() if raw_cluster else None
        except Exception as exc:
            logging.debug("Could not load destination config for side-tag: %s", exc)
        if not resolved_oci_storage:
            return SideTagResolution(
                cluster=cluster,
                error_message=(
                    "Error: --oci-storage (or cli.oci_storage in destination --config) "
                    "is required when using --side-tag"
                ),
            )
        return SideTagResolution(resolved_oci_storage=resolved_oci_storage, cluster=cluster)

    def resolve_gpg(self) -> GpgPullSettings:
        verify_enabled = self.verify_rpm_gpg
        keyring_path = self.gpg_keyring
        if not self.dest_config_path:
            return GpgPullSettings(verify_rpm_gpg=verify_enabled, gpg_keyring=keyring_path)
        try:
            transfer_cfg = ConfigManager(self.dest_config_path)
            transfer_cfg.load()
            if not verify_enabled:
                raw_verify = transfer_cfg.get("cli.verify_rpm_gpg")
                verify_enabled = bool(raw_verify) if raw_verify is not None else False
            if not keyring_path:
                raw_keyring = transfer_cfg.get("cli.gpg_keyring")
                keyring_path = str(raw_keyring).strip() if raw_keyring else None
        except Exception as exc:
            logging.debug("Could not load destination config for GPG settings: %s", exc)
        return GpgPullSettings(verify_rpm_gpg=verify_enabled, gpg_keyring=keyring_path)

    def to_pull_context(
        self,
        *,
        resolved_artifact_location: str,
        auth_key_path: str | None,
        side_tag: SideTagResolution,
        gpg: GpgPullSettings,
    ) -> PullContext:
        source_cfg = self.source_config_path or self.dest_config_path
        return PullContext(
            artifact_location=resolved_artifact_location,
            namespace=self.namespace,
            key_path=auth_key_path,
            config=self.pulp_client_config_path(),
            transfer_dest=self.dest_config_path,
            build_id=self.build_id,
            side_tag=self.side_tag,
            artifact_results=self.artifact_results,
            oci_storage=side_tag.resolved_oci_storage,
            snapshot_path=self.snapshot_path,
            cluster=side_tag.cluster,
            debug=self.debug,
            max_workers=self.max_workers,
            content_types=self.parsed_content_types(),
            archs=self.parsed_archs(),
            verify_rpm_gpg=gpg.verify_rpm_gpg,
            gpg_keyring=gpg.gpg_keyring,
            operation_label=self.operation_label,
            transfer_source_config_path=source_cfg,
        )


__all__ = [
    "ArtifactPullRunOptions",
    "GpgPullSettings",
    "SideTagResolution",
]
