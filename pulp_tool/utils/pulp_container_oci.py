"""Provision Pulp container-push OCI storage and copy artifacts after ``transfer``."""

from __future__ import annotations

import base64
import json
import logging
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Sequence
from urllib.parse import urlencode, urlparse

import httpx

from ..exceptions import PulpToolHTTPError
from ..models.pulp_api import DistributionRequest, RepositoryRequest
from .pulp_tasks import wait_for_successful_task
from .repository_manager import _is_distribution_uniqueness_error
from .validation import sanitize_build_id_for_repository, validate_build_id

if TYPE_CHECKING:
    from ..api.pulp_client.client import PulpClient

logger = logging.getLogger(__name__)

CONTAINER_PUSH_REPO_ENDPOINT = "api/v3/repositories/container/container-push/"
CONTAINER_DISTRIBUTION_ENDPOINT = "api/v3/distributions/container/container/"

DEFAULT_ORAS_TAG = "latest"
CONTAINER_REGISTRY_PATH_SEGMENT = "oci"

# Konflux Tekton tasks mount the ``pulp-access`` secret (not only ``cli.toml``).
_KONFLUX_PULP_ACCESS_MOUNT_DIRS = (Path("/etc/pulp-access"), Path("/pulp-access"))


class PulpContainerOciError(RuntimeError):
    """Pulp container-push provisioning or teardown failed."""


def pulp_container_oci_object_name(namespace: str | None, build_id: str | None) -> str:
    """
    Return the Pulp container distribution ``name`` and registry ``base_path``.

    Uses ``{namespace}/oci/{build_id}`` (each segment sanitized). The ``oci`` segment avoids pulpcore
    ``base_path`` overlap with transfer RPM/file distributions under ``{namespace}/{build_id}/…``.
    """
    ns = sanitize_build_id_for_repository((namespace or "").strip() or "default")
    bid_raw = (build_id or "").strip()
    if not bid_raw:
        raise PulpContainerOciError("build_id is required for --pulp-oras-cp-target")
    bid = sanitize_build_id_for_repository(bid_raw)
    if not validate_build_id(bid):
        raise PulpContainerOciError(f"Invalid build_id for Pulp container OCI storage: {build_id!r}")
    return f"{ns}/{CONTAINER_REGISTRY_PATH_SEGMENT}/{bid}"


def _container_distribution_api_name(registry_base_path: str) -> str:
    """
    Pulp distribution ``name`` (API filter) must not contain ``/``; registry ``base_path`` uses ``/``.
    """
    return registry_base_path.strip().replace("/", "__")


def oci_ref_registry_host(oci_reference: str) -> str:
    """Registry hostname from an OCI reference (strips tag, digest, and ``oci:`` prefix)."""
    ref = oci_reference.strip()
    if ref.startswith("oci:"):
        ref = ref[4:].strip()
    if "@" in ref:
        ref = ref.split("@", 1)[0]
    if not ref or "/" not in ref:
        return ref
    return ref.split("/", 1)[0]


def uses_pulp_container_registry(oci_reference: str, client: PulpClient) -> bool:
    """
    True when ``oci_reference`` targets the Pulp container registry.

    Matches ``packages.redhat.com`` explicitly, or the registry host from ``cli.toml`` when
    ``cli.base_url`` is a Pulp endpoint (not unrelated registries that happen to share a hostname).
    """
    host = oci_ref_registry_host(oci_reference).lower()
    if host == "packages.redhat.com":
        return True
    base_url = str(client.config.get("base_url", "")).lower()
    if "packages.redhat.com" not in base_url:
        return False
    try:
        return host == _registry_host_from_cli_config(client.config).lower()
    except PulpContainerOciError:
        return False


