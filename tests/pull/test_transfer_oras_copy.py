"""Tests for post-transfer oras cp + snapshot update."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pulp_tool.models.context import PullContext
from pulp_tool.pull.transfer_oras_copy import finalize_transfer_oras_copy


def test_finalize_requires_snapshot(tmp_path: Path) -> None:
    context = PullContext(
        operation_label="transfer",
        oras_cp_target="quay.io/ns/target:tag",
        oras_cp_source="quay.io/ns/src@sha256:abc",
        artifact_location=str(tmp_path / "pulp_results.json"),
    )
    with pytest.raises(ValueError, match="snapshot-path"):
        finalize_transfer_oras_copy(context)


def test_finalize_runs_cp_and_snapshot(tmp_path: Path) -> None:
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        '{"components":[{"name":"c","containerImage":"quay.io/ns/src@sha256:abc"}]}\n',
        encoding="utf-8",
    )
    context = PullContext(
        operation_label="transfer",
        oras_cp_target="quay.io/ns/target:rel",
        oras_cp_source="quay.io/ns/src@sha256:abc",
        snapshot_path=str(snapshot),
    )
    with (
        patch(
            "pulp_tool.pull.transfer_oras_copy.copy_oci_artifact",
            return_value="quay.io/ns/target@sha256:new",
        ) as mock_cp,
        patch(
            "pulp_tool.pull.transfer_oras_copy.update_snapshot_component_container_images",
            return_value=1,
        ) as mock_update,
    ):
        finalize_transfer_oras_copy(context)
    mock_cp.assert_called_once_with("quay.io/ns/src@sha256:abc", "quay.io/ns/target:rel")
    mock_update.assert_called_once_with(
        str(snapshot),
        "quay.io/ns/target@sha256:new",
        match_source_ref="quay.io/ns/src@sha256:abc",
    )
