"""Additional coverage for post-transfer OCI copy."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.models.context import PullContext
from pulp_tool.pull.transfer_oras_copy import (
    _transfer_pulp_oras_copy_kwargs,
    finalize_transfer_oci_post_copy,
    finalize_transfer_oras_copy,
    finalize_transfer_pulp_oras_cp,
)
from pulp_tool.utils.oras_publish import OrasPublishError
from pulp_tool.utils.pulp_container_oci import PulpContainerOciError


def test_transfer_pulp_oras_copy_kwargs_requires_config() -> None:
    with pytest.raises(ValueError, match="destination --config"):
        _transfer_pulp_oras_copy_kwargs(PullContext(operation_label="transfer"))


def test_transfer_pulp_oras_copy_kwargs_includes_source_config_and_tls(tmp_path: Path) -> None:
    cfg = tmp_path / "cli.toml"
    cfg.write_text("[cli]\n", encoding="utf-8")
    source_cfg = tmp_path / "source-cli.toml"
    source_cfg.write_text("[cli]\n", encoding="utf-8")
    mock_client = MagicMock()
    mock_client.config = {"cert": "/tls.crt"}
    mock_client.cert = ("/tls.crt", "/tls.key")
    context = PullContext(
        operation_label="transfer",
        transfer_dest=str(cfg),
        transfer_source_config_path=str(source_cfg),
        namespace="ns",
        build_id="bid",
    )
    with patch(
        "pulp_tool.pull.transfer_oras_copy.PulpClient.create_from_config_file",
        return_value=mock_client,
    ) as mock_create:
        client, kwargs = _transfer_pulp_oras_copy_kwargs(context)
    mock_create.assert_called_once_with(str(cfg), correlation_namespace="ns", correlation_build_id="bid")
    assert client is mock_client
    assert kwargs["extra_config_paths"] == (str(source_cfg),)
    assert kwargs["client_tls_cert"] == ("/tls.crt", "/tls.key")


def test_transfer_pulp_oras_copy_kwargs_omits_tls_without_cert(tmp_path: Path) -> None:
    cfg = tmp_path / "cli.toml"
    cfg.write_text("[cli]\n", encoding="utf-8")
    mock_client = MagicMock()
    mock_client.config = {"username": "u", "password": "p"}
    mock_client.cert = ("", "")
    with patch(
        "pulp_tool.pull.transfer_oras_copy.PulpClient.create_from_config_file",
        return_value=mock_client,
    ):
        _client, kwargs = _transfer_pulp_oras_copy_kwargs(
            PullContext(operation_label="transfer", transfer_dest=str(cfg)),
        )
    assert kwargs["client_tls_cert"] is None


def test_finalize_oras_copy_passes_pulp_client_for_pulp_registry(tmp_path: Path) -> None:
    cfg = tmp_path / "cli.toml"
    cfg.write_text('[cli]\nbase_url = "https://packages.redhat.com"\n', encoding="utf-8")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        '{"components":[{"containerImage":"quay.io/ns/src@sha256:abc"}]}\n',
        encoding="utf-8",
    )
    context = PullContext(
        operation_label="transfer",
        oras_cp_target="packages.redhat.com/ns/oci/bid:latest",
        oras_cp_source="quay.io/ns/src@sha256:abc",
        transfer_dest=str(cfg),
        snapshot_path=str(snapshot),
        namespace="ns",
        build_id="bid",
    )
    mock_client = MagicMock()
    mock_client.config = {"base_url": "https://packages.redhat.com", "username": "u", "password": "p"}
    mock_client.cert = None
    with (
        patch(
            "pulp_tool.pull.transfer_oras_copy.PulpClient.create_from_config_file",
            return_value=mock_client,
        ),
        patch(
            "pulp_tool.pull.transfer_oras_copy.copy_oci_artifact",
            return_value="packages.redhat.com/ns/oci/bid@sha256:new",
        ) as mock_cp,
        patch(
            "pulp_tool.pull.transfer_oras_copy.update_snapshot_component_container_images",
            return_value=1,
        ),
    ):
        finalize_transfer_oras_copy(context)
    mock_client.close.assert_called_once()
    assert mock_cp.call_args.kwargs.get("pulp_client") is mock_client


def test_finalize_oras_copy_closes_client_when_registry_not_pulp(tmp_path: Path) -> None:
    cfg = tmp_path / "cli.toml"
    cfg.write_text('[cli]\nbase_url = "https://example.com"\n', encoding="utf-8")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text('{"components":[]}\n', encoding="utf-8")
    context = PullContext(
        operation_label="transfer",
        oras_cp_target="quay.io/ns/target:rel",
        oras_cp_source="quay.io/ns/src@sha256:abc",
        transfer_dest=str(cfg),
        snapshot_path=str(snapshot),
    )
    mock_client = MagicMock()
    mock_client.config = {"base_url": "https://example.com"}
    with (
        patch(
            "pulp_tool.pull.transfer_oras_copy.PulpClient.create_from_config_file",
            return_value=mock_client,
        ),
        patch(
            "pulp_tool.pull.transfer_oras_copy.copy_oci_artifact",
            return_value="quay.io/ns/target@sha256:new",
        ) as mock_cp,
        patch(
            "pulp_tool.pull.transfer_oras_copy.update_snapshot_component_container_images",
            return_value=1,
        ),
    ):
        finalize_transfer_oras_copy(context)
    mock_client.close.assert_called_once()
    assert "pulp_client" not in mock_cp.call_args.kwargs


def test_finalize_oras_copy_noop_without_target() -> None:
    context = PullContext(operation_label="transfer")
    finalize_transfer_oras_copy(context)


def test_resolve_source_from_artifact_location(tmp_path: Path) -> None:
    snapshot = tmp_path / "snap.json"
    snapshot.write_text('{"components":[]}\n', encoding="utf-8")
    context = PullContext(
        operation_label="transfer",
        oras_cp_target="quay.io/t:rel",
        artifact_location="quay.io/ns/src@sha256:abc",
        snapshot_path=str(snapshot),
    )
    with (
        patch(
            "pulp_tool.pull.transfer_oras_copy.copy_oci_artifact",
            return_value="quay.io/t@sha256:new",
        ) as mock_cp,
        patch(
            "pulp_tool.pull.transfer_oras_copy.update_snapshot_component_container_images",
            return_value=1,
        ),
    ):
        finalize_transfer_oras_copy(context)
    mock_cp.assert_called_once_with("quay.io/ns/src@sha256:abc", "quay.io/t:rel")


def test_finalize_oras_copy_wraps_oras_error(tmp_path: Path) -> None:
    snapshot = tmp_path / "snap.json"
    snapshot.write_text('{"components":[]}\n', encoding="utf-8")
    context = PullContext(
        operation_label="transfer",
        oras_cp_target="quay.io/t:rel",
        oras_cp_source="quay.io/ns/src@sha256:abc",
        snapshot_path=str(snapshot),
    )
    with patch(
        "pulp_tool.pull.transfer_oras_copy.copy_oci_artifact",
        side_effect=OrasPublishError("cp failed"),
    ):
        with pytest.raises(ValueError, match="cp failed"):
            finalize_transfer_oras_copy(context)


def test_snapshot_warning_when_no_components_match(tmp_path: Path) -> None:
    snapshot = tmp_path / "snap.json"
    snapshot.write_text('{"components":[]}\n', encoding="utf-8")
    context = PullContext(
        operation_label="transfer",
        oras_cp_target="quay.io/t:rel",
        oras_cp_source="quay.io/ns/src@sha256:abc",
        snapshot_path=str(snapshot),
    )
    with (
        patch(
            "pulp_tool.pull.transfer_oras_copy.copy_oci_artifact",
            return_value="quay.io/t@sha256:new",
        ),
        patch(
            "pulp_tool.pull.transfer_oras_copy.update_snapshot_component_container_images",
            return_value=0,
        ),
    ):
        finalize_transfer_oras_copy(context)


def test_finalize_pulp_oras_cp_early_return() -> None:
    finalize_transfer_pulp_oras_cp(PullContext(operation_label="transfer"))


def test_finalize_pulp_oras_cp_provision_error(tmp_path: Path) -> None:
    cfg = tmp_path / "cli.toml"
    cfg.write_text('[cli]\nbase_url = "https://example.com"\n', encoding="utf-8")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text('{"components":[]}\n', encoding="utf-8")
    context = PullContext(
        operation_label="transfer",
        pulp_oras_cp_target=True,
        transfer_dest=str(cfg),
        snapshot_path=str(snapshot),
        oras_cp_source="quay.io/src@sha256:abc",
    )
    mock_client = patch(
        "pulp_tool.pull.transfer_oras_copy.PulpClient.create_from_config_file",
        return_value=type("C", (), {"config": {}, "cert": ("", ""), "close": lambda self: None})(),
    )
    with (
        mock_client,
        patch(
            "pulp_tool.pull.transfer_oras_copy.provision_pulp_oras_cp_target",
            side_effect=PulpContainerOciError("provision fail"),
        ),
    ):
        with pytest.raises(ValueError, match="provision fail"):
            finalize_transfer_pulp_oras_cp(context)


def test_finalize_pulp_oras_cp_oras_error(tmp_path: Path) -> None:
    cfg = tmp_path / "cli.toml"
    cfg.write_text('[cli]\nbase_url = "https://example.com"\n', encoding="utf-8")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text('{"components":[]}\n', encoding="utf-8")
    reg = tmp_path / "reg.json"
    reg.write_text("{}", encoding="utf-8")
    context = PullContext(
        operation_label="transfer",
        pulp_oras_cp_target=True,
        transfer_dest=str(cfg),
        snapshot_path=str(snapshot),
        oras_cp_source="quay.io/src@sha256:abc",
    )
    client = type(
        "PulpClientStub",
        (),
        {
            "config": {"base_url": "https://example.com", "username": "u", "password": "p"},
            "cert": ("", ""),
            "close": lambda self: None,
        },
    )()
    with (
        patch("pulp_tool.pull.transfer_oras_copy.PulpClient.create_from_config_file", return_value=client),
        patch(
            "pulp_tool.pull.transfer_oras_copy.provision_pulp_oras_cp_target",
            return_value="registry.example.com/ns+b1:latest",
        ),
        patch(
            "pulp_tool.pull.transfer_oras_copy.copy_oci_artifact",
            side_effect=OrasPublishError("oras cp failed"),
        ),
    ):
        with pytest.raises(ValueError, match="oras cp failed"):
            finalize_transfer_pulp_oras_cp(context)


def test_finalize_oci_post_copy_invokes_both_when_configured() -> None:
    context = PullContext(
        operation_label="transfer",
        oras_cp_target="quay.io/a:tag",
        pulp_oras_cp_target=True,
    )
    with (
        patch("pulp_tool.pull.transfer_oras_copy.finalize_transfer_oras_copy") as mock_ext,
        patch("pulp_tool.pull.transfer_oras_copy.finalize_transfer_pulp_oras_cp") as mock_pulp,
    ):
        finalize_transfer_oci_post_copy(context)
    mock_ext.assert_called_once_with(context)
    mock_pulp.assert_called_once_with(context)


def test_resolve_copy_source_requires_oci_ref() -> None:
    bad_loc = "/tmp/pulp_results.json"
    ctx = PullContext(
        operation_label="transfer",
        oras_cp_target="quay.io/t:tag",
        artifact_location=bad_loc,
    )
    with pytest.raises(ValueError, match="digest-pinned OCI"):
        finalize_transfer_oras_copy(ctx)


def test_missing_snapshot_path_raises() -> None:
    context = PullContext(
        operation_label="transfer",
        oras_cp_target="quay.io/t:tag",
        oras_cp_source="quay.io/src@sha256:abc",
    )
    with pytest.raises(ValueError, match="snapshot-path"):
        finalize_transfer_oras_copy(context)


def test_pulp_oras_cp_requires_destination_config() -> None:
    context = PullContext(
        operation_label="transfer",
        pulp_oras_cp_target=True,
        oras_cp_source="quay.io/src@sha256:abc",
        snapshot_path="/snap.json",
    )
    with pytest.raises(ValueError, match="destination --config"):
        finalize_transfer_pulp_oras_cp(context)


def test_finalize_pulp_oras_cp_success(tmp_path: Path) -> None:
    cfg = tmp_path / "cli.toml"
    cfg.write_text('[cli]\nbase_url = "https://example.com"\n', encoding="utf-8")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        '{"components":[{"containerImage":"quay.io/src@sha256:abc"}]}\n',
        encoding="utf-8",
    )
    context = PullContext(
        operation_label="transfer",
        pulp_oras_cp_target=True,
        transfer_dest=str(cfg),
        snapshot_path=str(snapshot),
        oras_cp_source="quay.io/src@sha256:abc",
    )
    client = MagicMock()
    client.config = {"base_url": "https://example.com", "username": "u", "password": "p"}
    client.cert = ("", "")
    client.close = MagicMock()
    with (
        patch("pulp_tool.pull.transfer_oras_copy.PulpClient.create_from_config_file", return_value=client),
        patch(
            "pulp_tool.pull.transfer_oras_copy.provision_pulp_oras_cp_target",
            return_value="registry.example.com/ns+bid:latest",
        ),
        patch(
            "pulp_tool.pull.transfer_oras_copy.copy_oci_artifact",
            return_value="registry.example.com/ns+bid@sha256:new",
        ),
    ):
        finalize_transfer_pulp_oras_cp(context)
    client.close.assert_called_once()