@contextmanager
def pulp_registry_oras_auth(
    client: PulpClient,
    oci_reference: str,
    *,
    extra_config_paths: Sequence[str] = (),
) -> Iterator[tuple[str | None, tuple[str, str] | None]]:
    """
    Yield ``(registry_config_path, client_tls_cert)`` for ORAS against Pulp's registry.

    Uses ``[cli].username``/``[cli].password`` from Pulp config (not ``select-oci-auth``).
    """
    if not uses_pulp_container_registry(oci_reference, client):
        yield None, None
        return
    from .oci_reference import oci_storage_oras_target

    ref_for_auth = oci_reference.strip()
    if "@" not in ref_for_auth:
        ref_for_auth = oci_storage_oras_target(ref_for_auth)
    config_path, _flags = build_pulp_destination_registry_config(
        client,
        ref_for_auth,
        extra_config_paths=extra_config_paths,
    )
    tls_cert = client.cert if client.config.get("cert") else None
    try:
        yield config_path, tls_cert
    finally:
        Path(config_path).unlink(missing_ok=True)


def _registry_host_from_cli_config(cli_config: dict[str, str | int]) -> str:
    for key in ("container_registry", "oci_registry"):
        raw = cli_config.get(key)
        if raw:
            host = str(raw).strip().rstrip("/")
            if "://" in host:
                return urlparse(host).netloc or host.split("://", 1)[1].split("/", 1)[0]
            return host.split("/", 1)[0]
    base_url = str(cli_config.get("base_url", "")).strip()
    if not base_url:
        raise PulpContainerOciError("cli.base_url or cli.container_registry is required for Pulp OCI registry push")
    parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    if not host:
        raise PulpContainerOciError(f"Could not derive container registry host from base_url={base_url!r}")
    return host


def oras_copy_target_for_base_path(
    cli_config: dict[str, str | int],
    base_path: str,
    *,
    tag: str = DEFAULT_ORAS_TAG,
) -> str:
    """Build ``registry/host/{base_path}:{tag}`` for ``oras cp``."""
    host = _registry_host_from_cli_config(cli_config)
    path = base_path.strip().strip("/")
    if not path:
        raise PulpContainerOciError("container distribution base_path is empty")
    return f"{host}/{path}:{tag}"


def _registry_auth_hosts(registry_host: str) -> set[str]:
    hosts = {registry_host}
    if ":" not in registry_host:
        hosts.add(f"{registry_host}:443")
    return hosts


def _write_registry_auth_file(registry_host: str, auths: dict[str, dict[str, str]]) -> str:
    body = {"auths": auths}
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(body, tmp)
    tmp.close()
    return tmp.name


def _credential_search_dirs(client: PulpClient, extra_config_paths: Sequence[str] = ()) -> list[Path]:
    """Directories that may hold Konflux ``username`` / ``password`` files beside ``cli.toml`` or TLS material."""
    seen: set[Path] = set()
    dirs: list[Path] = []

    def add(candidate: Path | str) -> None:
        try:
            resolved = Path(candidate).resolve()
        except OSError:
            return
        if resolved not in seen:
            seen.add(resolved)
            dirs.append(resolved)

    if isinstance(client.config_path, Path):
        add(client.config_path.parent)
    for mount_dir in _KONFLUX_PULP_ACCESS_MOUNT_DIRS:
        add(mount_dir)
    if client.config.get("cert"):
        try:
            cert_path, _ = client.cert
            if cert_path:
                add(Path(cert_path).parent)
        except Exception:
            logger.debug("Could not resolve client cert path for registry credential search", exc_info=True)
    for raw in extra_config_paths:
        text = str(raw).strip()
        if text:
            add(Path(text).parent)
    return dirs


def _basic_auth_from_pulp_cli_toml(config_path: str) -> tuple[str, str] | None:
    """Read ``[cli].username`` / ``[cli].password`` from a Pulp ``cli.toml`` file."""
    path = Path(config_path).expanduser()
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    cli = data.get("cli")
    if not isinstance(cli, dict):
        return None
    return _basic_auth_from_cli_mapping(cli)


