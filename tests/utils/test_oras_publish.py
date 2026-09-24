"""Tests for ORAS publish helper."""

from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.utils.oras_publish import OrasPublishError, push_pulp_results_manifest, resolve_oci_manifest


def _auth_ok() -> MagicMock:
    return MagicMock(returncode=0, stdout='{"auths":{}}', stderr="")


class TestOrasPublish:
    def test_push_pulp_results_manifest_success(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=0, stdout="", stderr=""),
                _auth_ok(),
                MagicMock(returncode=0, stdout="quay.io/ns/repo@sha256:abc123", stderr=""),
            ]
            ref, digest = push_pulp_results_manifest("quay.io/ns/repo:latest", '{"version":1}')
        assert ref == "quay.io/ns/repo"
        assert digest == "sha256:abc123"
        oras_calls = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "oras"]
        assert all("--registry-config" in cmd for cmd in oras_calls)

    def test_push_pulp_results_manifest_push_failure(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=1, stdout="", stderr="push failed"),
            ]
            with pytest.raises(OrasPublishError, match="oras push failed"):
                push_pulp_results_manifest("quay.io/ns/repo:latest", "{}")

    def test_push_pulp_results_manifest_missing_select_oci_auth(self) -> None:
        with patch("pulp_tool.utils.oras_publish.shutil.which", return_value=None):
            with pytest.raises(OrasPublishError, match="select-oci-auth not found"):
                push_pulp_results_manifest("quay.io/ns/repo:latest", "{}")

    def test_resolve_oci_manifest_success(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=0, stdout="quay.io/ns/repo@sha256:abc123", stderr=""),
            ]
            ref, digest = resolve_oci_manifest("quay.io/ns/repo:latest")
        assert ref == "quay.io/ns/repo"
        assert digest == "sha256:abc123"
