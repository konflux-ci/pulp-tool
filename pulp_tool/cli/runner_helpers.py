"""Shared helpers for CLI commands (pull, upload-build, search-by, update-build)."""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..models.artifacts import ArtifactMetadata
from ..utils.config_manager import ConfigManager
from ..utils.oci_pull import is_oci_artifact_reference
from ..utils.oras_publish import OrasPublishError
from ..utils.results_json_io import ResultsJsonIOError, resolve_results_json_path
from ..utils.validation.build_id import sanitize_build_id_for_repository, strip_namespace_from_build_id


class PullRunnerError(Exception):
    """Invalid pull CLI inputs or artifact location resolution."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True)
class DistributionAuthSettings:
    """TLS or basic auth plus Pulp API base URL for distribution fetches."""

    cert_path: str | None = None
    key_path: str | None = None
    username: str | None = None
    password: str | None = None
    pulp_api_base_url: str | None = None

    @property
    def has_cert_auth(self) -> bool:
        return bool(self.cert_path and self.key_path)

    @property
    def has_basic_auth(self) -> bool:
        return self.username is not None and self.password is not None

    @property
    def has_any_auth(self) -> bool:
        return self.has_cert_auth or self.has_basic_auth


def _expand_config_path(raw: str) -> str | None:
    expanded = os.path.expanduser(raw.strip())
    return expanded if os.path.exists(expanded) else None


def load_distribution_auth_from_config(
    *,
    auth_config_path: str | None,
    cert_path: str | None = None,
    key_path: str | None = None,
    username: str | None = None,
    password: str | None = None,
    pulp_api_base_url: str | None = None,
) -> DistributionAuthSettings:
    """Load distribution auth fields from config when not already set on the CLI."""
    if not auth_config_path:
        return DistributionAuthSettings(
            cert_path=cert_path,
            key_path=key_path,
            username=username,
            password=password,
            pulp_api_base_url=pulp_api_base_url,
        )
    try:
        config_manager = ConfigManager(auth_config_path)
        config_manager.load()
        if not cert_path:
            loaded_cert = config_manager.get("cli.cert")
            if loaded_cert and isinstance(loaded_cert, str) and loaded_cert.strip():
                cert_path = _expand_config_path(loaded_cert)
        if not key_path:
            loaded_key = config_manager.get("cli.key")
            if loaded_key and isinstance(loaded_key, str) and loaded_key.strip():
                key_path = _expand_config_path(loaded_key)
        if username is None:
            raw_user = config_manager.get("cli.username")
            username = str(raw_user).strip() if raw_user else None
        if password is None:
            raw_pass = config_manager.get("cli.password")
            password = str(raw_pass) if raw_pass is not None else None
        if pulp_api_base_url is None:
            loaded_base = config_manager.get("cli.base_url")
            if loaded_base and isinstance(loaded_base, str) and loaded_base.strip():
                pulp_api_base_url = loaded_base.strip()
    except Exception as e:
        logging.debug("Could not load auth from config %s: %s", auth_config_path, e)
    return DistributionAuthSettings(
        cert_path=cert_path,
        key_path=key_path,
        username=username,
        password=password,
        pulp_api_base_url=pulp_api_base_url,
    )


def resolve_pulp_api_base_url_for_remote(
    *,
    artifact_location: str,
    auth: DistributionAuthSettings,
    fallback_config_paths: tuple[str | None, ...],
) -> DistributionAuthSettings:
    """Fill ``pulp_api_base_url`` from alternate config files when the artifact URL is remote."""
    if not artifact_location.startswith(("http://", "https://")) or auth.pulp_api_base_url:
        return auth
    for base_config_path in fallback_config_paths:
        if not base_config_path:
            continue
        try:
            base_manager = ConfigManager(base_config_path)
            base_manager.load()
            loaded_base = base_manager.get("cli.base_url")
            if loaded_base and isinstance(loaded_base, str) and loaded_base.strip():
                return DistributionAuthSettings(
                    cert_path=auth.cert_path,
                    key_path=auth.key_path,
                    username=auth.username,
                    password=auth.password,
                    pulp_api_base_url=loaded_base.strip(),
                )
        except Exception as e:
            logging.debug("Could not load cli.base_url from %s: %s", base_config_path, e)
    return auth


def validate_remote_pull_auth(artifact_location: str, auth: DistributionAuthSettings) -> None:
    """Raise ``PullRunnerError`` when a remote artifact location lacks auth or base URL."""
    if not artifact_location.startswith(("http://", "https://")):
        return
    if not auth.has_any_auth:
        raise PullRunnerError(
            "Authentication required for remote URLs. Provide either (cert, key) or (username, password) "
            "via --distribution-config, --transfer-dest, --config, --cert-path, or --key-path."
        )
    if not auth.pulp_api_base_url:
        raise PullRunnerError(
            "cli.base_url in config is required for remote --artifact-location (fetch allowlist uses Pulp API host)."
        )


def resolve_artifact_location_for_pull(
    *,
    artifact_location: str | None,
    namespace: str | None,
    build_id: str | None,
    source_config_path: str | None,
    dest_config_path: str | None,
    oci_dest_dir: Path | None = None,
) -> str:
    """
    Resolve pull artifact location: validate flags, synthesize build-id URL, or ORAS-pull OCI refs.

    Args:
        oci_dest_dir: When set, OCI manifest references are pulled into this directory.

    Returns:
        Local path or HTTPS URL to ``pulp_results.json``.
    """
    if artifact_location and (namespace or build_id):
        raise PullRunnerError("Cannot use --artifact-location with --build-id and --namespace")

    location = artifact_location
    if namespace or build_id:
        if not (namespace and build_id):
            raise PullRunnerError("Both --build-id and --namespace must be provided together")
        metadata_config_path = source_config_path or dest_config_path
        if not metadata_config_path:
            raise PullRunnerError("--config is required when using --build-id and --namespace")
        config_manager = ConfigManager(metadata_config_path)
        config_manager.load()
        base_url = config_manager.get("cli.base_url")
        content_build_id = sanitize_build_id_for_repository(strip_namespace_from_build_id(build_id))
        location = f"{base_url}/api/pulp-content/{namespace}/{content_build_id}/artifacts/pulp_results.json"
        logging.info("Auto-generated artifact location: %s", location)
    elif not location:
        raise PullRunnerError("Either --artifact-location OR (--build-id AND --namespace) must be provided")

    if location and is_oci_artifact_reference(location):
        if oci_dest_dir is None:
            raise PullRunnerError("Internal error: OCI artifact location requires oci_dest_dir")
        try:
            local_json = resolve_results_json_path(location, oci_dest_dir)
            logging.info("ORAS-pulled pulp_results.json to %s", local_json)
            return str(local_json)
        except (OrasPublishError, ResultsJsonIOError) as e:
            raise PullRunnerError(str(e)) from e
    return location


@contextmanager
def oci_pull_tempdir(prefix: str = "pulp-tool-oras-pull-") -> Iterator[Path]:
    """Temporary directory for ORAS-pulled ``pulp_results.json`` (auto cleanup)."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(tmp)


