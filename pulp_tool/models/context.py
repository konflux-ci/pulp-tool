"""Context and configuration models for Konflux Pulp operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import ConfigDict, Field, field_validator

from .base import KonfluxBaseModel
from .pulp_label_values import normalize_signed_by_value_for_pulp

if TYPE_CHECKING:
    from .rpm_repo_layout import RpmRepoLayout


class UploadContext(KonfluxBaseModel):
    """
    Base context information for upload operations.

    This is the base class containing common attributes shared by
    UploadRpmContext and UploadFilesContext.

    Attributes:
        build_id: Unique build identifier
        date_str: Build date string
        namespace: Namespace for the upload operation
        parent_package: Optional parent package name (will not be added to labels if not provided)
        config: Optional path to config file
        debug: Verbosity level (0=WARNING, 1=INFO, 2=DEBUG, 3+=DEBUG with HTTP logs)
        artifact_results: Konflux ``url_path,digest_path``, or a single folder path to write ``pulp_results.json``
            locally (no comma); local folder also skips artifacts repo and ``artifacts`` distribution URLs in JSON
        oci_storage: OCI registry (``--oci-storage`` only) for ORAS ``pulp_results.json`` publish
        sbom_results: Optional path to write SBOM results
        skip_logs_repo: When True, logs repo was not created; omit logs distribution URLs
        skip_sbom_repo: When True, SBOM repo was not created; omit sbom distribution URLs
    """

    build_id: str
    date_str: str
    namespace: str
    parent_package: str | None = None
    config: str | None = None
    debug: int = 0
    artifact_results: str | None = None
    oci_storage: str | None = None
    sbom_results: str | None = None
    skip_logs_repo: bool = False
    skip_sbom_repo: bool = False
    cluster: str | None = None


class UploadRpmContext(UploadContext):
    """
    Context information for upload operations (RPM directory-based).

    This context is used for the upload command which processes RPMs
    from directory structures organized by architecture.

    Attributes:
        rpm_path: Path to directory containing RPM files (defaults to current directory if not provided)
        sbom_path: Optional path to SBOM file (SBOM upload will be skipped if not provided)
        results_json: Optional path to pulp_results.json (upload artifacts from this file)
        files_base_path: Optional base path for resolving artifact keys to file paths (default: dir of results_json)
        signed_by: Optional string; when set, add pulp_label and use separate signed repos
        overwrite: When True, remove existing RPM package units in the target RPM repo that match
            local RPM NVRA filename (and signed_by when set) before uploading RPMs
        target_arch_repo: When True, RPM repos use architecture as name/base_path (e.g. x86_64) instead
            of build_id/rpms; created lazily per arch at upload time. With signed_by, the same per-arch
            repo is used (signed_by is label-only; no rpms-signed path segment).
        target_arch_repo_build_scoped: When True with target_arch_repo, use ``{build_id}/{arch}`` as the
            repository/distribution name (e.g. concurrent e2e) instead of global ``{arch}`` only.
    """

    rpm_path: str | None = None
    sbom_path: str | None = None
    results_json: str | None = None
    files_base_path: str | None = None
    signed_by: str | None = None
    overwrite: bool = False
    target_arch_repo: bool = False
    target_arch_repo_build_scoped: bool = False

    @field_validator("signed_by")
    @classmethod
    def normalize_signed_by_for_pulp(cls, v: str | None) -> str | None:
        """Strip and map signed_by to a pulp-safe label value when needed."""
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            return None
        return normalize_signed_by_value_for_pulp(stripped)

    def rpm_repo_layout(self) -> RpmRepoLayout:
        """RPM repository naming layout derived from ``--target-arch-repo*`` flags."""
        from .rpm_repo_layout import RpmRepoLayout

        return RpmRepoLayout.from_context(self)

    def uses_signed_aggregate_rpm_repo(self) -> bool:
        """True when RPMs use signed aggregate ``rpms-signed`` (not per-arch target repo)."""
        return bool(self.signed_by and self.signed_by.strip()) and not self.target_arch_repo


class PullContext(KonfluxBaseModel):
    """
    Context information for pull operations.

    Attributes:
        artifact_location: Path or URL to artifact metadata (can be generated from namespace+build_id)
        namespace: Optional namespace for auto-generating artifact URL (requires build_id and config)
        key_path: Optional path to SSL private key (required for remote URLs, can come from config)
        config: Path to destination Pulp config (``transfer`` command global ``--config``) for upload; or source
            ``--config`` on ``pull`` for auth/URL only
        transfer_dest: Destination config path when running ``transfer`` (enables repository setup and re-upload)
        build_id: Optional build identifier (can be used for override or with namespace for URL generation)
        side_tag: Optional side-tag name for extra release-Pulp RPM promotion (``transfer`` command only)
        artifact_results: Konflux ``url_path,digest_path`` for OCI manifest Tekton results after side-tag transfer
        oci_storage: OCI registry target (--oci-storage) for ORAS push
        snapshot_path: Optional Konflux release snapshot JSON to update (``pulpResultsOciManifest`` and/or
            ``components[].containerImage`` when ``--oras-cp-target`` is set)
        oras_cp_target: When set, ``oras cp`` the source OCI artifact to this registry target after transfer
        pulp_oras_cp_target: Provision Pulp container OCI storage (registry path ``namespace/oci/build-id``) and
            ``oras cp`` after transfer
        oras_cp_source: Optional digest-pinned source for ``oras cp``; defaults to OCI ``--artifact-location``
        cluster: Cluster identity from config (cli.cluster) for origin_cluster labels
        debug: Verbosity level (0=WARNING, 1=INFO, 2=DEBUG, 3+=DEBUG with HTTP logs)
        max_workers: Maximum number of concurrent workers
        content_types: Optional list of content types to filter (rpm, log, sbom)
        archs: Optional list of architectures to filter
        verify_rpm_gpg: When True, verify RPM GPG signatures after download (before transfer upload)
        gpg_keyring: Optional GnuPG homedir for rpm --checksig (keys imported via gpg export)
        operation_label: ``pull`` or ``transfer`` (drives transfer-only destination repo naming)
        transfer_source_config_path: Source ``cli.toml`` for ``transfer``
            (``--source-config``, or destination when omitted)
        transfer_repository_name_prefix: Set during transfer setup; ``konflux-<source-domain>/<source-repo>`` path
            prefix for destination repository base paths (upload must use the same prefix as setup)
        oci_intermediate_bundle_dir: ORAS-pulled RPM directory when ``pulp_results.json`` is absent (``transfer`` only)
        delete_local_sources_after_upload: Remove local RPM files after successful upload (ORAS bundle path)
    """

    artifact_location: str | None = None
    namespace: str | None = None
    key_path: str | None = None
    config: str | None = None
    transfer_dest: str | None = None
    build_id: str | None = None
    side_tag: str | None = None
    artifact_results: str | None = None
    oci_storage: str | None = None
    snapshot_path: str | None = None
    oras_cp_target: str | None = None
    pulp_oras_cp_target: bool = False
    oras_cp_source: str | None = None
    cluster: str | None = None
    debug: int = 0
    max_workers: int = Field(default=10, ge=1, le=100)
    content_types: list[str] | None = None
    archs: list[str] | None = None
    verify_rpm_gpg: bool = False
    gpg_keyring: str | None = None
    operation_label: str = "pull"
    transfer_source_config_path: str | None = None
    transfer_repository_name_prefix: str | None = None
    oci_intermediate_bundle_dir: str | None = None
    delete_local_sources_after_upload: bool = False

    @field_validator("content_types")
    @classmethod
    def validate_content_types(cls, v: list[str] | None) -> list[str] | None:
        """Validate that content_types only contains valid values."""
        if v is None:
            return v

        valid_types = {"rpm", "log", "sbom"}
        invalid_types = [ct for ct in v if ct not in valid_types]

        if invalid_types:
            raise ValueError(
                f"Invalid content type(s): {', '.join(invalid_types)}. "
                f"Valid types are: {', '.join(sorted(valid_types))}"
            )

        return v

    @field_validator("operation_label")
    @classmethod
    def validate_operation_label(cls, value: str) -> str:
        """Restrict to pull vs transfer for typed CLI flows."""
        label = (value or "").strip() or "pull"
        if label not in {"pull", "transfer"}:
            raise ValueError("operation_label must be 'pull' or 'transfer'")
        return label


class ArchUploadConfig(KonfluxBaseModel):
    """
    Configuration for uploading architecture-specific content.

    Attributes:
        rpm_path: Path to RPM files
        arch: Architecture name (e.g., 'x86_64', 'noarch')
        rpm_repository_href: Repository href for RPMs
        file_repository_prn: PRN for file repository (logs)
        build_id: Build identifier
        date_str: Build date string
        labels: Dictionary of labels to apply
    """

    rpm_path: str
    arch: str
    rpm_repository_href: str
    file_repository_prn: str
    build_id: str
    date_str: str
    labels: dict[str, str]


class UploadCallbacks(KonfluxBaseModel):
    """
    Callback functions for upload operations.

    Attributes:
        upload_sbom_func: Function to upload SBOM
        collect_results_func: Function to collect and save results
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    upload_sbom_func: Callable
    collect_results_func: Callable


class UploadFilesContext(UploadContext):
    """
    Context information for upload-files operations.

    This context is used for the upload-files command which processes
    individual files specified via command-line options.

    Attributes:
        rpm_files: List of RPM file paths to upload
        file_files: List of generic file paths to upload
        log_files: List of log file paths to upload
        sbom_files: List of SBOM file paths to upload
        arch: Optional architecture for RPMs (if not provided, will try to detect)
    """

    rpm_files: list[str] = Field(default_factory=list)
    file_files: list[str] = Field(default_factory=list)
    log_files: list[str] = Field(default_factory=list)
    sbom_files: list[str] = Field(default_factory=list)
    arch: str | None = None


__all__ = [
    "UploadContext",
    "UploadRpmContext",
    "PullContext",
    "ArchUploadConfig",
    "UploadCallbacks",
    "UploadFilesContext",
]
