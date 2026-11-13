"""Tests for OCI transfer resolution model."""

from pathlib import Path

from pulp_tool.models.oci_transfer import OciTransferResolution


def test_ok_pulp_results_when_file_exists(tmp_path: Path) -> None:
    json_path = tmp_path / "pulp_results.json"
    json_path.write_text("{}", encoding="utf-8")
    res = OciTransferResolution(kind="pulp_results", pulp_results_path=json_path)
    assert res.ok
    assert res.bundle_dir is None


def test_ok_pulp_results_false_when_missing_file(tmp_path: Path) -> None:
    res = OciTransferResolution(kind="pulp_results", pulp_results_path=tmp_path / "missing.json")
    assert not res.ok


def test_ok_bundle_when_directory_exists(tmp_path: Path) -> None:
    res = OciTransferResolution(kind="oci_bundle", bundle_dir=tmp_path)
    assert res.ok


def test_ok_bundle_false_when_dir_missing(tmp_path: Path) -> None:
    res = OciTransferResolution(kind="oci_bundle", bundle_dir=tmp_path / "nope")
    assert not res.ok