def _basic_auth_from_cli_mapping(cli: dict[str, Any]) -> tuple[str, str] | None:
    username = cli.get("username")
    password = cli.get("password")
    if username is None or password is None:
        return None
    user = str(username).strip()
    secret = str(password).strip()
    if not user or not secret:
        return None
    return user, secret


def _read_credentials_from_pulp_access_secret_dir(
    client: PulpClient,
    extra_config_paths: Sequence[str] = (),
) -> tuple[str, str] | None:
    """
    Konflux ``pulp-access`` secrets mount ``username`` / ``password`` files beside ``cli.toml``.

    Certificate-auth ``cli.toml`` often omits those keys even when terms-based registry creds exist.
    """
    for parent in _credential_search_dirs(client, extra_config_paths):
        user_file = parent / "username"
        pass_file = parent / "password"
        if not user_file.is_file() or not pass_file.is_file():
            continue
        user = user_file.read_text(encoding="utf-8").strip()
        secret = pass_file.read_text(encoding="utf-8").strip()
        if user and secret:
            return user, secret
    return None


def _pulp_registry_credentials(
    client: PulpClient,
    extra_config_paths: Sequence[str] = (),
) -> tuple[str, str] | None:
    """
    Return ``(username, password)`` for Pulp container-registry HTTP auth from Pulp ``cli.toml``.

    OAuth (``client_id``/``client_secret``) is API-only. Konflux ``pulp-access`` sibling ``username`` /
    ``password`` files (terms-based registry) take precedence over ``[cli].username``/``password`` in
    destination ``--config``, which may hold Pulp API Basic Auth instead of registry credentials.
    Then other ``cli.toml`` paths (``--source-config``), then inline ``[cli]`` fields on the active client.
    """
    from_secrets = _read_credentials_from_pulp_access_secret_dir(client, extra_config_paths)
    if from_secrets:
        return from_secrets
    for raw in extra_config_paths:
        from_extra = _basic_auth_from_pulp_cli_toml(str(raw).strip())
        if from_extra:
            return from_extra
    if isinstance(client.config_path, Path):
        from_dest_file = _basic_auth_from_pulp_cli_toml(str(client.config_path))
        if from_dest_file:
            return from_dest_file
    return _basic_auth_from_cli_mapping(client.config)


def pulp_registry_oras_destination_flags(
    client: PulpClient,
    extra_config_paths: Sequence[str] = (),
) -> list[str]:
    """Extra ``oras cp`` flags for the Pulp destination registry (explicit auth)."""
    creds = _pulp_registry_credentials(client, extra_config_paths)
    if not creds:
        return []
    user, secret = creds
    return ["--to-username", user, "--to-password", secret]


def pulp_registry_oras_source_flags(
    client: PulpClient,
    extra_config_paths: Sequence[str] = (),
) -> list[str]:
    """Extra ``oras cp`` flags for the Pulp source registry (explicit auth)."""
    creds = _pulp_registry_credentials(client, extra_config_paths)
    if not creds:
        return []
    user, secret = creds
    return ["--from-username", user, "--from-password", secret]


def build_pulp_cp_registry_config_for_ref(
    client: PulpClient,
    oci_reference: str,
    *,
    extra_config_paths: Sequence[str] = (),
    side: Literal["from", "to"],
) -> tuple[str | None, list[str]]:
    """
    Build ``oras cp`` registry config for one side of a copy when targeting Pulp's container registry.

    Uses ``[cli].username``/``[cli].password`` (or Konflux sibling secret files) only — never
    ``select-oci-auth``. Returns ``(None, [])`` when the ref is not Pulp's registry or no creds/TLS apply.
    """
    if not uses_pulp_container_registry(oci_reference, client):
        return None, []
    from .oci_reference import oci_storage_oras_target

    ref_for_host = oci_reference.strip()
    if "@" not in ref_for_host and side == "to":
        ref_for_host = oci_storage_oras_target(ref_for_host)
    registry_host = ref_for_host.split("/", 1)[0]
    creds = _pulp_registry_credentials(client, extra_config_paths)
    if creds:
        logger.info(
            "Pulp container-registry oras cp (%s): using terms-based registry Basic Auth for %s",
            side,
            registry_host,
        )
        path = write_pulp_registry_auth_config(client, registry_host, extra_config_paths=extra_config_paths)
        # ``auths`` in the registry config file are enough; duplicate ``--to-*`` flags confuse ORAS.
        return path, []
    if client.config.get("cert"):
        return _write_empty_auths_registry_config(registry_host), []
    return None, []


