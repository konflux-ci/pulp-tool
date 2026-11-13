"""Provision Pulp container-push OCI storage and copy artifacts after ``transfer``."""

from __future__ import annotations

import base64
import json
import logging
import tempfile
from typing import TYPE_CHECKING
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


def _pulp_registry_credentials(client: PulpClient) -> tuple[str, str] | None:
    """
    Return ``(username, password)`` for Pulp container-registry HTTP auth.

    OAuth access tokens are returned as the password (same pattern as Pulp API Basic Auth on registry v2).
    """
    username = client.config.get("username")
    password = client.config.get("password")
    if username is not None and password is not None:
        return str(username), str(password)

    client_id = client.config.get("client_id")
    client_secret = client.config.get("client_secret")
    if client_id and client_secret:
        from ..api.auth import OAuth2ClientCredentialsAuth

        auth = client.auth
        if not isinstance(auth, OAuth2ClientCredentialsAuth):
            raise PulpContainerOciError("Pulp registry OAuth push requires OAuth2 client credentials in --config")
        if not auth.access_token:
            auth._retrieve_token()
        access_token = auth.access_token
        if not access_token:
            raise PulpContainerOciError("Failed to obtain OAuth access token for Pulp container registry push")
        principal = str(username if username is not None else client_id)
        return principal, access_token

    return None


def pulp_registry_oras_destination_flags(client: PulpClient) -> list[str]:
    """Extra ``oras cp`` flags for the Pulp destination registry (explicit auth)."""
    creds = _pulp_registry_credentials(client)
    if not creds:
        return []
    user, secret = creds
    return ["--to-username", user, "--to-password", secret]


def write_pulp_registry_auth_config(client: PulpClient, registry_host: str) -> str:
    """
    Write a Docker ``config.json`` fragment with registry credentials from the Pulp CLI config.

    Supports HTTP basic (username/password), OAuth access token as password (Konflux ``cli.toml``), and mTLS-only
    (empty ``auths`` entry) when ``cert``/``key`` are set—mTLS is passed separately to ORAS.
    """
    creds = _pulp_registry_credentials(client)
    if creds:
        user, secret = creds
        token = base64.b64encode(f"{user}:{secret}".encode()).decode("ascii")
        auths = {host: {"auth": token} for host in _registry_auth_hosts(registry_host)}
        return _write_registry_auth_file(registry_host, auths)

    if client.config.get("cert"):
        return _write_empty_auths_registry_config(registry_host)
    raise PulpContainerOciError(
        "Pulp registry push requires cli.username/cli.password, client_id/client_secret, or client cert/key "
        "in destination --config"
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
    "container_resource_name_for_cleanup",
    "destroy_container_push_oci_storage",
    "ensure_container_push_oci_storage",
    "oras_copy_target_for_base_path",
    "provision_pulp_oras_cp_target",
    "pulp_container_oci_object_name",
    "pulp_registry_oras_destination_flags",
    "write_pulp_registry_auth_config",
]
