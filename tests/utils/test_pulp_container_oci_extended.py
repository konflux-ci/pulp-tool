"""Extended coverage for Pulp container-push OCI helpers."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pulp_tool.exceptions import PulpToolHTTPError
from pulp_tool.utils.oras_publish import OrasPublishError
from pulp_tool.utils.pulp_container_oci import (
    PulpContainerOciError,
    _create_container_distribution,
    _create_container_push_repository,
    _delete_pulp_href,
    _first_result,
    _registry_host_from_cli_config,
    _write_empty_auths_registry_config,
    build_pulp_destination_registry_config,
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
    client.config_path = None
    with pytest.raises(PulpContainerOciError, match="username"):
        write_pulp_registry_auth_config(client, "host")


def test_build_pulp_destination_registry_config_basic_auth() -> None:
    client = MagicMock()
    client.config = {"username": "u", "password": "p"}
    client.config_path = None
    dest = "registry.example.com/ns/oci/build:latest"
    with (
        patch(
            "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
            side_effect=OrasPublishError("no docker auth"),
        ),
        patch("pulp_tool.utils.pulp_container_oci.logger") as mock_log,
    ):
        path, flags = build_pulp_destination_registry_config(client, dest)
    mock_log.info.assert_called()
    data = json.loads(open(path, encoding="utf-8").read())
    assert "registry.example.com" in data["auths"]
    assert flags == ["--to-username", "u", "--to-password", "p"]


def test_build_pulp_destination_registry_config_select_oci_auth_only(tmp_path) -> None:
    client = MagicMock()
    client.config = {"client_id": "id", "client_secret": "secret"}
    client.config_path = None
    dest = "packages.redhat.com/ns/oci/build:latest"
    oci_cfg = tmp_path / "oci.json"
    oci_cfg.write_text('{"auths":{"packages.redhat.com":{"auth":"d"}}}', encoding="utf-8")
    with patch(
        "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
        return_value=str(oci_cfg),
    ):
        path, flags = build_pulp_destination_registry_config(client, dest)
    assert path == str(oci_cfg)
    assert flags == []


def test_build_pulp_destination_registry_config_skips_select_when_toml_has_basic(tmp_path) -> None:
    client = MagicMock()
    client.config = {}
    client.config_path = None
    dest = "registry.example.com/ns/oci/build:latest"
    source_toml = tmp_path / "cli.toml"
    source_toml.write_text('[cli]\nusername = "u"\npassword = "p"\n', encoding="utf-8")
    with patch(
        "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
    ) as mock_select:
        path, flags = build_pulp_destination_registry_config(client, dest, extra_config_paths=[str(source_toml)])
    mock_select.assert_not_called()
    data = json.loads(open(path, encoding="utf-8").read())
    import base64

    expected = base64.b64encode(b"u:p").decode("ascii")
    assert data["auths"]["registry.example.com"]["auth"] == expected
    assert flags == ["--to-username", "u", "--to-password", "p"]


def test_build_pulp_destination_registry_config_raises_without_any_auth() -> None:
    client = MagicMock()
    client.config = {"client_id": "id", "client_secret": "secret"}
    client.config_path = None
    dest = "registry.example.com/ns/oci/build:latest"
    with (
        patch(
            "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
            side_effect=OrasPublishError("missing"),
        ),
        pytest.raises(PulpContainerOciError, match="select-oci-auth"),
    ):
        build_pulp_destination_registry_config(client, dest)


def test_pulp_registry_credentials_secret_dir_missing_files(tmp_path) -> None:
    from pulp_tool.utils.pulp_container_oci import _pulp_registry_credentials

    config_dir = tmp_path / "pulp-access"
    config_dir.mkdir()
    toml = config_dir / "cli.toml"
    toml.write_text("[cli]\n", encoding="utf-8")
    client = MagicMock()
    client.config = {}
    client.config_path = toml
    assert _pulp_registry_credentials(client) is None


def test_pulp_registry_credentials_secret_dir_empty_password(tmp_path) -> None:
    from pulp_tool.utils.pulp_container_oci import _pulp_registry_credentials

    config_dir = tmp_path / "pulp-access"
    config_dir.mkdir()
    toml = config_dir / "cli.toml"
    toml.write_text("[cli]\n", encoding="utf-8")
    (config_dir / "username").write_text("u", encoding="utf-8")
    (config_dir / "password").write_text("   \n", encoding="utf-8")
    client = MagicMock()
    client.config = {}
    client.config_path = toml
    assert _pulp_registry_credentials(client) is None


def test_credential_search_dirs_skips_unresolvable_path() -> None:
    from pulp_tool.utils.pulp_container_oci import _credential_search_dirs

    client = MagicMock()
    client.config = {}
    client.config_path = Path("/tmp/cli.toml")
    with patch.object(Path, "resolve", side_effect=OSError(2, "missing")):
        assert _credential_search_dirs(client) == []


def test_pulp_registry_credentials_from_konflux_mount_dir(tmp_path, monkeypatch) -> None:
    from pulp_tool.utils import pulp_container_oci as oci_mod
    from pulp_tool.utils.pulp_container_oci import _pulp_registry_credentials

    mount = tmp_path / "etc-pulp-access"
    mount.mkdir()
    (mount / "username").write_text("mount-user", encoding="utf-8")
    (mount / "password").write_text("mount-pass", encoding="utf-8")
    monkeypatch.setattr(oci_mod, "_KONFLUX_PULP_ACCESS_MOUNT_DIRS", (mount,))
    client = MagicMock()
    client.config = {}
    client.config_path = None
    assert _pulp_registry_credentials(client) == ("mount-user", "mount-pass")


def test_pulp_registry_credentials_from_tls_cert_dir(tmp_path) -> None:
    from pulp_tool.utils.pulp_container_oci import _pulp_registry_credentials

    cert_dir = tmp_path / "pulp-access"
    cert_dir.mkdir()
    cert_file = cert_dir / "tls.crt"
    cert_file.write_text("cert", encoding="utf-8")
    (cert_dir / "username").write_text("cert-user", encoding="utf-8")
    (cert_dir / "password").write_text("cert-pass", encoding="utf-8")
    client = MagicMock()
    client.config = {"cert": "./tls.crt"}
    client.config_path = None
    client.cert = (str(cert_file), str(cert_dir / "tls.key"))
    assert _pulp_registry_credentials(client) == ("cert-user", "cert-pass")


def test_oci_ref_registry_host_strips_oci_prefix_and_bare_host() -> None:
    from pulp_tool.utils.pulp_container_oci import oci_ref_registry_host

    assert oci_ref_registry_host("oci:packages.redhat.com/ns/oci/b@sha256:d") == "packages.redhat.com"
    assert oci_ref_registry_host("localhost") == "localhost"


def test_uses_pulp_container_registry_invalid_cli_registry_host() -> None:
    from pulp_tool.utils.pulp_container_oci import uses_pulp_container_registry

    client = MagicMock()
    client.config = {"base_url": "https://packages.redhat.com"}
    with patch(
        "pulp_tool.utils.pulp_container_oci._registry_host_from_cli_config",
        side_effect=PulpContainerOciError("bad"),
    ):
        assert not uses_pulp_container_registry("other.example.com/repo:latest", client)


def test_uses_pulp_container_registry_packages_redhat() -> None:
    from pulp_tool.utils.pulp_container_oci import uses_pulp_container_registry

    client = MagicMock()
    client.config = {"base_url": "https://quay.io"}
    assert uses_pulp_container_registry("packages.redhat.com/ns/oci/b:latest", client)
    assert not uses_pulp_container_registry("quay.io/ns/repo:latest", client)

    pulp_client = MagicMock()
    pulp_client.config = {
        "base_url": "https://packages.redhat.com",
        "container_registry": "registry.example.com",
    }
    assert uses_pulp_container_registry("registry.example.com/ns/oci/b:latest", pulp_client)


def test_pulp_registry_oras_auth_skips_non_pulp_registry() -> None:
    from pulp_tool.utils.pulp_container_oci import pulp_registry_oras_auth

    client = MagicMock()
    client.config = {"base_url": "https://quay.io"}
    with pulp_registry_oras_auth(client, "quay.io/ns/repo:latest") as (path, tls):
        assert path is None
        assert tls is None


def test_basic_auth_from_pulp_cli_toml_paths() -> None:
    from pulp_tool.utils.pulp_container_oci import (
        _basic_auth_from_cli_mapping,
        _basic_auth_from_pulp_cli_toml,
    )

    assert _basic_auth_from_pulp_cli_toml("/no/such/file.toml") is None
    assert _basic_auth_from_cli_mapping({"username": "u"}) is None
    assert _basic_auth_from_cli_mapping({"username": " ", "password": "p"}) is None


def test_basic_auth_from_pulp_cli_toml_invalid_toml(tmp_path) -> None:
    from pulp_tool.utils.pulp_container_oci import _basic_auth_from_pulp_cli_toml

    bad = tmp_path / "bad.toml"
    bad.write_text("not = [valid\n", encoding="utf-8")
    assert _basic_auth_from_pulp_cli_toml(str(bad)) is None


def test_basic_auth_from_pulp_cli_toml_missing_cli_section(tmp_path) -> None:
    from pulp_tool.utils.pulp_container_oci import _basic_auth_from_pulp_cli_toml

    cfg = tmp_path / "cfg.toml"
    cfg.write_text("foo = 1\n", encoding="utf-8")
    assert _basic_auth_from_pulp_cli_toml(str(cfg)) is None


def test_pulp_registry_credentials_from_dest_config_path_file(tmp_path) -> None:
    from pulp_tool.utils.pulp_container_oci import _pulp_registry_credentials

    cfg = tmp_path / "cli.toml"
    cfg.write_text('[cli]\nusername = "file-user"\npassword = "file-pass"\n', encoding="utf-8")
    client = MagicMock()
    client.config = {}
    client.config_path = cfg
    assert _pulp_registry_credentials(client) == ("file-user", "file-pass")


def test_pulp_registry_credentials_prefers_secret_files_over_cli_mapping(tmp_path) -> None:
    from pulp_tool.utils.pulp_container_oci import _pulp_registry_credentials

    config_dir = tmp_path / "transfer"
    config_dir.mkdir()
    (config_dir / "username").write_text("registry-user", encoding="utf-8")
    (config_dir / "password").write_text("registry-pass", encoding="utf-8")
    toml = config_dir / "transfer-cli.toml"
    toml.write_text("[cli]\n", encoding="utf-8")
    client = MagicMock()
    client.config = {"username": "api-user", "password": "api-pass"}
    client.config_path = toml
    assert _pulp_registry_credentials(client) == ("registry-user", "registry-pass")


def test_pulp_registry_credentials_from_source_config_mount(tmp_path) -> None:
    from pulp_tool.utils.pulp_container_oci import _pulp_registry_credentials

    mount = tmp_path / "pulp-access"
    mount.mkdir()
    (mount / "username").write_text("mount-user", encoding="utf-8")
    (mount / "password").write_text("mount-pass", encoding="utf-8")
    source_toml = mount / "cli.toml"
    source_toml.write_text("[cli]\n", encoding="utf-8")

    workdir = tmp_path / "work"
    workdir.mkdir()
    dest_toml = workdir / "transfer-cli.toml"
    dest_toml.write_text("[cli]\n", encoding="utf-8")
    client = MagicMock()
    client.config = {}
    client.config_path = dest_toml
    assert _pulp_registry_credentials(client, extra_config_paths=[str(source_toml)]) == (
        "mount-user",
        "mount-pass",
    )


def test_pulp_registry_credentials_from_secret_dir_files(tmp_path) -> None:
    from pulp_tool.utils.pulp_container_oci import _pulp_registry_credentials

    config_dir = tmp_path / "pulp-access"
    config_dir.mkdir()
    toml = config_dir / "cli.toml"
    toml.write_text('[cli]\ncert = "./tls.crt"\n', encoding="utf-8")
    (config_dir / "username").write_text("123|svc-account\n", encoding="utf-8")
    (config_dir / "password").write_text("registry-token\n", encoding="utf-8")
    client = MagicMock()
    client.config = {"cert": "tls.crt"}
    client.config_path = toml
    assert _pulp_registry_credentials(client) == ("123|svc-account", "registry-token")


def test_build_pulp_destination_registry_config_uses_secret_dir_files(tmp_path) -> None:
    config_dir = tmp_path / "pulp-access"
    config_dir.mkdir()
    toml = config_dir / "cli.toml"
    toml.write_text('[cli]\ncert = "./tls.crt"\n', encoding="utf-8")
    (config_dir / "username").write_text("u", encoding="utf-8")
    (config_dir / "password").write_text("p", encoding="utf-8")
    client = MagicMock()
    client.config = {"cert": "tls.crt"}
    client.config_path = toml
    dest = "packages.redhat.com/ns/oci/build:latest"
    quay_only = tmp_path / "quay.json"
    quay_only.write_text('{"auths":{"quay.io":{"auth":"q"}}}', encoding="utf-8")
    with patch(
        "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
        return_value=str(quay_only),
    ):
        path, flags = build_pulp_destination_registry_config(client, dest)
    data = json.loads(open(path, encoding="utf-8").read())
    import base64

    expected = base64.b64encode(b"u:p").decode("ascii")
    assert data["auths"]["packages.redhat.com"]["auth"] == expected
    assert flags == ["--to-username", "u", "--to-password", "p"]


def test_build_pulp_destination_registry_config_ignores_select_without_dest_host(tmp_path) -> None:
    client = MagicMock()
    client.config = {"cert": "/tls.crt"}
    client.config_path = None
    dest = "packages.redhat.com/ns/oci/build:latest"
    quay_only = tmp_path / "quay.json"
    quay_only.write_text('{"auths":{"quay.io":{"auth":"q"}}}', encoding="utf-8")
    with patch(
        "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
        return_value=str(quay_only),
    ):
        path, flags = build_pulp_destination_registry_config(client, dest)
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["auths"]["packages.redhat.com"] == {}
    assert flags == []


def test_build_pulp_destination_registry_config_cert_only_when_select_fails() -> None:
    client = MagicMock()
    client.config = {"cert": "/tls.crt", "client_id": "id", "client_secret": "secret"}
    client.config_path = None
    dest = "registry.example.com/ns/oci/build:latest"
    with (
        patch(
            "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
            side_effect=OrasPublishError("missing"),
        ),
        patch("pulp_tool.utils.pulp_container_oci.logger") as mock_log,
    ):
        path, flags = build_pulp_destination_registry_config(client, dest)
    mock_log.warning.assert_called()
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["auths"]["registry.example.com"] == {}
    assert flags == []


def test_build_pulp_cp_registry_config_for_ref_from_side() -> None:
    from pulp_tool.utils.pulp_container_oci import build_pulp_cp_registry_config_for_ref

    client = MagicMock()
    client.config = {"base_url": "https://packages.redhat.com", "username": "u", "password": "p"}
    client.config_path = None
    client.cert = None
    source = "packages.redhat.com/ns/oci/b@sha256:abc"
    path, flags = build_pulp_cp_registry_config_for_ref(client, source, side="from")
    assert path
    assert flags == []
    Path(path).unlink(missing_ok=True)


def test_pulp_registry_oras_source_flags_with_creds() -> None:
    from pulp_tool.utils.pulp_container_oci import pulp_registry_oras_source_flags

    client = MagicMock()
    client.config = {"username": "u", "password": "p"}
    assert pulp_registry_oras_source_flags(client) == [
        "--from-username",
        "u",
        "--from-password",
        "p",
    ]


def test_pulp_registry_oras_source_flags_empty_without_password_creds() -> None:
    from pulp_tool.utils.pulp_container_oci import pulp_registry_oras_source_flags

    client = MagicMock()
    client.config = {"cert": "/tls.crt"}
    client.config_path = None
    assert pulp_registry_oras_source_flags(client) == []


def test_build_pulp_cp_registry_config_to_side_uses_tag_ref() -> None:
    from pulp_tool.utils.pulp_container_oci import build_pulp_cp_registry_config_for_ref

    client = MagicMock()
    client.config = {"base_url": "https://packages.redhat.com", "username": "u", "password": "p"}
    client.config_path = None
    client.cert = None
    path, flags = build_pulp_cp_registry_config_for_ref(
        client,
        "packages.redhat.com/ns/oci/bid:latest",
        side="to",
    )
    assert path
    assert flags == []
    Path(path).unlink(missing_ok=True)


def test_build_pulp_cp_registry_config_without_creds_or_cert() -> None:
    from pulp_tool.utils.pulp_container_oci import build_pulp_cp_registry_config_for_ref

    client = MagicMock()
    client.config = {"base_url": "https://packages.redhat.com"}
    client.config_path = None
    client.cert = None
    path, flags = build_pulp_cp_registry_config_for_ref(
        client,
        "packages.redhat.com/ns/oci/bid:latest",
        side="to",
    )
    assert path is None and flags == []


def test_build_pulp_cp_registry_config_cert_only_without_basic_auth() -> None:
    from pulp_tool.utils.pulp_container_oci import build_pulp_cp_registry_config_for_ref

    client = MagicMock()
    client.config = {"base_url": "https://packages.redhat.com", "cert": "/tls.crt"}
    client.config_path = None
    path, flags = build_pulp_cp_registry_config_for_ref(
        client,
        "packages.redhat.com/ns/oci/bid:latest",
        side="to",
    )
    assert path
    assert flags == []
    Path(path).unlink(missing_ok=True)


def test_build_pulp_cp_registry_config_skips_non_pulp_host() -> None:
    from pulp_tool.utils.pulp_container_oci import build_pulp_cp_registry_config_for_ref

    client = MagicMock()
    client.config = {"base_url": "https://example.com", "username": "u", "password": "p"}
    path, flags = build_pulp_cp_registry_config_for_ref(client, "quay.io/ns/r@sha256:x", side="to")
    assert path is None and flags == []


def test_pulp_registry_oras_destination_flags_basic() -> None:
    client = MagicMock()
    client.config = {"username": "u", "password": "p"}
    assert pulp_registry_oras_destination_flags(client) == ["--to-username", "u", "--to-password", "p"]


def test_pulp_registry_oras_destination_flags_empty_without_password_creds() -> None:
    client = MagicMock()
    client.config = {"cert": "/tls.crt"}
    client.config_path = None
    assert pulp_registry_oras_destination_flags(client) == []


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
    client.config_path = None
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
