"""Tests for shared pulp_results ORAS publish helper."""

from unittest.mock import Mock, patch

import pytest

from pulp_tool.utils.oras_publish import OrasPublishError
from pulp_tool.utils.pulp_results_oci_publish import sync_pulp_results_with_oci_registry


class TestSyncPulpResultsWithOciRegistry:
    def test_sync_sets_version_and_publishes(self) -> None:
        mock_client = Mock()
        document: dict = {"artifacts": {}, "distributions": {}}
        mock_task = Mock()
        with (
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                return_value=mock_task,
            ) as mock_upload,
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/ns/repo", "sha256:one"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/ns/repo", "sha256:final"),
            ),
        ):
            oci_ref, task = sync_pulp_results_with_oci_registry(
                mock_client,
                "artifacts-prn",
                document,
                "quay.io/ns/repo:latest",
                {"build_id": "b1"},
                build_id="b1",
            )
        assert document["version"] == 1
        assert document["oci_manifest"] == "quay.io/ns/repo@sha256:final"
        assert oci_ref == "quay.io/ns/repo@sha256:final"
        assert task is mock_task
        assert mock_upload.call_count == 3

    def test_sync_requires_oci_storage(self) -> None:
        with pytest.raises(ValueError, match="oci_storage is required"):
            sync_pulp_results_with_oci_registry(Mock(), "prn", {}, "  ", {}, build_id="b1")

    def test_sync_records_manifest_history(self) -> None:
        mock_client = Mock()
        document: dict = {"artifacts": {}, "oci_manifest": "quay.io/r@sha256:old"}
        with (
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                return_value=Mock(),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/r", "sha256:one"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/r", "sha256:final"),
            ),
            patch("pulp_tool.utils.pulp_results_oci_publish.append_oci_manifest_history") as mock_hist,
        ):
            sync_pulp_results_with_oci_registry(
                mock_client,
                "prn",
                document,
                "quay.io/r:tag",
                {},
                build_id="b1",
                record_manifest_history=True,
            )
        mock_hist.assert_called_once()

    def test_sync_wraps_oras_publish_error(self) -> None:
        with (
            patch("pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait", return_value=Mock()),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                side_effect=OrasPublishError("oras down"),
            ),
        ):
            with pytest.raises(OrasPublishError, match="oras down"):
                sync_pulp_results_with_oci_registry(
                    Mock(),
                    "prn",
                    {"artifacts": {}},
                    "quay.io/r:tag",
                    {},
                    build_id="b1",
                )
