"""Tests for Konflux snapshot JSON updates."""

import json
from pathlib import Path

import pytest

from pulp_tool.utils.snapshot_update import (
    SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY,
    SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY,
    update_snapshot_component_container_images,
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

    def test_empty_manifest_ref_raises(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            update_snapshot_pulp_results_manifest(snapshot, "  ")


class TestUpdateSnapshotComponentContainerImages:
    def test_snapshot_root_must_be_object(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text("[]\n", encoding="utf-8")
        with pytest.raises(ValueError, match="JSON object"):
            update_snapshot_component_container_images(snapshot, "quay.io/x@sha256:1")

    def test_empty_container_image_ref_raises(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text('{"components":[]}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            update_snapshot_component_container_images(snapshot, "  ")

    def test_updates_matching_digest_only(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text(
            json.dumps(
                {
                    "components": [
                        {
                            "name": "a",
                            SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY: "quay.io/ns/a@sha256:aaaa",
                        },
                        {
                            "name": "b",
                            SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY: "quay.io/ns/b@sha256:bbbb",
                        },
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        updated = update_snapshot_component_container_images(
            snapshot,
            "quay.io/release/target@sha256:newdigest",
            match_source_ref="quay.io/ns/a@sha256:aaaa",
        )
        assert updated == 1
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        assert data["components"][0][SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY].endswith("newdigest")
        assert data["components"][1][SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY].endswith("bbbb")

    def test_digest_without_sha256_prefix_matches(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text(
            json.dumps(
                {
                    "components": [
                        {
                            "name": "a",
                            SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY: "quay.io/ns/a@deadbeef",
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        updated = update_snapshot_component_container_images(
            snapshot,
            "quay.io/release@sha256:new",
            match_source_ref="quay.io/ns/a@sha256:deadbeef",
        )
        assert updated == 1

    def test_components_defaults_to_empty_list(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text("{}\n", encoding="utf-8")
        assert update_snapshot_component_container_images(snapshot, "quay.io/x@sha256:1") == 0

    def test_components_must_be_array(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text('{"components": "nope"}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="array"):
            update_snapshot_component_container_images(snapshot, "quay.io/x@sha256:1")

    def test_component_must_be_object(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text('{"components": [1]}\n', encoding="utf-8")
        with pytest.raises(TypeError):
            update_snapshot_component_container_images(snapshot, "quay.io/x@sha256:1")

    def test_skips_components_without_container_image(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text('{"components": [{"name": "bare"}]}\n', encoding="utf-8")
        assert update_snapshot_component_container_images(snapshot, "quay.io/x@sha256:1") == 0

    def test_no_match_leaves_file_unchanged(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "snapshot.json"
        before = '{"components": [{"containerImage": "quay.io/x@sha256:1111"}]}\n'
        snapshot.write_text(before, encoding="utf-8")
        updated = update_snapshot_component_container_images(
            snapshot,
            "quay.io/y@sha256:2222",
            match_source_ref="quay.io/z@sha256:9999",
        )
        assert updated == 0
        assert snapshot.read_text(encoding="utf-8") == before