def resolve_results_json_local_path(
    location: str,
    *,
    oci_dest_dir: Path | None,
    prefix: str = "pulp-tool-oras-pull-",
) -> tuple[str, tempfile.TemporaryDirectory[str] | None]:
    """
    Resolve a results JSON path or OCI reference to a local filesystem path.

    Returns:
        Tuple of (local path, temporary directory handle or None).
    """
    loc = location.strip()
    if is_oci_artifact_reference(loc):
        if oci_dest_dir is not None:
            try:
                local_path = resolve_results_json_path(loc, oci_dest_dir)
                return str(local_path), None
            except ResultsJsonIOError as e:
                raise PullRunnerError(str(e)) from e
        temp = tempfile.TemporaryDirectory(prefix=prefix)
        try:
            local_path = resolve_results_json_path(loc, Path(temp.name))
            return str(local_path), temp
        except ResultsJsonIOError as e:
            temp.cleanup()
            raise PullRunnerError(str(e)) from e
    path = Path(loc).expanduser().resolve()
    if not path.is_file():
        raise PullRunnerError(f"results JSON not found: {path}")
    return str(path), None


def artifact_row_from_json(row: object) -> ArtifactMetadata | None:
    """Coerce a JSON artifact row to ``ArtifactMetadata``; return None if invalid."""
    if isinstance(row, ArtifactMetadata):
        return row
    if isinstance(row, dict):
        try:
            return ArtifactMetadata.model_validate(row)
        except Exception:
            return None
    return None


__all__ = [
    "DistributionAuthSettings",
    "PullRunnerError",
    "artifact_row_from_json",
    "load_distribution_auth_from_config",
    "oci_pull_tempdir",
    "resolve_artifact_location_for_pull",
    "resolve_pulp_api_base_url_for_remote",
    "resolve_results_json_local_path",
    "validate_remote_pull_auth",
]
