"""Tests for Konflux snapshot JSON updates."""

import json
from pathlib import Path

import pytest

from pulp_tool.utils.snapshot_update import (
    SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY,
    update_snapshot_pulp_results_manifest,
)


class TestUpdateSnapshotPulpResultsManifest:
    def test_updates_snapshot_atomically(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text('{"components": []}\n', encoding="utf-8")
        update_snapshot_pulp_results_manifest(snapshot, "quay.io/ns/repo@sha256:abc")
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        assert data[SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY] == "quay.io/ns/repo@sha256:abc"
        assert data["components"] == []

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            update_snapshot_pulp_results_manifest(tmp_path / "missing.json", "ref")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            update_snapshot_pulp_results_manifest(bad, "ref")