def write_pulp_registry_auth_config(
    client: PulpClient,
    registry_host: str,
    *,
    extra_config_paths: Sequence[str] = (),
) -> str:
    """
    Write a Docker ``config.json`` fragment with registry credentials from the Pulp CLI config.

    Supports HTTP basic (``cli.username``/``cli.password``) or mTLS-only (empty ``auths``) when
    ``cert``/``key`` are set.
    """
    creds = _pulp_registry_credentials(client, extra_config_paths)
    if creds:
        user, secret = creds
        token = base64.b64encode(f"{user}:{secret}".encode()).decode("ascii")
        auths = {host: {"auth": token} for host in _registry_auth_hosts(registry_host)}
        return _write_registry_auth_file(registry_host, auths)

    if client.config.get("cert"):
        return _write_empty_auths_registry_config(registry_host)
    raise PulpContainerOciError(
        "Pulp registry push requires cli.username/cli.password in destination --config, "
        "or use build_pulp_destination_registry_config with a full destination ref"
    )


def build_pulp_destination_registry_config(
    client: PulpClient,
    destination_ref: str,
    *,
    extra_config_paths: Sequence[str] = (),
) -> tuple[str, list[str]]:
    """
    Build ``--to-registry-config`` (and optional ``oras cp --to-*`` flags) for Pulp container-registry push.

    Pulp registry auth uses ``[cli].username``/``[cli].password`` from destination and ``extra_config_paths``
    ``cli.toml`` files when present (no ``select-oci-auth`` in that case). Otherwise falls back to
    ``select-oci-auth``, then mTLS-only empty ``auths`` when ``cert``/``key`` are set.
    """
    from .oras_publish import (
        OrasPublishError,
        registry_config_has_auth_for_host,
        select_oci_auth_registry_config_path,
    )

    registry_host = destination_ref.split("/", 1)[0]
    creds = _pulp_registry_credentials(client, extra_config_paths)
    if creds:
        logger.info("Pulp container-registry push: using terms-based registry Basic Auth for %s", registry_host)
    elif client.config.get("cert"):
        logger.warning(
            "Pulp container-registry push: no Basic Auth creds resolved for %s; "
            "using client TLS only (ensure pulp-access mounts username/password or set cli.username/cli.password)",
            registry_host,
        )
    else:
        logger.warning(
            "Pulp container-registry push: no cli Basic Auth for %s; falling back to select-oci-auth or failing",
            registry_host,
        )

    cli_path: str | None = None
    if creds:
        cli_path = write_pulp_registry_auth_config(client, registry_host, extra_config_paths=extra_config_paths)
        return cli_path, pulp_registry_oras_destination_flags(client, extra_config_paths)

    oci_path: str | None = None
    try:
        candidate = select_oci_auth_registry_config_path(destination_ref)
        if registry_config_has_auth_for_host(candidate, registry_host):
            oci_path = candidate
        else:
            Path(candidate).unlink(missing_ok=True)
    except OrasPublishError:
        oci_path = None

    if oci_path:
        return oci_path, []
    if client.config.get("cert"):
        return _write_empty_auths_registry_config(registry_host), []
    raise PulpContainerOciError(
        "Pulp registry push requires cli.username/cli.password, select-oci-auth credentials "
        f"for {destination_ref!r}, or client cert/key in destination --config"
    )


def _write_empty_auths_registry_config(registry_host: str) -> str:
    """Registry config with no auths (client cert used for TLS)."""
    body: dict[str, dict[str, dict[str, str]]] = {"auths": {registry_host: {}}}
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(body, tmp)
    tmp.close()
    return tmp.name


