"""ORAS CLI integration for publishing pulp_results.json OCI manifests."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, cast

from pulp_tool.models.pulp_results import PULP_RESULTS_ORAS_MEDIA_TYPE

from .constants import RESULTS_JSON_FILENAME
from .oci_reference import oci_storage_oras_target, oci_storage_repository_name

logger = logging.getLogger(__name__)

SELECT_OCI_AUTH = "select-oci-auth"


class OrasPublishError(RuntimeError):
    """ORAS push or resolve failed."""


def _select_oci_auth_binary() -> str:
    path = shutil.which(SELECT_OCI_AUTH)
    if not path:
        raise OrasPublishError(
            f"{SELECT_OCI_AUTH} not found on PATH; required for ORAS registry auth in Konflux "
            "(install via pulp-tool-container image or build-trusted-artifacts select-oci-auth.sh)"
        )
    return path


def _load_registry_auths(path: str) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrasPublishError(f"Invalid registry config at {path}: {exc}") from exc
    auths = data.get("auths")
    return auths if isinstance(auths, dict) else {}


def _write_merged_registry_config(*paths: str) -> str:
    merged: dict[str, dict[str, str]] = {}
    for path in paths:
        merged.update(_load_registry_auths(path))
    body = {"auths": merged}
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(body, tmp)
    tmp.close()
    return tmp.name


@contextmanager
def _oci_registry_config(oci_target: str, *, extra_registry_config_path: str | None = None) -> Iterator[str]:
    """
    Build a Docker-style registry config for ``oci_target`` via Konflux ``select-oci-auth``.

    Reads credentials from ``AUTHFILE`` or ``$HOME/.docker/config.json`` (Tekton-injected merged secrets).
    """
    auth_bin = _select_oci_auth_binary()
    auth_result = subprocess.run(
        [auth_bin, oci_target.strip()],
        capture_output=True,
        text=True,
        check=False,
    )
    if auth_result.returncode != 0:
        raise OrasPublishError(
            f"{SELECT_OCI_AUTH} failed (exit {auth_result.returncode}): {auth_result.stderr or auth_result.stdout}"
        )
    config_body = auth_result.stdout or ""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        tmp.write(config_body)
        config_path = tmp.name
    merged_path: str | None = None
    try:
        if extra_registry_config_path:
            merged_path = _write_merged_registry_config(config_path, extra_registry_config_path)
            yield merged_path
        else:
            yield config_path
    finally:
        Path(config_path).unlink(missing_ok=True)
        if merged_path:
            Path(merged_path).unlink(missing_ok=True)


def _run_oras(
    args: list[str],
    oci_target: str,
    *,
    cwd: str | Path | None = None,
    extra_registry_config_path: str | None = None,
    client_tls_cert: tuple[str, str] | None = None,
    destination_cp_flags: list[str] | None = None,
    registry_config_override: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if registry_config_override:
        cmd = ["oras", "--registry-config", registry_config_override, *args]
        if client_tls_cert and client_tls_cert[0] and client_tls_cert[1]:
            cmd.extend(["--cert", client_tls_cert[0], "--key", client_tls_cert[1]])
        return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)

    subcommand = args[0] if args else ""
    split_cp_destination = bool(subcommand == "cp" and extra_registry_config_path)
    merge_for_non_cp = extra_registry_config_path if not split_cp_destination else None

    with _oci_registry_config(oci_target, extra_registry_config_path=merge_for_non_cp) as registry_config:
        if subcommand == "cp":
            # ``oras cp`` does not accept root-level ``--registry-config`` (unlike push/resolve/pull).
            cp_tail = args[1:]
            from_config = registry_config
            to_config = cast(str, extra_registry_config_path) if split_cp_destination else registry_config
            cmd = [
                "oras",
                "cp",
                "--from-registry-config",
                from_config,
                "--to-registry-config",
                to_config,
            ]
            if client_tls_cert and client_tls_cert[0] and client_tls_cert[1]:
                cmd.extend(
                    [
                        "--to-cert-file",
                        client_tls_cert[0],
                        "--to-key-file",
                        client_tls_cert[1],
                    ]
                )
            if destination_cp_flags:
                cmd.extend(destination_cp_flags)
            cmd.extend(cp_tail)
        else:
            cmd = ["oras", "--registry-config", registry_config, *args]
            if client_tls_cert and client_tls_cert[0] and client_tls_cert[1]:
                cmd.extend(["--cert", client_tls_cert[0], "--key", client_tls_cert[1]])
        return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)


def _parse_oras_resolve_output(oci_storage: str, resolved: str) -> tuple[str, str]:
    """Parse ``oras resolve`` stdout (full ref or digest-only) into Konflux-style repo + digest."""
    repository_name = oci_storage_repository_name(oci_storage)
    text = resolved.strip()
    if not text:
        raise OrasPublishError("oras resolve returned empty output")
    if "@" in text:
        image_ref, digest = text.rsplit("@", 1)
        return oci_storage_repository_name(image_ref), digest
    if text.startswith("sha256:"):
        return repository_name, text
    raise OrasPublishError(f"oras resolve returned unexpected value: {text}")


def _parse_oras_json_digest(stdout: str, repository_name: str) -> tuple[str, str]:
    """Parse ``(repo, digest)`` from ``oras --format json`` stdout (push/attach)."""
    text = (stdout or "").strip()
    if not text:
        raise OrasPublishError("oras returned empty JSON output")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise OrasPublishError(f"oras JSON output parse failed: {e}") from e
    if not isinstance(data, dict):
        raise OrasPublishError(f"oras JSON output must be an object, got: {type(data).__name__}")
    digest = str(data.get("digest") or "").strip()
    if not digest:
        raise OrasPublishError(f"oras JSON output missing digest: {text[:200]}")
    if not digest.startswith("sha256:"):
        digest = f"sha256:{digest}"
    ref = str(data.get("reference") or data.get("name") or repository_name).strip()
    repo = oci_storage_repository_name(ref) if ref else repository_name
    return repo, digest


def resolve_oci_manifest(
    oci_storage: str,
    *,
    extra_registry_config_path: str | None = None,
    client_tls_cert: tuple[str, str] | None = None,
    registry_config_override: str | None = None,
) -> tuple[str, str]:
    """Resolve ``oci_storage`` to (image_ref_without_digest, digest with sha256: prefix)."""
    target = oci_storage.strip()
    if not target:
        raise OrasPublishError("oci_storage target is empty")

    oras_ref = oci_storage_oras_target(target)
    resolve_result = _run_oras(
        ["resolve", oras_ref],
        target,
        extra_registry_config_path=extra_registry_config_path,
        client_tls_cert=client_tls_cert,
        registry_config_override=registry_config_override or extra_registry_config_path,
    )
    if resolve_result.returncode != 0:
        raise OrasPublishError(
            f"oras resolve failed (exit {resolve_result.returncode}): {resolve_result.stderr or resolve_result.stdout}"
        )
    return _parse_oras_resolve_output(target, resolve_result.stdout or "")


def push_pulp_results_manifest(oci_storage: str, json_content: str) -> tuple[str, str]:
    """
    ORAS-push JSON to ``oci_storage`` and return (image_ref_without_digest, digest).

    ``digest`` includes the ``sha256:`` prefix when returned by oras.
    """
    target = oci_storage.strip()
    if not target:
        raise OrasPublishError("oci_storage target is empty")

    oras_ref = oci_storage_oras_target(target)
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / RESULTS_JSON_FILENAME
        artifact_path.write_text(json_content, encoding="utf-8")
        logger.info("ORAS push to %s", oras_ref)
        push_result = _run_oras(
            [
                "push",
                oras_ref,
                f"{RESULTS_JSON_FILENAME}:{PULP_RESULTS_ORAS_MEDIA_TYPE}",
            ],
            target,
            cwd=tmpdir,
        )
        if push_result.returncode != 0:
            raise OrasPublishError(
                f"oras push failed (exit {push_result.returncode}): {push_result.stderr or push_result.stdout}"
            )

        return resolve_oci_manifest(target)


def copy_oci_artifact(
    source_ref: str,
    target_storage: str,
    *,
    extra_registry_config_path: str | None = None,
    client_tls_cert: tuple[str, str] | None = None,
    destination_cp_flags: list[str] | None = None,
) -> str:
    """
    Copy *source_ref* to ``target_storage`` with ``oras cp`` and return digest-pinned ``repo@sha256:…``.

    Used after ``transfer`` to publish the build OCI bundle into release ``ociStorage`` and record the
    new ref on the Konflux snapshot (``components[].containerImage``).
    """
    from .oci_pull import normalize_oci_artifact_reference

    source = normalize_oci_artifact_reference(source_ref.strip())
    if not source or "@" not in source:
        raise OrasPublishError("oras cp source must be digest-pinned (repo@sha256:…)")
    target = oci_storage_oras_target(target_storage)
    if not target:
        raise OrasPublishError("oras cp target is empty")

    logger.info("ORAS cp %s -> %s", source, target)
    cp_result = _run_oras(
        ["cp", source, target],
        source,
        extra_registry_config_path=extra_registry_config_path,
        client_tls_cert=client_tls_cert,
        destination_cp_flags=destination_cp_flags,
    )
    if cp_result.returncode != 0:
        raise OrasPublishError(f"oras cp failed (exit {cp_result.returncode}): {cp_result.stderr or cp_result.stdout}")
    repo, digest = resolve_oci_manifest(
        target_storage,
        client_tls_cert=client_tls_cert,
        registry_config_override=extra_registry_config_path,
    )
    return f"{repo}@{digest}"


def attach_pulp_results_manifest(subject_ref: str, json_content: str) -> tuple[str, str]:
    """
    ORAS-attach updated ``pulp_results.json`` to an existing digest-pinned subject.

    Preserves the subject manifest and attestation chain; returns (repo, digest) for the **referrer**
    artifact created by attach.
    """
    from .oci_pull import normalize_oci_artifact_reference

    subject = normalize_oci_artifact_reference(subject_ref.strip())
    if not subject or "@" not in subject:
        raise OrasPublishError("attach subject must be digest-pinned (repo@sha256:…)")
    digest_part = subject.rsplit("@", 1)[-1]
    if not digest_part.startswith("sha256:"):
        raise OrasPublishError(f"attach subject must use sha256 digest, got: {subject_ref!r}")
    repository_name = oci_storage_repository_name(subject.rsplit("@", 1)[0])

    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / RESULTS_JSON_FILENAME
        artifact_path.write_text(json_content, encoding="utf-8")
        logger.info("ORAS attach pulp_results to subject %s", subject)
        attach_result = _run_oras(
            [
                "attach",
                "--artifact-type",
                PULP_RESULTS_ORAS_MEDIA_TYPE,
                "--format",
                "json",
                subject,
                f"{RESULTS_JSON_FILENAME}:{PULP_RESULTS_ORAS_MEDIA_TYPE}",
            ],
            subject,
            cwd=tmpdir,
        )
        if attach_result.returncode != 0:
            raise OrasPublishError(
                f"oras attach failed (exit {attach_result.returncode}): {attach_result.stderr or attach_result.stdout}"
            )
        return _parse_oras_json_digest(attach_result.stdout or "", repository_name)


__all__ = [
    "OrasPublishError",
    "attach_pulp_results_manifest",
    "copy_oci_artifact",
    "push_pulp_results_manifest",
    "resolve_oci_manifest",
]
