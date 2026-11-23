"""ORAS CLI integration for publishing pulp_results.json OCI manifests."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Literal, Sequence, cast

if TYPE_CHECKING:
    from pulp_tool.api.pulp_client.client import PulpClient

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


def merge_registry_config_paths(*paths: str) -> str:
    """Merge Docker ``auths`` from multiple registry config files (later paths override host keys)."""
    return _write_merged_registry_config(*paths)


def registry_config_has_auth_for_host(config_path: str, registry_host: str) -> bool:
    """Return whether ``config_path`` carries HTTP auth for ``registry_host`` (or ``host:443``)."""
    auths = _load_registry_auths(config_path)
    hosts = {registry_host}
    if ":" not in registry_host:
        hosts.add(f"{registry_host}:443")
    for host in hosts:
        entry = auths.get(host)
        if not isinstance(entry, dict):
            continue
        if entry.get("auth") or entry.get("identitytoken"):
            return True
    return False


def select_oci_auth_registry_config_path(oci_target: str) -> str:
    """
    Run Konflux ``select-oci-auth`` for ``oci_target`` and return a temp config path.

    Caller must delete the file when done (``Path.unlink``).
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
        return tmp.name


@contextmanager
def _oci_registry_config(oci_target: str, *, extra_registry_config_path: str | None = None) -> Iterator[str]:
    """
    Build a Docker-style registry config for ``oci_target`` via Konflux ``select-oci-auth``.

    Reads credentials from ``AUTHFILE`` or ``$HOME/.docker/config.json`` (Tekton-injected merged secrets).
    """
    config_path = select_oci_auth_registry_config_path(oci_target)
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


def _is_oras_auth_failure(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    text = f"{result.stderr or ''}{result.stdout or ''}".lower()
    return any(
        marker in text
        for marker in (
            "unauthorized",
            "denied",
            "not authorized",
            "authentication required",
            "access to the requested resource is not authorized",
        )
    )


def _select_registry_config_for_cp(
    oci_ref: str,
    *,
    client: PulpClient | None,
    extra_config_paths: Sequence[str],
    side: Literal["from", "to"],
) -> str:
    """
    Run ``select-oci-auth`` for ``oci_ref``, merging Pulp registry Basic Auth when needed.

    Konflux ``select-oci-auth`` often omits ``packages.redhat.com``; sibling ``username``/``password`` from
    ``--config`` / ``--source-config`` must still be applied for Pulp container-registry push.
    """
    from .pulp_container_oci import (
        _pulp_registry_credentials,
        build_pulp_cp_registry_config_for_ref,
        oci_ref_registry_host,
        uses_pulp_container_registry,
    )

    select_path = select_oci_auth_registry_config_path(oci_ref)
    pulp_temp: str | None = None
    try:
        if client is None or not uses_pulp_container_registry(oci_ref, client):
            return select_path
        registry_host = oci_ref_registry_host(oci_ref)
        if registry_config_has_auth_for_host(select_path, registry_host):
            return select_path
        if not _pulp_registry_credentials(client, extra_config_paths):
            return select_path
        pulp_temp, _flags = build_pulp_cp_registry_config_for_ref(
            client,
            oci_ref,
            extra_config_paths=extra_config_paths,
            side=side,
        )
        if not pulp_temp:
            return select_path
        merged = merge_registry_config_paths(select_path, pulp_temp)
        Path(select_path).unlink(missing_ok=True)
        Path(pulp_temp).unlink(missing_ok=True)
        return merged
    except OrasPublishError:
        if pulp_temp:
            Path(pulp_temp).unlink(missing_ok=True)
        return select_path


def _run_oras_cp_hybrid(
    source: str,
    target: str,
    *,
    from_registry_config: str | None = None,
    to_registry_config: str | None = None,
    from_client_tls_cert: tuple[str, str] | None = None,
    to_client_tls_cert: tuple[str, str] | None = None,
    from_cp_flags: list[str] | None = None,
    destination_cp_flags: list[str] | None = None,
    pulp_client: PulpClient | None = None,
    extra_config_paths: Sequence[str] = (),
) -> subprocess.CompletedProcess[str]:
    """
    Run ``oras cp`` with explicit per-side registry configs.

    Sides set to ``None`` use Konflux ``select-oci-auth`` for that ref.
    """
    created: list[str] = []
    try:
        from_config = from_registry_config
        if from_config is None:
            from_config = _select_registry_config_for_cp(
                source,
                client=pulp_client,
                extra_config_paths=extra_config_paths,
                side="from",
            )
            created.append(from_config)
        to_config = to_registry_config
        if to_config is None:
            to_config = _select_registry_config_for_cp(
                target,
                client=pulp_client,
                extra_config_paths=extra_config_paths,
                side="to",
            )
            created.append(to_config)
        cmd = [
            "oras",
            "cp",
            "--from-registry-config",
            from_config,
            "--to-registry-config",
            to_config,
        ]
        if from_client_tls_cert and from_client_tls_cert[0] and from_client_tls_cert[1]:
            cmd.extend(
                [
                    "--from-cert-file",
                    from_client_tls_cert[0],
                    "--from-key-file",
                    from_client_tls_cert[1],
                ]
            )
        if to_client_tls_cert and to_client_tls_cert[0] and to_client_tls_cert[1]:
            cmd.extend(
                [
                    "--to-cert-file",
                    to_client_tls_cert[0],
                    "--to-key-file",
                    to_client_tls_cert[1],
                ]
            )
        if from_cp_flags:
            cmd.extend(from_cp_flags)
        if destination_cp_flags:
            cmd.extend(destination_cp_flags)
        cmd.extend([source, target])
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    finally:
        for path in created:
            Path(path).unlink(missing_ok=True)


def _oras_cp_with_pulp_auth_fallback(
    client: PulpClient,
    source: str,
    target: str,
    *,
    extra_config_paths: Sequence[str] = (),
) -> tuple[subprocess.CompletedProcess[str], str | None, tuple[str, str] | None, list[str]]:
    """
    ``oras cp`` for transfer: Pulp ``cli.toml`` basic auth first, ``select-oci-auth`` on auth failure.

    Returns ``(cp_result, to_registry_config_for_resolve, to_tls_cert, temp_paths_to_unlink)``.
    """
    from .pulp_container_oci import (
        build_pulp_cp_registry_config_for_ref,
        uses_pulp_container_registry,
    )

    paths: list[str] = []
    extra = tuple(extra_config_paths)
    tls = client.cert if client.config.get("cert") else None
    from_pulp = uses_pulp_container_registry(source, client)
    to_pulp = uses_pulp_container_registry(target, client)

    from_cfg, from_flags = (
        build_pulp_cp_registry_config_for_ref(client, source, extra_config_paths=extra, side="from")
        if from_pulp
        else (None, [])
    )
    to_cfg, to_flags = (
        build_pulp_cp_registry_config_for_ref(client, target, extra_config_paths=extra, side="to")
        if to_pulp
        else (None, [])
    )
    if from_cfg:
        paths.append(from_cfg)
    if to_cfg:
        paths.append(to_cfg)

    used_pulp_config = bool(from_cfg or to_cfg)
    from_tls = tls if from_pulp and tls else None
    to_tls = tls if to_pulp and tls else None

    def _unlink_configs(*except_paths: str | None) -> None:
        skip = {p for p in except_paths if p}
        for path in paths:
            if path not in skip:
                Path(path).unlink(missing_ok=True)

    result = _run_oras_cp_hybrid(
        source,
        target,
        from_registry_config=from_cfg,
        to_registry_config=to_cfg,
        from_client_tls_cert=from_tls,
        to_client_tls_cert=to_tls,
        from_cp_flags=from_flags or None,
        destination_cp_flags=to_flags or None,
        pulp_client=client,
        extra_config_paths=extra,
    )
    if result.returncode == 0:
        _unlink_configs(to_cfg)
        defer = [to_cfg] if to_cfg else []
        return result, to_cfg, to_tls, defer
    if used_pulp_config and _is_oras_auth_failure(result):
        logger.warning(
            "Pulp cli.toml registry auth failed for oras cp; falling back to select-oci-auth (source=%s, target=%s)",
            source,
            target,
        )
        _unlink_configs()
        result = _run_oras_cp_hybrid(
            source,
            target,
            from_registry_config=None if from_cfg else from_cfg,
            to_registry_config=None if to_cfg else to_cfg,
            from_client_tls_cert=from_tls,
            to_client_tls_cert=to_tls,
            from_cp_flags=None if from_cfg else (from_flags or None),
            destination_cp_flags=None if to_cfg else (to_flags or None),
            pulp_client=client,
            extra_config_paths=extra,
        )
        return result, None, to_tls if to_pulp else None, []
    _unlink_configs()
    return result, None, None, []


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


def push_pulp_results_manifest(
    oci_storage: str,
    json_content: str,
    *,
    client_tls_cert: tuple[str, str] | None = None,
    registry_config_override: str | None = None,
) -> tuple[str, str]:
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
            client_tls_cert=client_tls_cert,
            registry_config_override=registry_config_override,
        )
        if push_result.returncode != 0:
            raise OrasPublishError(
                f"oras push failed (exit {push_result.returncode}): {push_result.stderr or push_result.stdout}"
            )

        return resolve_oci_manifest(
            target,
            client_tls_cert=client_tls_cert,
            registry_config_override=registry_config_override,
        )


