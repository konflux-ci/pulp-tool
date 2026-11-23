"""Tests for intermediate ORAS bundle ingestion."""

from pathlib import Path

import pytest

from pulp_tool.models.context import PullContext
from pulp_tool.pull.oras_bundle import collect_pulled_artifacts_from_oras_bundle


def test_collect_rpms_from_nested_bundle(tmp_path: Path) -> None:
    nested = tmp_path / "layers" / "rpms"
    nested.mkdir(parents=True)
    rpm = nested / "test-1.0-1.noarch.rpm"
    rpm.write_bytes(b"%PDF-rpm-stub")

    context = PullContext(
        build_id="ns/build-1",
        namespace="ns",
        operation_label="transfer",
    )
    pulled = collect_pulled_artifacts_from_oras_bundle(tmp_path, context)
    assert len(pulled.rpms) == 1
    assert "test-1.0-1.noarch.rpm" in pulled.rpms
    assert pulled.rpms["test-1.0-1.noarch.rpm"].arch == "noarch"


def test_default_labels_include_cluster(tmp_path: Path) -> None:
    nested = tmp_path / "pkg.noarch.rpm"
    nested.write_bytes(b"rpm")
    context = PullContext(operation_label="transfer", namespace="ns", build_id="b1", cluster="prod")
    pulled = collect_pulled_artifacts_from_oras_bundle(tmp_path, context)
    assert pulled.rpms["pkg.noarch.rpm"].labels.get("cluster") == "prod"


def test_collect_missing_directory_raises(tmp_path: Path) -> None:
    context = PullContext(operation_label="transfer")
    with pytest.raises(ValueError, match="not found"):
        collect_pulled_artifacts_from_oras_bundle(tmp_path / "missing", context)


def test_collect_empty_bundle_raises(tmp_path: Path) -> None:
    context = PullContext(operation_label="transfer")
    try:
        collect_pulled_artifacts_from_oras_bundle(tmp_path, context)
    except ValueError as exc:
        assert "No RPM files" in str(exc)
    else:
        raise AssertionError("expected ValueError")
