"""Tests for ORAS publish helper."""

import json
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

    def test_registry_config_has_auth_for_host(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oras_publish import registry_config_has_auth_for_host

        cfg = tmp_path / "cfg.json"
        cfg.write_text('{"auths":{"packages.redhat.com:443":{"auth":"x"}}}', encoding="utf-8")
        assert registry_config_has_auth_for_host(str(cfg), "packages.redhat.com")
        cfg.write_text('{"auths":{"quay.io":{"auth":"x"}}}', encoding="utf-8")
        assert not registry_config_has_auth_for_host(str(cfg), "packages.redhat.com")

    def test_merge_registry_config_paths_public_wrapper(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oras_publish import merge_registry_config_paths

        first = tmp_path / "a.json"
        second = tmp_path / "b.json"
        first.write_text('{"auths":{"a":{"auth":"1"}}}', encoding="utf-8")
        second.write_text('{"auths":{"b":{"auth":"2"}}}', encoding="utf-8")
        merged = merge_registry_config_paths(str(first), str(second))
        data = json.loads(Path(merged).read_text(encoding="utf-8"))
        Path(merged).unlink(missing_ok=True)
        assert data["auths"]["a"]["auth"] == "1"
        assert data["auths"]["b"]["auth"] == "2"

    def test_write_merged_registry_config_combines_auths(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oras_publish import _write_merged_registry_config

        first = tmp_path / "a.json"
        second = tmp_path / "b.json"
        first.write_text('{"auths":{"quay.io":{"auth":"a"}}}', encoding="utf-8")
        second.write_text('{"auths":{"reg.example.com":{"auth":"b"}}}', encoding="utf-8")
        merged_path = _write_merged_registry_config(str(first), str(second))
        data = json.loads(Path(merged_path).read_text(encoding="utf-8"))
        Path(merged_path).unlink(missing_ok=True)
        assert data["auths"]["quay.io"]["auth"] == "a"
        assert data["auths"]["reg.example.com"]["auth"] == "b"

    def test_oci_registry_config_merges_extra_and_cleans_up(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oras_publish import _oci_registry_config

        extra = tmp_path / "pulp-auth.json"
        extra.write_text('{"auths":{"packages.redhat.com":{"auth":"p"}}}', encoding="utf-8")
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch(
                "pulp_tool.utils.oras_publish.subprocess.run",
                return_value=_auth_ok(),
            ),
        ):
            with _oci_registry_config("quay.io/ns/repo:tag", extra_registry_config_path=str(extra)) as merged_path:
                merged = json.loads(Path(merged_path).read_text(encoding="utf-8"))
                assert merged["auths"]["packages.redhat.com"]["auth"] == "p"
            assert not Path(merged_path).exists()

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

    def test_copy_pulp_auth_falls_back_to_select_oci_auth(self) -> None:
        client = MagicMock()
        client.config = {"base_url": "https://packages.redhat.com", "username": "u", "password": "p"}
        client.cert = None
        dest = "packages.redhat.com/ns/oci/bid:latest"
        with (
            patch("pulp_tool.utils.oras_publish.shutil.which", return_value="/usr/local/bin/select-oci-auth"),
            patch(
                "pulp_tool.utils.pulp_container_oci.build_pulp_cp_registry_config_for_ref",
                return_value=(str(Path("/tmp/pulp-reg.json")), ["--to-username", "u", "--to-password", "p"]),
            ),
            patch(
                "pulp_tool.utils.pulp_container_oci.uses_pulp_container_registry",
                side_effect=lambda ref, _c: "packages.redhat.com" in ref,
            ),
            patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout='{"auths":{}}', stderr=""),
                MagicMock(returncode=1, stdout="", stderr="denied: not authorized"),
                MagicMock(returncode=0, stdout='{"auths":{}}', stderr=""),
                MagicMock(returncode=0, stdout='{"auths":{}}', stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout='{"auths":{}}', stderr=""),
                MagicMock(returncode=0, stdout="sha256:fallback", stderr=""),
            ]
            ref = copy_oci_artifact(
                "quay.io/ns/src@sha256:src",
                dest,
                pulp_client=client,
            )
        assert ref.endswith("sha256:fallback")
        cp_cmds = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "oras" and c.args[0][1] == "cp"]
        assert len(cp_cmds) == 2

    def test_is_oras_auth_failure(self) -> None:
        from pulp_tool.utils.oras_publish import _is_oras_auth_failure

        ok = MagicMock(returncode=0, stdout="", stderr="")
        assert not _is_oras_auth_failure(ok)
        denied = MagicMock(returncode=1, stdout="", stderr="denied: Access not authorized")
        assert _is_oras_auth_failure(denied)
        other = MagicMock(returncode=1, stdout="manifest unknown", stderr="")
        assert not _is_oras_auth_failure(other)

    def test_run_oras_cp_hybrid_explicit_tls_and_cp_flags(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oras_publish import _run_oras_cp_hybrid

        from_cfg = tmp_path / "from.json"
        to_cfg = tmp_path / "to.json"
        from_cfg.write_text('{"auths":{}}', encoding="utf-8")
        to_cfg.write_text('{"auths":{}}', encoding="utf-8")
        with patch("pulp_tool.utils.oras_publish.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_oras_cp_hybrid(
                "quay.io/ns/src@sha256:src",
                "packages.redhat.com/ns/oci/b:latest",
                from_registry_config=str(from_cfg),
                to_registry_config=str(to_cfg),
                from_client_tls_cert=("/from-cert.pem", "/from-key.pem"),
                to_client_tls_cert=("/to-cert.pem", "/to-key.pem"),
                from_cp_flags=["--from-username", "fu", "--from-password", "fp"],
                destination_cp_flags=["--to-username", "tu", "--to-password", "tp"],
            )
        cmd = mock_run.call_args.args[0]
        assert "--from-cert-file" in cmd and "--from-key-file" in cmd
        assert "--to-cert-file" in cmd and "--to-key-file" in cmd
        assert "--from-username" in cmd and "--to-password" in cmd

    def test_oras_cp_pulp_auth_success_defers_dest_config_cleanup(self) -> None:
        from pulp_tool.utils.oras_publish import _oras_cp_with_pulp_auth_fallback

        client = MagicMock()
        client.config = {
            "base_url": "https://packages.redhat.com",
            "username": "u",
            "password": "p",
            "cert": "/cert.pem",
        }
        client.config_path = None
        client.cert = ("/cert.pem", "/key.pem")
        with (
            patch(
                "pulp_tool.utils.pulp_container_oci.uses_pulp_container_registry",
                return_value=True,
            ),
            patch(
                "pulp_tool.utils.oras_publish._run_oras_cp_hybrid",
                return_value=MagicMock(returncode=0, stdout="", stderr=""),
            ),
        ):
            result, resolve_cfg, resolve_tls, defer = _oras_cp_with_pulp_auth_fallback(
                client,
                "packages.redhat.com/ns/src@sha256:abc",
                "packages.redhat.com/ns/oci/b:latest",
            )
        assert result.returncode == 0
        assert resolve_cfg
        assert resolve_tls == ("/cert.pem", "/key.pem")
        assert defer == [resolve_cfg]
        for path in defer:
            assert Path(path).exists()
        Path(defer[0]).unlink(missing_ok=True)

    def test_oras_cp_pulp_non_auth_failure_unlinks_configs(self) -> None:
        from pulp_tool.utils.oras_publish import _oras_cp_with_pulp_auth_fallback

        client = MagicMock()
        client.config = {"base_url": "https://packages.redhat.com", "username": "u", "password": "p"}
        client.config_path = None
        client.cert = None
        with (
            patch(
                "pulp_tool.utils.pulp_container_oci.uses_pulp_container_registry",
                side_effect=lambda ref, _c: ref.startswith("packages.redhat.com"),
            ),
            patch(
                "pulp_tool.utils.oras_publish._run_oras_cp_hybrid",
                return_value=MagicMock(returncode=1, stdout="manifest unknown", stderr=""),
            ) as mock_hybrid,
        ):
            result, resolve_cfg, resolve_tls, defer = _oras_cp_with_pulp_auth_fallback(
                client,
                "quay.io/ns/src@sha256:src",
                "packages.redhat.com/ns/oci/b:latest",
            )
        assert result.returncode == 1
        assert resolve_cfg is None and resolve_tls is None and defer == []
        assert mock_hybrid.call_count == 1

    def test_select_registry_config_for_cp_merges_pulp_when_select_lacks_host(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oras_publish import _select_registry_config_for_cp

        client = MagicMock()
        client.config = {"base_url": "https://packages.redhat.com", "username": "u", "password": "p"}
        client.config_path = None
        client.cert = None
        select_only = tmp_path / "select.json"
        select_only.write_text('{"auths":{"quay.io":{"auth":"x"}}}', encoding="utf-8")
        dest = "packages.redhat.com/ns/oci/bid:latest"
        with (
            patch(
                "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
                return_value=str(select_only),
            ),
            patch(
                "pulp_tool.utils.pulp_container_oci.uses_pulp_container_registry",
                return_value=True,
            ),
        ):
            path = _select_registry_config_for_cp(dest, client=client, extra_config_paths=(), side="to")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        Path(path).unlink(missing_ok=True)
        assert "packages.redhat.com" in data["auths"] or "packages.redhat.com:443" in data["auths"]

    def test_select_registry_config_skips_merge_when_select_has_host_auth(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oras_publish import _select_registry_config_for_cp

        select_path = tmp_path / "select.json"
        select_path.write_text(
            '{"auths":{"packages.redhat.com:443":{"auth":"x"}}}',
            encoding="utf-8",
        )
        client = MagicMock()
        with (
            patch(
                "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
                return_value=str(select_path),
            ),
            patch(
                "pulp_tool.utils.pulp_container_oci.uses_pulp_container_registry",
                return_value=True,
            ),
        ):
            path = _select_registry_config_for_cp(
                "packages.redhat.com/ns/oci/bid:latest",
                client=client,
                extra_config_paths=(),
                side="to",
            )
        assert path == str(select_path)

    def test_select_registry_config_returns_select_without_pulp_creds(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oras_publish import _select_registry_config_for_cp

        select_path = tmp_path / "select.json"
        select_path.write_text('{"auths":{}}', encoding="utf-8")
        client = MagicMock()
        client.config = {"cert": "/tls.crt"}
        client.config_path = None
        client.cert = None
        with (
            patch(
                "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
                return_value=str(select_path),
            ),
            patch(
                "pulp_tool.utils.pulp_container_oci.uses_pulp_container_registry",
                return_value=True,
            ),
        ):
            path = _select_registry_config_for_cp(
                "packages.redhat.com/ns/oci/bid:latest",
                client=client,
                extra_config_paths=(),
                side="to",
            )
        assert path == str(select_path)

    def test_select_registry_config_returns_select_when_pulp_config_empty(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oras_publish import _select_registry_config_for_cp

        select_path = tmp_path / "select.json"
        select_path.write_text('{"auths":{}}', encoding="utf-8")
        client = MagicMock()
        with (
            patch(
                "pulp_tool.utils.oras_publish.select_oci_auth_registry_config_path",
                return_value=str(select_path),
            ),
            patch(
                "pulp_tool.utils.pulp_container_oci.uses_pulp_container_registry",
                return_value=True,
            ),
            patch(
                "pulp_tool.utils.pulp_container_oci._pulp_registry_credentials",
                return_value=("u", "p"),
            ),
            patch(
                "pulp_tool.utils.pulp_container_oci.build_pulp_cp_registry_config_for_ref",
                return_value=(None, []),
            ),
        ):
            path = _select_registry_config_for_cp(
                "packages.redhat.com/ns/oci/bid:latest",
                client=client,
                extra_config_paths=(),
                side="to",
            )
        assert path == str(select_path)

    def test_copy_pulp_auth_success_unlinks_deferred_temp_configs(self, tmp_path: Path) -> None:
        client = MagicMock()
        client.config = {"username": "u", "password": "p"}
        client.cert = None
        defer_path = tmp_path / "defer.json"
        defer_path.write_text('{"auths":{}}', encoding="utf-8")
        with (
            patch(
                "pulp_tool.utils.oras_publish._oras_cp_with_pulp_auth_fallback",
                return_value=(
                    MagicMock(returncode=0, stdout="", stderr=""),
                    str(defer_path),
                    None,
                    [str(defer_path)],
                ),
            ),
            patch(
                "pulp_tool.utils.oras_publish.resolve_oci_manifest",
                return_value=("packages.redhat.com/ns/oci/bid", "sha256:ok"),
            ),
        ):
            ref = copy_oci_artifact(
                "quay.io/ns/src@sha256:src",
                "packages.redhat.com/ns/oci/bid:latest",
                pulp_client=client,
            )
        assert ref.endswith("sha256:ok")
        assert not defer_path.exists()