def _first_result(response: httpx.Response) -> dict | None:
    if response.status_code == 404:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        return None
    row = results[0]
    return row if isinstance(row, dict) else None


def _get_container_resource(client: PulpClient, endpoint: str, name: str) -> dict | None:
    from ..api.pulp_client.repository import get_single_resource_by_name

    response = get_single_resource_by_name(client, endpoint, name)
    return _first_result(response)


def _get_container_resource_by_query(
    client: PulpClient,
    endpoint: str,
    param: str,
    value: str,
) -> dict | None:
    url = client._url(f"{endpoint}?") + urlencode({param: value, "offset": 0, "limit": 1})
    response = client.session.get(url, timeout=client.timeout, **client.request_params)
    if response.status_code != 404:
        client._check_response(response, f"get container resource by {param}")
    return _first_result(response)


def _get_container_distribution(client: PulpClient, registry_base_path: str) -> dict | None:
    """Resolve a container distribution by API ``name`` or registry ``base_path``."""
    api_name = _container_distribution_api_name(registry_base_path)
    row = _get_container_resource(client, CONTAINER_DISTRIBUTION_ENDPOINT, api_name)
    if row:
        return row
    return _get_container_resource_by_query(
        client,
        CONTAINER_DISTRIBUTION_ENDPOINT,
        "base_path",
        registry_base_path,
    )


def _container_repository_href_from_task(*, client: PulpClient, task_href: str, name: str) -> str:
    task = client.wait_for_finished_task(task_href)
    created = task.created_resources or []
    for resource in created:
        if "container-push" in resource and "repositories" in resource:
            return resource
    raise PulpContainerOciError(f"Container-push repository task did not create a repository: {name!r}")


def _create_container_push_repository(client: PulpClient, name: str) -> str:
    request = RepositoryRequest(name=name)
    try:
        response = client._create_repository(CONTAINER_PUSH_REPO_ENDPOINT, request)
    except PulpToolHTTPError as exc:
        if exc.response is not None and exc.response.status_code == 400:
            if _is_distribution_uniqueness_error(exc.response.text):
                existing = _get_container_resource(client, CONTAINER_PUSH_REPO_ENDPOINT, name)
                if existing and existing.get("pulp_href"):
                    logger.info("Using existing Pulp container-push repository %s", name)
                    return str(existing["pulp_href"])
        raise PulpContainerOciError(f"Failed to create container-push repository {name!r}: {exc}") from exc
    payload = response.json()
    href = payload.get("pulp_href")
    if isinstance(href, str) and href.strip():
        return href.strip()
    task_href = payload.get("task")
    if isinstance(task_href, str) and task_href.strip():
        return _container_repository_href_from_task(client=client, task_href=task_href.strip(), name=name)
    raise PulpContainerOciError(f"Unexpected create container-push repository response for {name!r}")


def _create_container_distribution(client: PulpClient, api_name: str, base_path: str) -> None:
    """
    Create a container registry distribution (push repo is provisioned by Pulp on push).

    See pulp-container: ``ContainerPushRepositoryViewSet`` disallows POST; distributions use
    ``api/v3/distributions/container/container/``.
    """
    request = DistributionRequest(name=api_name, base_path=base_path)
    try:
        response = client._create_distribution(CONTAINER_DISTRIBUTION_ENDPOINT, request)
    except PulpToolHTTPError as exc:
        if exc.response is not None and exc.response.status_code == 400:
            if _is_distribution_uniqueness_error(exc.response.text):
                existing = _get_container_distribution(client, base_path)
                if existing:
                    logger.info("Using existing Pulp container distribution %s", base_path)
                    return
        raise PulpContainerOciError(f"Failed to create container distribution {base_path!r}: {exc}") from exc
    payload = response.json()
    if isinstance(payload.get("pulp_href"), str) and payload["pulp_href"].strip():
        return
    task_href = payload.get("task")
    if isinstance(task_href, str) and task_href.strip():
        wait_for_successful_task(client, task_href.strip(), "create container distribution")


