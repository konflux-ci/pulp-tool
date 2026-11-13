"""Tests for OCI manifest detection and ORAS pull helper."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.utils.oci_pull import (
    _ensure_extracted_files_under_dest,
    _extract_referrer_digests_from_discover_payload,
    discover_pulp_results_referrer_refs,
    is_oci_artifact_reference,
    normalize_oci_artifact_reference,
    pull_pulp_results_json,
    resolve_oci_transfer_artifact,
    resolve_pulp_results_oci_pull_ref,
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


class TestEnsureExtractedFilesUnderDest:
    def test_skips_non_file_paths(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"
        sub = dest / "nested"
        sub.mkdir(parents=True)
        (sub / "pulp_results.json").write_text("{}", encoding="utf-8")
        _ensure_extracted_files_under_dest(dest)

    def test_rejects_file_outside_destination(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"
        dest.mkdir()
        outside = tmp_path / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        link = dest / "escape"
        link.symlink_to(outside)
        with pytest.raises(OrasPublishError, match="outside destination"):
            _ensure_extracted_files_under_dest(dest)


class TestPullPulpResultsJson:
    def test_pull_success_prefers_pulp_results_filename(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in args:
                return MagicMock(returncode=1, stdout="", stderr="no referrers")
            assert "pull" in args
            assert "--allow-path-traversal" not in args
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
            if "discover" in _args:
                return MagicMock(returncode=1, stdout="", stderr="")
            assert not stale.exists()
            (dest / "pulp_results.json").write_text("{}", encoding="utf-8")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            pull_pulp_results_json("quay.io/ns/repo@sha256:abc", dest)

    def test_pull_falls_back_to_any_json_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"

        def _fake_oras(_args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in _args:
                return MagicMock(returncode=1, stdout="", stderr="")
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

    def test_pull_uses_attached_referrer_when_discovered(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"
        subject = "quay.io/ns/repo@sha256:subject"
        referrer = "quay.io/ns/repo@sha256:attached"
        pulled_refs: list[str] = []

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in args:
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps({"manifests": [{"digest": "sha256:attached"}]}),
                    stderr="",
                )
            if "pull" in args:
                pulled_refs.append(args[args.index("pull") + 1])
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "pulp_results.json").write_text('{"version": 2}', encoding="utf-8")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            pull_pulp_results_json(subject, dest)
        assert pulled_refs == [referrer]

    def test_resolve_prefers_latest_last_updated_among_referrers(self) -> None:
        subject = "quay.io/ns/repo@sha256:subject"
        ref_b = "quay.io/ns/repo@sha256:bbbb"

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in args:
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "manifests": [
                                {"digest": "sha256:aaaa"},
                                {"digest": "sha256:bbbb"},
                            ]
                        }
                    ),
                    stderr="",
                )
            if "pull" in args:
                ref = args[args.index("pull") + 1]
                out_dir = Path(args[args.index("-o") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                last_updated = "2026-01-01" if ref.endswith("aaaa") else "2026-03-01"
                (out_dir / "pulp_results.json").write_text(
                    json.dumps({"version": "1.0.0", "last_updated": last_updated}),
                    encoding="utf-8",
                )
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            assert resolve_pulp_results_oci_pull_ref(subject) == ref_b


class TestExtractReferrerDigests:
    def test_list_payload_and_reference_field(self) -> None:
        data = [
            {"reference": "quay.io/ns/repo@deadbeef"},
            "skip",
            {"digest": "abc123"},
        ]
        digests = _extract_referrer_digests_from_discover_payload(data)
        assert digests == ["sha256:deadbeef", "sha256:abc123"]

    def test_dict_referrers_key(self) -> None:
        digests = _extract_referrer_digests_from_discover_payload({"referrers": [{"digest": "sha256:already"}]})
        assert digests == ["sha256:already"]

    def test_skips_invalid_items(self) -> None:
        assert _extract_referrer_digests_from_discover_payload({"manifests": [None, {"digest": 42}]}) == []
        assert _extract_referrer_digests_from_discover_payload({"manifests": [{"reference": 99}]}) == []


class TestDiscoverPulpResultsReferrers:
    def test_invalid_discover_json_returns_empty(self) -> None:
        with patch("pulp_tool.utils.oci_pull._run_oras") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="not-json", stderr="")
            assert discover_pulp_results_referrer_refs("quay.io/ns/r@sha256:sub") == []


class TestOrasPullRefToDir:
    def test_empty_reference_raises(self, tmp_path: Path) -> None:
        with pytest.raises(OrasPublishError, match="empty"):
            from pulp_tool.utils.oci_pull import _oras_pull_ref_to_dir

            _oras_pull_ref_to_dir("  ", tmp_path)

    def test_pull_without_clearing_existing_files(self, tmp_path: Path) -> None:
        from pulp_tool.utils.oci_pull import _oras_pull_ref_to_dir

        dest = tmp_path / "dest"
        dest.mkdir()
        keep = dest / "keep.txt"
        keep.write_text("stay", encoding="utf-8")

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            _oras_pull_ref_to_dir("quay.io/ns/r@sha256:abc", dest, clear_files=False)
        assert keep.read_text(encoding="utf-8") == "stay"


class TestResolveOciTransferArtifact:
    def test_empty_subject_raises(self, tmp_path: Path) -> None:
        with pytest.raises(OrasPublishError, match="empty"):
            resolve_oci_transfer_artifact("  ", tmp_path)

    def test_referrer_pull_success(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        subject = "quay.io/ns/repo@sha256:subject"

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in args:
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps({"manifests": [{"digest": "sha256:attach"}]}),
                    stderr="",
                )
            if "pull" in args:
                out_dir = Path(args[args.index("-o") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "pulp_results.json").write_text("{}", encoding="utf-8")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            res = resolve_oci_transfer_artifact(subject, work)
        assert res.kind == "pulp_results"

    def test_referrer_pull_failure_falls_back_to_subject(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        subject = "quay.io/ns/repo@sha256:subject"

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in args:
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps({"manifests": [{"digest": "sha256:bad"}]}),
                    stderr="",
                )
            if "pull" in args:
                ref = args[args.index("pull") + 1]
                out_dir = Path(args[args.index("-o") + 1])
                if "bad" in ref:
                    return MagicMock(returncode=1, stdout="", stderr="nope")
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "pulp_results.json").write_text("{}", encoding="utf-8")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            res = resolve_oci_transfer_artifact(subject, work)
        assert res.kind == "pulp_results"

    def test_no_json_and_no_rpms_raises(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        subject = "quay.io/ns/repo@sha256:subject"

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in args:
                return MagicMock(returncode=1, stdout="", stderr="")
            if "pull" in args:
                out_dir = Path(args[args.index("-o") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            with pytest.raises(OrasPublishError, match="no pulp_results"):
                resolve_oci_transfer_artifact(subject, work)

    def test_bundle_fallback_when_no_json(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        subject = "quay.io/ns/repo@sha256:subject"

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in args:
                return MagicMock(returncode=1, stdout="", stderr="")
            if "pull" in args:
                out_dir = Path(args[args.index("-o") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "pkg.noarch.rpm").write_bytes(b"fake rpm")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            res = resolve_oci_transfer_artifact(subject, work)
        assert res.kind == "oci_bundle"
        assert res.bundle_dir is not None
        assert (res.bundle_dir / "pkg.noarch.rpm").is_file()

    def test_subject_json_before_bundle(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        subject = "quay.io/ns/repo@sha256:subject"

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in args:
                return MagicMock(returncode=1, stdout="", stderr="")
            if "pull" in args:
                out_dir = Path(args[args.index("-o") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "pulp_results.json").write_text('{"version": "1.0.0", "artifacts": {}}', encoding="utf-8")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            res = resolve_oci_transfer_artifact(subject, work)
        assert res.kind == "pulp_results"
        assert res.pulp_results_path is not None
        assert res.pulp_results_path.name == "pulp_results.json"


class TestSelectNewestReferrerSkipsBadCandidates:
    def test_resolve_skips_unpullable_referrer(self) -> None:
        subject = "quay.io/ns/repo@sha256:subject"
        good = "quay.io/ns/repo@sha256:good"

        def _fake_oras(args: list[str], _target: str, *, cwd: str | Path | None = None) -> MagicMock:
            if "discover" in args:
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {"manifests": [{"digest": "sha256:bad"}, {"digest": "sha256:good"}]},
                    ),
                    stderr="",
                )
            if "pull" in args:
                ref = args[args.index("pull") + 1]
                if ref.endswith("bad"):
                    return MagicMock(returncode=1, stdout="", stderr="fail")
                out_dir = Path(args[args.index("-o") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "pulp_results.json").write_text('{"last_updated": "2026-06-01"}', encoding="utf-8")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("pulp_tool.utils.oci_pull._run_oras", side_effect=_fake_oras):
            assert resolve_pulp_results_oci_pull_ref(subject) == good
