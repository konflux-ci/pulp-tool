"""Tests for post-transfer Pulp container-push oras cp."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.models.context import PullContext
from pulp_tool.pull.transfer_oras_copy import finalize_transfer_pulp_oras_cp


def test_finalize_pulp_oras_cp_requires_snapshot(tmp_path: Path) -> None:
    context = PullContext(
        operation_label="transfer",
        pulp_oras_cp_target=True,
        config=str(tmp_path / "cli.toml"),
        transfer_dest=str(tmp_path / "cli.toml"),
        oras_cp_source="quay.io/ns/src@sha256:abc",
        namespace="ns",
        build_id="b1",
    )
    with pytest.raises(ValueError, match="snapshot-path"):
        finalize_transfer_pulp_oras_cp(context)


def test_finalize_pulp_oras_cp_runs_provision_and_snapshot(tmp_path: Path) -> None:
    cfg = tmp_path / "cli.toml"
    cfg.write_text('[cli]\nbase_url = "https://example.com"\n', encoding="utf-8")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        '{"components":[{"name":"c","containerImage":"quay.io/ns/src@sha256:abc"}]}\n',
        encoding="utf-8",
    )
    context = PullContext(
        operation_label="transfer",
        pulp_oras_cp_target=True,
        config=str(cfg),
        transfer_dest=str(cfg),
        snapshot_path=str(snapshot),
        oras_cp_source="quay.io/ns/src@sha256:abc",
        namespace="my-ns",
        build_id="build-1",
    )
    mock_client = MagicMock()
    mock_client.config = {"base_url": "https://example.com", "username": "u", "password": "p"}
    mock_client.cert = ("", "")
    with (
        patch(
            "pulp_tool.pull.transfer_oras_copy.PulpClient.create_from_config_file",
            return_value=mock_client,
        ),
        patch(
            "pulp_tool.pull.transfer_oras_copy.provision_pulp_oras_cp_target",
            return_value="registry.example.com/my-ns/oci/build-1:latest",
        ) as mock_provision,
        patch(
            "pulp_tool.pull.transfer_oras_copy.write_pulp_registry_auth_config",
            return_value=str(tmp_path / "reg.json"),
        ),
        patch(
            "pulp_tool.pull.transfer_oras_copy.pulp_registry_oras_destination_flags",
            return_value=["--to-username", "u", "--to-password", "p"],
        ),
        patch(
            "pulp_tool.pull.transfer_oras_copy.copy_oci_artifact",
            return_value="registry.example.com/my-ns/oci/build-1@sha256:new",
        ) as mock_cp,
        patch(
            "pulp_tool.pull.transfer_oras_copy.update_snapshot_component_container_images",
            return_value=1,
        ) as mock_update,
    ):
        finalize_transfer_pulp_oras_cp(context)
    mock_provision.assert_called_once_with(mock_client, "my-ns", "build-1")
    mock_cp.assert_called_once()
    assert mock_cp.call_args.kwargs.get("destination_cp_flags") == ["--to-username", "u", "--to-password", "p"]
    mock_update.assert_called_once_with(
        str(snapshot),
        "registry.example.com/my-ns/oci/build-1@sha256:new",
        match_source_ref="quay.io/ns/src@sha256:abc",
    )
    mock_client.close.assert_called_once()
