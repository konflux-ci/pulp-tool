"""Tests for ORAS publish helper."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.utils.oras_publish import (
    OrasPublishError,
    _parse_oras_json_digest,
    _parse_oras_resolve_output,
    attach_pulp_results_manifest,
    copy_oci_artifact,
    push_pulp_results_manifest,
    resolve_oci_manifest,
)


def _auth_ok() -> MagicMock:
    return MagicMock(returncode=0, stdout='{"auths":{}}', stderr="")


class TestOrasPublish:
    def test_attach_pulp_results_manifest_success(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(
                    returncode=0,
                    stdout='{"reference":"quay.io/ns/repo","digest":"sha256:attached"}',
                    stderr="",
                ),
            ]
            ref, digest = attach_pulp_results_manifest(
                "quay.io/ns/repo@sha256:subject",
                '{"version":2}',
            )
        assert ref == "quay.io/ns/repo"
        assert digest == "sha256:attached"
        oras_calls = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "oras"]
        attach_cmds = [cmd for cmd in oras_calls if "attach" in cmd]
        assert attach_cmds
        assert "quay.io/ns/repo@sha256:subject" in attach_cmds[0]

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

    def test_copy_oci_artifact_success(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=0, stdout="", stderr=""),
                _auth_ok(),
                MagicMock(returncode=0, stdout="sha256:copied", stderr=""),
            ]
            ref = copy_oci_artifact("quay.io/ns/src@sha256:src", "quay.io/ns/target:release")
        assert ref == "quay.io/ns/target@sha256:copied"
        oras_cmds = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "oras"]
        cp_cmds = [cmd for cmd in oras_cmds if len(cmd) > 1 and cmd[1] == "cp"]
        assert cp_cmds
        assert "--from-registry-config" in cp_cmds[0]
        assert "--to-registry-config" in cp_cmds[0]
        assert "quay.io/ns/src@sha256:src" in cp_cmds[0]
        assert "quay.io/ns/target:release" in cp_cmds[0]

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

    def test_attach_rejects_non_digest_subject(self) -> None:
        with pytest.raises(OrasPublishError, match="digest-pinned"):
            attach_pulp_results_manifest("quay.io/ns/repo:latest", "{}")

    def test_attach_rejects_non_sha256_digest(self) -> None:
        with pytest.raises(OrasPublishError, match="sha256 digest"):
            attach_pulp_results_manifest("quay.io/ns/repo@deadbeef", "{}")

    def test_attach_oras_failure(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=1, stdout="", stderr="attach failed"),
            ]
            with pytest.raises(OrasPublishError, match="oras attach failed"):
                attach_pulp_results_manifest("quay.io/ns/repo@sha256:subject", "{}")

    def test_copy_invalid_source_or_target(self) -> None:
        with pytest.raises(OrasPublishError, match="digest-pinned"):
            copy_oci_artifact("quay.io/ns/repo:latest", "quay.io/t:tag")
        with pytest.raises(OrasPublishError, match="empty"):
            copy_oci_artifact("quay.io/ns/repo@sha256:abc", "  ")

    def test_copy_with_merged_registry_and_tls(self, tmp_path) -> None:
        extra = tmp_path / "extra.json"
        extra.write_text('{"auths":{"registry.example.com":{"auth":"e"}}}', encoding="utf-8")
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout='{"auths":{"quay.io":{}}}', stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout="sha256:copied", stderr=""),
            ]
            ref = copy_oci_artifact(
                "quay.io/ns/src@sha256:src",
                "quay.io/ns/target:release",
                extra_registry_config_path=str(extra),
                client_tls_cert=("/cert.pem", "/key.pem"),
            )
        assert ref.endswith("sha256:copied")
        oras_cmd = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "oras"][0]
        assert oras_cmd[1] == "cp"
        assert "--from-registry-config" in oras_cmd
        assert "--to-registry-config" in oras_cmd
        assert "--to-cert-file" in oras_cmd and "--to-key-file" in oras_cmd

    def test_copy_uses_split_destination_registry_config(self, tmp_path: Path) -> None:
        extra = tmp_path / "pulp-auth.json"
        extra.write_text('{"auths":{"registry.example.com":{}}}', encoding="utf-8")
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout='{"auths":{"quay.io":{}}}', stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout="sha256:ok", stderr=""),
            ]
            copy_oci_artifact(
                "quay.io/ns/src@sha256:src",
                "registry.example.com/ns/target:release",
                extra_registry_config_path=str(extra),
                destination_cp_flags=["--to-username", "u", "--to-password", "p"],
            )
        cp_cmd = [c.args[0] for c in mock_run.call_args_list if len(c.args[0]) > 2 and c.args[0][1] == "cp"][0]
        assert "--from-registry-config" in cp_cmd
        assert "--to-registry-config" in cp_cmd
        to_idx = cp_cmd.index("--to-registry-config")
        assert cp_cmd[to_idx + 1] == str(extra)
        assert "--to-username" in cp_cmd and "--to-password" in cp_cmd

    def test_resolve_with_client_tls_uses_global_cert_flags(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=0, stdout="sha256:tlsresolve", stderr=""),
            ]
            ref, digest = resolve_oci_manifest(
                "registry.example.com/ns/oci/bid:latest",
                client_tls_cert=("/cert.pem", "/key.pem"),
            )
        assert ref == "registry.example.com/ns/oci/bid"
        assert digest == "sha256:tlsresolve"
        oras_cmd = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "oras"][0]
        assert oras_cmd[1] == "--registry-config"
        assert "--cert" in oras_cmd and "--key" in oras_cmd

    def test_load_registry_auths_invalid_json(self, tmp_path) -> None:
        from pulp_tool.utils.oras_publish import _load_registry_auths

        bad = tmp_path / "bad.json"
        bad.write_text("{", encoding="utf-8")
        with pytest.raises(OrasPublishError, match="Invalid registry config"):
            _load_registry_auths(str(bad))

    def test_load_registry_auths_missing_auths_key(self, tmp_path) -> None:
        from pulp_tool.utils.oras_publish import _load_registry_auths

        path = tmp_path / "ok.json"
        path.write_text("{}", encoding="utf-8")
        assert _load_registry_auths(str(path)) == {}

    def test_copy_cp_failure(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=2, stdout="", stderr="cp failed"),
            ]
            with pytest.raises(OrasPublishError, match="oras cp failed"):
                copy_oci_artifact("quay.io/ns/src@sha256:src", "quay.io/ns/target:release")

    def test_copy_resolves_destination_after_cp(self) -> None:
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                _auth_ok(),
                MagicMock(returncode=0, stdout="", stderr=""),
                _auth_ok(),
                MagicMock(returncode=0, stdout="sha256:resolved", stderr=""),
            ]
            ref = copy_oci_artifact("quay.io/ns/src@sha256:src", "quay.io/ns/target:release")
        assert ref == "quay.io/ns/target@sha256:resolved"

    def test_parse_oras_json_digest_errors(self) -> None:
        repo = "quay.io/ns/repo"
        with pytest.raises(OrasPublishError, match="empty JSON"):
            _parse_oras_json_digest("  ", repo)
        with pytest.raises(OrasPublishError, match="parse failed"):
            _parse_oras_json_digest("{", repo)
        with pytest.raises(OrasPublishError, match="must be an object"):
            _parse_oras_json_digest("[]", repo)
        with pytest.raises(OrasPublishError, match="missing digest"):
            _parse_oras_json_digest("{}", repo)
        ref, digest = _parse_oras_json_digest('{"digest":"abc"}', repo)
        assert ref == repo
        assert digest == "sha256:abc"
