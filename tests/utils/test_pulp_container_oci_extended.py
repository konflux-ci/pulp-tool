"""Extended coverage for Pulp container-push OCI helpers."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pulp_tool.exceptions import PulpToolHTTPError
from pulp_tool.utils.pulp_container_oci import (
    PulpContainerOciError,
    _create_container_distribution,
    _create_container_push_repository,
    _delete_pulp_href,
    _first_result,
    _registry_host_from_cli_config,
    _write_empty_auths_registry_config,
    destroy_container_push_oci_storage,
    ensure_container_push_oci_storage,
    oras_copy_target_for_base_path,
    pulp_container_oci_object_name,
    pulp_registry_oras_destination_flags,
    write_pulp_registry_auth_config,
)


def test_pulp_container_oci_object_name_invalid_build_id() -> None:
    with pytest.raises(PulpContainerOciError, match="Invalid build_id"):
        pulp_container_oci_object_name("ns", "invalid build id")


def test_registry_host_from_container_registry_url() -> None:
    host = _registry_host_from_cli_config({"container_registry": "https://registry.example.com/v2"})
    assert host == "registry.example.com"


def test_registry_host_missing_config_raises() -> None:
    with pytest.raises(PulpContainerOciError, match="base_url"):
        _registry_host_from_cli_config({})


def test_oras_copy_target_empty_base_path() -> None:
    with pytest.raises(PulpContainerOciError, match="base_path"):
        oras_copy_target_for_base_path({"base_url": "https://x.com"}, "  ")


def test_write_pulp_registry_auth_basic(tmp_path) -> None:
    client = MagicMock()
    client.config = {"username": "u", "password": "p"}
    path = write_pulp_registry_auth_config(client, "registry.example.com")
    data = json.loads(open(path, encoding="utf-8").read())
    assert "registry.example.com" in data["auths"]
    assert "registry.example.com:443" in data["auths"]


def test_write_pulp_registry_auth_cert_only() -> None:
    client = MagicMock()
    client.config = {"cert": "/c.pem"}
    path = _write_empty_auths_registry_config("registry.example.com")
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["auths"]["registry.example.com"] == {}


def test_write_pulp_registry_auth_missing_credentials() -> None:
    client = MagicMock()
    client.config = {}
    with pytest.raises(PulpContainerOciError, match="client_id"):
        write_pulp_registry_auth_config(client, "host")


def test_write_pulp_registry_auth_oauth_uses_basic_auth_password() -> None:
    import base64

    from pulp_tool.api.auth import OAuth2ClientCredentialsAuth

    oauth = OAuth2ClientCredentialsAuth("id", "secret", "https://sso.example/token")
    oauth._access_token = "oauth-registry-token"
    client = MagicMock()
    client.config = {"client_id": "id", "client_secret": "secret"}
    client.auth = oauth
    path = write_pulp_registry_auth_config(client, "packages.redhat.com")
    data = json.loads(open(path, encoding="utf-8").read())
    expected = base64.b64encode(b"id:oauth-registry-token").decode("ascii")
    assert data["auths"]["packages.redhat.com"]["auth"] == expected
    assert data["auths"]["packages.redhat.com:443"]["auth"] == expected


def test_write_pulp_registry_auth_oauth_fetches_token_when_missing() -> None:
    from pulp_tool.api.auth import OAuth2ClientCredentialsAuth

    oauth = OAuth2ClientCredentialsAuth("id", "secret", "https://sso.example/token")
    client = MagicMock()
    client.config = {"client_id": "id", "client_secret": "secret"}
    client.auth = oauth
    with patch.object(oauth, "_retrieve_token", side_effect=lambda: setattr(oauth, "_access_token", "fetched")):
        path = write_pulp_registry_auth_config(client, "registry.example.com")
    data = json.loads(open(path, encoding="utf-8").read())
    import base64

    expected = base64.b64encode(b"id:fetched").decode("ascii")
    assert data["auths"]["registry.example.com"]["auth"] == expected


def test_write_pulp_registry_auth_oauth_rejects_non_oauth_client_auth() -> None:
    client = MagicMock()
    client.config = {"client_id": "id", "client_secret": "secret"}
    client.auth = httpx.BasicAuth("u", "p")
    with pytest.raises(PulpContainerOciError, match="OAuth2 client credentials"):
        write_pulp_registry_auth_config(client, "registry.example.com")


def test_pulp_registry_oras_destination_flags_basic() -> None:
    client = MagicMock()
    client.config = {"username": "u", "password": "p"}
    assert pulp_registry_oras_destination_flags(client) == ["--to-username", "u", "--to-password", "p"]


def test_write_pulp_registry_auth_oauth_raises_when_token_missing_after_retrieve() -> None:
    from pulp_tool.api.auth import OAuth2ClientCredentialsAuth

    oauth = OAuth2ClientCredentialsAuth("id", "secret", "https://sso.example/token")
    client = MagicMock()
    client.config = {"client_id": "id", "client_secret": "secret"}
    client.auth = oauth
    with (
        patch.object(oauth, "_retrieve_token"),
        pytest.raises(PulpContainerOciError, match="Failed to obtain OAuth access token"),
    ):
        write_pulp_registry_auth_config(client, "registry.example.com")


def test_get_container_resource_delegates_to_pulp_api() -> None:
    from pulp_tool.utils.pulp_container_oci import _get_container_resource

    client = MagicMock()
    response = httpx.Response(200, json={"results": [{"pulp_href": "/repo/x/"}]})
    with patch(
        "pulp_tool.api.pulp_client.repository.get_single_resource_by_name",
        return_value=response,
    ) as mock_get:
        row = _get_container_resource(client, "api/v3/repositories/container/container-push/", "ns+bid")
    mock_get.assert_called_once_with(client, "api/v3/repositories/container/container-push/", "ns+bid")
    assert row and row["pulp_href"] == "/repo/x/"


def test_first_result_handles_shapes() -> None:
    assert _first_result(httpx.Response(404)) is None
    assert _first_result(httpx.Response(200, content=b"not json")) is None
    assert _first_result(httpx.Response(200, json={"results": []})) is None
    row = _first_result(httpx.Response(200, json={"results": [{"pulp_href": "/x/"}]}))
    assert row and row["pulp_href"] == "/x/"


def test_create_repository_uses_existing_on_uniqueness_error() -> None:
    client = MagicMock()
    response = httpx.Response(400, text="name uniqueness")
    http_err = PulpToolHTTPError("fail", response=response)
    client._create_repository.side_effect = http_err
    with patch(
        "pulp_tool.utils.pulp_container_oci._is_distribution_uniqueness_error",
        return_value=True,
    ):
        with patch(
            "pulp_tool.utils.pulp_container_oci._get_container_resource",
            return_value={"pulp_href": "/repo/1/"},
        ):
            href = _create_container_push_repository(client, "ns+bid")
    assert href == "/repo/1/"


def test_create_repository_http_error_wrapped() -> None:
    client = MagicMock()
    response = httpx.Response(500, text="boom")
    client._create_repository.side_effect = PulpToolHTTPError("fail", response=response)
    with pytest.raises(PulpContainerOciError, match="Failed to create"):
        _create_container_push_repository(client, "ns+bid")


def test_create_repository_returns_immediate_href() -> None:
    client = MagicMock()
    client._create_repository.return_value = httpx.Response(
        201,
        json={"pulp_href": "/pulp/api/v3/repositories/container/container-push/abc/"},
    )
    href = _create_container_push_repository(client, "ns+bid")
    assert href == "/pulp/api/v3/repositories/container/container-push/abc/"


def test_create_repository_via_task() -> None:
    client = MagicMock()
    client._create_repository.return_value = httpx.Response(202, json={"task": "/tasks/1/"})
    client.wait_for_finished_task.return_value = MagicMock(
        created_resources=["/pulp/api/v3/repositories/container/container-push/abc/"]
    )
    href = _create_container_push_repository(client, "ns+bid")
    assert "container-push" in href


def test_create_repository_unexpected_response() -> None:
    client = MagicMock()
    client._create_repository.return_value = httpx.Response(200, json={})
    with pytest.raises(PulpContainerOciError, match="Unexpected create"):
        _create_container_push_repository(client, "ns+bid")


def test_create_distribution_existing_on_uniqueness() -> None:
    client = MagicMock()
    response = httpx.Response(400, text="name uniqueness")
    client._create_distribution.side_effect = PulpToolHTTPError("fail", response=response)
    with patch(
        "pulp_tool.utils.pulp_container_oci._is_distribution_uniqueness_error",
        return_value=True,
    ):
        with patch(
            "pulp_tool.utils.pulp_container_oci._get_container_resource",
            return_value={"pulp_href": "/dist/"},
        ):
            _create_container_distribution(client, "n", "n")


def test_create_distribution_waits_for_task() -> None:
    client = MagicMock()
    client._create_distribution.return_value = httpx.Response(202, json={"task": "/tasks/2/"})
    with patch("pulp_tool.utils.pulp_container_oci.wait_for_successful_task") as mock_wait:
        _create_container_distribution(client, "n", "n")
    mock_wait.assert_called_once()


def test_get_container_distribution_falls_back_to_base_path_query() -> None:
    from pulp_tool.utils.pulp_container_oci import _get_container_distribution

    client = MagicMock()
    client.timeout = 30
    client.request_params = {}
    distro = {"pulp_href": "/dist/", "base_path": "ns/bid"}
    with (
        patch(
            "pulp_tool.utils.pulp_container_oci._get_container_resource",
            return_value=None,
        ),
        patch(
            "pulp_tool.utils.pulp_container_oci._get_container_resource_by_query",
            return_value=distro,
        ) as mock_query,
    ):
        row = _get_container_distribution(client, "ns/bid")
    mock_query.assert_called_once_with(
        client,
        "api/v3/distributions/container/container/",
        "base_path",
        "ns/bid",
    )
    assert row == distro


def test_ensure_distribution_missing_after_create() -> None:
    client = MagicMock()
    client.config = {"base_url": "https://example.com"}
    with (
        patch(
            "pulp_tool.utils.pulp_container_oci._get_container_distribution",
            side_effect=[None, None],
        ),
        patch("pulp_tool.utils.pulp_container_oci._create_container_distribution"),
        pytest.raises(PulpContainerOciError, match="not found after create"),
    ):
        ensure_container_push_oci_storage(client, "ns/bid")


def test_delete_pulp_href_checks_response() -> None:
    from pulp_tool.exceptions import PulpToolHTTPError

    client = MagicMock()
    client.config = {"base_url": "https://example.com"}
    bad_response = httpx.Response(500, text="err")
    client.session.delete.return_value = bad_response
    client.timeout = 30
    client.request_params = {}
    client._check_response.side_effect = PulpToolHTTPError("delete Pulp resource", response=bad_response)
    with pytest.raises(PulpToolHTTPError):
        _delete_pulp_href(client, "/pulp/api/v3/foo/")


def test_registry_host_unparseable_base_url() -> None:
    with pytest.raises(PulpContainerOciError, match="Could not derive"):
        _registry_host_from_cli_config({"base_url": "https://"})


def test_write_pulp_registry_auth_uses_cert_without_password() -> None:
    client = MagicMock()
    client.config = {"cert": "/tls.crt"}
    path = write_pulp_registry_auth_config(client, "registry.example.com")
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["auths"]["registry.example.com"] == {}


def test_create_repository_task_without_created_resource() -> None:
    client = MagicMock()
    client._create_repository.return_value = httpx.Response(202, json={"task": "/tasks/1/"})
    client.wait_for_finished_task.return_value = MagicMock(created_resources=[])
    with pytest.raises(PulpContainerOciError, match="did not create a repository"):
        _create_container_push_repository(client, "ns+bid")


def test_create_distribution_http_error_wrapped() -> None:
    client = MagicMock()
    response = httpx.Response(500, text="boom")
    client._create_distribution.side_effect = PulpToolHTTPError("fail", response=response)
    with pytest.raises(PulpContainerOciError, match="Failed to create container distribution"):
        _create_container_distribution(client, "n", "n")


def test_delete_pulp_href_noop_on_empty() -> None:
    client = MagicMock()
    _delete_pulp_href(client, "")
    client.session.delete.assert_not_called()


def test_container_resource_name_for_cleanup() -> None:
    from pulp_tool.utils.pulp_container_oci import container_resource_name_for_cleanup

    assert container_resource_name_for_cleanup("ns", "bid") == "ns/oci/bid"


def test_destroy_container_push_oci_storage() -> None:
    client = MagicMock()
    client.config = {"base_url": "https://example.com"}
    client.session.delete.return_value = httpx.Response(202)
    client.timeout = 30
    client.request_params = {}
    registry_path = "ns/bid"
    with (
        patch(
            "pulp_tool.utils.pulp_container_oci._get_container_distribution",
            return_value={"pulp_href": "/dist/1/"},
        ),
        patch(
            "pulp_tool.utils.pulp_container_oci._get_container_resource",
            return_value={"pulp_href": "/repo/1/"},
        ),
    ):
        destroy_container_push_oci_storage(client, registry_path)
    assert client.session.delete.call_count == 2
