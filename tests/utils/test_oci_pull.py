"""Tests for OCI manifest detection and ORAS pull helper."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.utils.oci_pull import (
    is_oci_artifact_reference,
    normalize_oci_artifact_reference,
    pull_pulp_results_json,
)
from pulp_tool.utils.oras_publish import OrasPublishError


def test_normalize_strips_oci_prefix() -> None:
    ref = "quay.io/ns/repo@sha256:abc"
    assert normalize_oci_artifact_reference(f"oci:{ref}") == ref


def test_is_oci_artifact_reference_manifest() -> None:
    assert is_oci_artifact_reference("quay.io/ns/repo@sha256:deadbeef")
    assert is_oci_artifact_reference("oci:quay.io/ns/repo@sha256:deadbeef")


def test_is_oci_artifact_reference_rejects_http_and_bare_repo() -> None:
    assert not is_oci_artifact_reference("https://pulp.example/artifacts/pulp_results.json")
    assert not is_oci_artifact_reference("quay.io/ns/repo")
    assert not is_oci_artifact_reference("/tmp/pulp_results.json")


class TestPullPulpResultsJson:
    def test_pull_success_prefers_pulp_results_filename(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"

        def _fake_oras(_args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "pulp_results.json").write_text("{}", encoding="utf-8")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            path = pull_pulp_results_json("quay.io/ns/repo@sha256:abc", dest)
        assert path.name == "pulp_results.json"

    def test_pull_oras_failure(self, tmp_path: Path) -> None:
        with patch("pulp_tool.utils.oci_pull._run_oras") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="pull failed")
            with pytest.raises(OrasPublishError, match="oras pull failed"):
                pull_pulp_results_json("quay.io/ns/repo@sha256:abc", tmp_path / "d")

    def test_pull_empty_reference(self) -> None:
        with pytest.raises(OrasPublishError, match="empty"):
            pull_pulp_results_json("oci:", Path("/tmp/unused"))

    def test_pull_clears_existing_files_in_dest(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"
        dest.mkdir()
        stale = dest / "stale.json"
        stale.write_text("{}", encoding="utf-8")

        def _fake_oras(_args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            assert not stale.exists()
            (dest / "pulp_results.json").write_text("{}", encoding="utf-8")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            pull_pulp_results_json("quay.io/ns/repo@sha256:abc", dest)

    def test_pull_falls_back_to_any_json_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"

        def _fake_oras(_args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "other.json").write_text("{}", encoding="utf-8")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            path = pull_pulp_results_json("quay.io/ns/repo@sha256:abc", dest)
        assert path.name == "other.json"

    def test_pull_no_json_after_oras(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"

        with patch("pulp_tool.utils.oci_pull._run_oras") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with pytest.raises(OrasPublishError, match="No .json file"):
                pull_pulp_results_json("quay.io/ns/repo@sha256:abc", dest)
