"""Tests for ORAS publish helper."""

from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.utils.oras_publish import (
    OrasPublishError,
    _parse_oras_resolve_output,
    push_pulp_results_manifest,
    resolve_oci_manifest,
)


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
        push_cmds = [cmd for cmd in oras_calls if "push" in cmd]
        assert push_cmds
        push_idx = push_cmds[0].index("push")
        assert push_cmds[0][push_idx + 1] == "quay.io/ns/repo:latest"
        assert "pulp_results.json:" in push_cmds[0][-1]

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

    def test_resolve_bare_oci_storage_uses_latest(self) -> None:
        storage = "quay.io/redhat-user-workloads/artifact-storage-tenant/tooling/pulp-e2e-testing"
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=0, stdout="sha256:abc123", stderr=""),
            ]
            ref, digest = resolve_oci_manifest(storage)
        assert ref == storage
        assert digest == "sha256:abc123"
        oras_cmd = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "oras"][0]
        resolve_idx = oras_cmd.index("resolve")
        assert oras_cmd[resolve_idx + 1] == f"{storage}:latest"

    def test_parse_oras_resolve_digest_only(self) -> None:
        storage = "quay.io/ns/repo"
        ref, digest = _parse_oras_resolve_output(storage, "sha256:deadbeef")
        assert ref == storage
        assert digest == "sha256:deadbeef"

    def test_parse_oras_resolve_empty_output(self) -> None:
        with pytest.raises(OrasPublishError, match="empty output"):
            _parse_oras_resolve_output("quay.io/ns/repo", "   ")

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

    def test_select_oci_auth_failure(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="auth failed")
            with pytest.raises(OrasPublishError, match="select-oci-auth failed"):
                resolve_oci_manifest("quay.io/ns/repo:latest")

    def test_resolve_empty_target(self) -> None:
        with pytest.raises(OrasPublishError, match="empty"):
            resolve_oci_manifest("   ")

    def test_resolve_oras_command_failure(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=2, stdout="", stderr="resolve err"),
            ]
            with pytest.raises(OrasPublishError, match="oras resolve failed"):
                resolve_oci_manifest("quay.io/ns/repo:latest")

    def test_resolve_unexpected_output(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=0, stdout="no-digest-here", stderr=""),
            ]
            with pytest.raises(OrasPublishError, match="unexpected value"):
                resolve_oci_manifest("quay.io/ns/repo:latest")

    def test_push_empty_target(self) -> None:
        with pytest.raises(OrasPublishError, match="empty"):
            push_pulp_results_manifest("", "{}")
