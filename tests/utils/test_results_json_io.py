"""Tests for results JSON path resolution."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pulp_tool.utils.results_json_io import (
    ResultsJsonIOError,
    load_results_document,
    require_digest_pinned_oci_ref,
    resolve_results_json_path,
)


def test_require_digest_pinned_rejects_bare_repo() -> None:
    with pytest.raises(ResultsJsonIOError, match="digest-pinned"):
        require_digest_pinned_oci_ref("quay.io/ns/repo:latest")


def test_require_digest_pinned_strips_oci_prefix() -> None:
    with pytest.raises(ResultsJsonIOError, match="digest-pinned"):
        require_digest_pinned_oci_ref("oci:quay.io/ns/repo:tag")


def test_require_digest_pinned_rejects_non_sha256_digest() -> None:
    with pytest.raises(ResultsJsonIOError, match="sha256 digest"):
        require_digest_pinned_oci_ref("quay.io/ns/repo@deadbeef")


def test_resolve_rejects_empty_location(tmp_path: Path) -> None:
    with pytest.raises(ResultsJsonIOError, match="empty"):
        resolve_results_json_path("   ", tmp_path)


def test_resolve_local_path(tmp_path: Path) -> None:
    f = tmp_path / "pulp_results.json"
    f.write_text('{"version": 1}', encoding="utf-8")
    assert resolve_results_json_path(str(f), tmp_path) == f.resolve()


def test_load_results_document_local(tmp_path: Path) -> None:
    f = tmp_path / "pulp_results.json"
    f.write_text('{"version": 2, "artifacts": {}}', encoding="utf-8")
    doc = load_results_document(str(f), dest_dir=tmp_path / "oci")
    assert doc.version == "2"


def test_load_results_document_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "pulp_results.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ResultsJsonIOError, match="Failed to read"):
        load_results_document(str(bad), dest_dir=tmp_path)


def test_load_results_document_non_object_root(tmp_path: Path) -> None:
    bad = tmp_path / "pulp_results.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ResultsJsonIOError, match="must be an object"):
        load_results_document(str(bad), dest_dir=tmp_path)


def test_load_results_document_oci_does_not_embed_manifest(tmp_path: Path) -> None:
    pulled = tmp_path / "pulp_results.json"
    pulled.write_text('{"version": 2, "artifacts": {}}', encoding="utf-8")
    ref = "quay.io/ns/repo@sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    with patch(
        "pulp_tool.utils.results_json_io.pull_pulp_results_json",
        return_value=pulled,
    ):
        doc = load_results_document(ref, dest_dir=tmp_path / "oci")
    assert "oci_manifest" not in doc._mutable_dict()
    assert "oci_manifest_history" not in doc._mutable_dict()
    assert doc.version == "2"


def test_resolve_oci_pulls(tmp_path: Path) -> None:
    pulled = tmp_path / "pulled.json"
    pulled.write_text("{}", encoding="utf-8")
    with patch(
        "pulp_tool.utils.results_json_io.pull_pulp_results_json",
        return_value=pulled,
    ):
        out = resolve_results_json_path("quay.io/ns/r@sha256:abc", tmp_path)
    assert out == pulled