def copy_oci_artifact(
    source_ref: str,
    target_storage: str,
    *,
    extra_registry_config_path: str | None = None,
    client_tls_cert: tuple[str, str] | None = None,
    destination_cp_flags: list[str] | None = None,
    pulp_client: PulpClient | None = None,
    extra_config_paths: Sequence[str] = (),
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
    resolve_override: str | None = extra_registry_config_path
    resolve_tls = client_tls_cert
    tempfile_paths: list[str] = []
    try:
        if pulp_client is not None:
            cp_result, resolve_override, resolve_tls, tempfile_paths = _oras_cp_with_pulp_auth_fallback(
                pulp_client,
                source,
                target,
                extra_config_paths=extra_config_paths,
            )
        else:
            cp_result = _run_oras(
                ["cp", source, target],
                source,
                extra_registry_config_path=extra_registry_config_path,
                client_tls_cert=client_tls_cert,
                destination_cp_flags=destination_cp_flags,
            )
        if cp_result.returncode != 0:
            raise OrasPublishError(
                f"oras cp failed (exit {cp_result.returncode}): {cp_result.stderr or cp_result.stdout}"
            )
        repo, digest = resolve_oci_manifest(
            target_storage,
            client_tls_cert=resolve_tls,
            registry_config_override=resolve_override,
            extra_registry_config_path=resolve_override,
        )
        return f"{repo}@{digest}"
    finally:
        for path in tempfile_paths:
            Path(path).unlink(missing_ok=True)


def attach_pulp_results_manifest(
    subject_ref: str,
    json_content: str,
    *,
    client_tls_cert: tuple[str, str] | None = None,
    registry_config_override: str | None = None,
) -> tuple[str, str]:
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
            client_tls_cert=client_tls_cert,
            registry_config_override=registry_config_override,
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
    "merge_registry_config_paths",
    "push_pulp_results_manifest",
    "registry_config_has_auth_for_host",
    "resolve_oci_manifest",
    "select_oci_auth_registry_config_path",
]