def _get_or_create_container_distribution(client: PulpClient, registry_base_path: str) -> str:
    api_name = _container_distribution_api_name(registry_base_path)
    existing = _get_container_distribution(client, registry_base_path)
    if existing:
        return str(existing.get("base_path") or registry_base_path)
    logger.info(
        "Creating Pulp container distribution %s (base_path=%s) for registry push",
        api_name,
        registry_base_path,
    )
    _create_container_distribution(client, api_name, registry_base_path)
    client.invalidate_get_cache()
    existing = _get_container_distribution(client, registry_base_path)
    if not existing:
        raise PulpContainerOciError(f"Container distribution {registry_base_path!r} was not found after create")
    return str(existing.get("base_path") or registry_base_path)


def ensure_container_push_oci_storage(client: PulpClient, resource_name: str) -> tuple[str, str]:
    """
    Ensure a container registry distribution exists for push (``namespace/oci/build-id`` base path).

    Returns ``(base_path, oras_copy_target)``.
    """
    base_path = _get_or_create_container_distribution(client, resource_name)
    target = oras_copy_target_for_base_path(client.config, base_path)
    return base_path, target


def provision_pulp_oras_cp_target(client: PulpClient, namespace: str | None, build_id: str | None) -> str:
    """Create Pulp OCI storage if needed and return the ``oras cp`` destination (``host/path:tag``)."""
    name = pulp_container_oci_object_name(namespace, build_id)
    _base_path, target = ensure_container_push_oci_storage(client, name)
    return target


def _delete_pulp_href(client: PulpClient, pulp_href: str) -> None:
    if not pulp_href:
        return
    base_url = str(client.config["base_url"]).rstrip("/")
    href = pulp_href if pulp_href.startswith("http") else f"{base_url}{pulp_href}"
    response = client.session.delete(href, timeout=client.timeout, **client.request_params)
    if response.status_code not in (202, 204, 404):
        client._check_response(response, "delete Pulp resource")


def destroy_container_push_oci_storage(client: PulpClient, registry_base_path: str) -> None:
    """Best-effort delete of container-push distribution and repository (e2e cleanup)."""
    api_name = _container_distribution_api_name(registry_base_path)
    distro = _get_container_distribution(client, registry_base_path)
    if distro and distro.get("pulp_href"):
        logger.info("Deleting Pulp container distribution %s (base_path=%s)", api_name, registry_base_path)
        _delete_pulp_href(client, str(distro["pulp_href"]))
    repo = _get_container_resource(client, CONTAINER_PUSH_REPO_ENDPOINT, registry_base_path)
    if repo and repo.get("pulp_href"):
        logger.info("Deleting Pulp container-push repository %s", registry_base_path)
        _delete_pulp_href(client, str(repo["pulp_href"]))


def container_resource_name_for_cleanup(namespace: str, build_id: str) -> str:
    """Name helper for e2e/post-test cleanup (matches :func:`pulp_container_oci_object_name`)."""
    return pulp_container_oci_object_name(namespace, build_id)


__all__ = [
    "CONTAINER_REGISTRY_PATH_SEGMENT",
    "DEFAULT_ORAS_TAG",
    "PulpContainerOciError",
    "build_pulp_cp_registry_config_for_ref",
    "build_pulp_destination_registry_config",
    "container_resource_name_for_cleanup",
    "destroy_container_push_oci_storage",
    "ensure_container_push_oci_storage",
    "oras_copy_target_for_base_path",
    "oci_ref_registry_host",
    "provision_pulp_oras_cp_target",
    "pulp_container_oci_object_name",
    "pulp_registry_oras_auth",
    "pulp_registry_oras_destination_flags",
    "pulp_registry_oras_source_flags",
    "uses_pulp_container_registry",
    "write_pulp_registry_auth_config",
]
