"""Tests for e2e run-scoped naming helpers."""

from __future__ import annotations

import sys
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parents[2] / "e2e"
sys.path.insert(0, str(E2E_DIR))

from names import (  # noqa: E402
    BASE_PATH_CREATE_REPOSITORY,
    BASE_PATH_CREATE_REPOSITORY_JSON,
    BUILD_ID_PULL_SIDE_TAG,
    BUILD_ID_UPLOAD_MINIMAL,
    BUILD_ID_UPLOAD_ORAS,
    BUILD_ID_UPLOAD_TARGET_ARCH,
    file_repos_for_run,
    normalize_oci_storage,
    oci_storage_e2e_enabled,
    pull_side_tag_rpm_repo_key,
    resolve_run_id,
    rpm_repos_for_run,
    scoped_base_path,
    scoped_build_id,
    scoped_repo_name,
    side_tag_e2e_name,
)


def test_resolve_run_id_sanitizes() -> None:
    assert resolve_run_id("abc/123") == "abc-123"


def test_scoped_build_id_without_run_id() -> None:
    assert scoped_build_id(BUILD_ID_UPLOAD_MINIMAL, None) == BUILD_ID_UPLOAD_MINIMAL


def test_scoped_build_id_with_run_id() -> None:
    assert scoped_build_id(BUILD_ID_UPLOAD_MINIMAL, "run1") == f"{BUILD_ID_UPLOAD_MINIMAL}-run1"


def test_scoped_base_path_without_run_id() -> None:
    assert scoped_base_path(BASE_PATH_CREATE_REPOSITORY, None) == BASE_PATH_CREATE_REPOSITORY


def test_scoped_base_path_with_run_id() -> None:
    assert scoped_base_path(BASE_PATH_CREATE_REPOSITORY_JSON, "run1") == f"{BASE_PATH_CREATE_REPOSITORY_JSON}-run1"


def test_scoped_repo_name_qualifies_build_scoped_repo() -> None:
    assert scoped_repo_name(f"{BUILD_ID_UPLOAD_MINIMAL}/rpms", "run1") == f"{BUILD_ID_UPLOAD_MINIMAL}-run1/rpms"


def test_scoped_repo_name_leaves_global_arch_repos_unsuffixed() -> None:
    assert scoped_repo_name("aarch64", "run1") == "aarch64"


def test_rpm_repos_for_run_keeps_global_arch_repos_when_isolated() -> None:
    legacy = rpm_repos_for_run(None)
    isolated = rpm_repos_for_run("run1")
    assert "aarch64" in legacy
    assert "aarch64" in isolated
    assert f"{BUILD_ID_UPLOAD_MINIMAL}-run1/rpms" in isolated


def test_file_repos_for_run_scopes_target_arch_artifacts_when_isolated() -> None:
    isolated = file_repos_for_run("run1")
    assert f"{BUILD_ID_UPLOAD_TARGET_ARCH}-run1/artifacts" in isolated
    assert f"{BUILD_ID_UPLOAD_MINIMAL}-run1/artifacts" in isolated


def test_oci_repos_omitted_without_oci_storage() -> None:
    run_id = "run1"
    rpm = rpm_repos_for_run(run_id, None)
    files = file_repos_for_run(run_id, None)
    assert not oci_storage_e2e_enabled(None)
    assert f"{BUILD_ID_UPLOAD_ORAS}-{run_id}/rpms" not in rpm
    assert f"{BUILD_ID_PULL_SIDE_TAG}-{run_id}/rpms" not in rpm
    assert f"{BUILD_ID_UPLOAD_ORAS}-{run_id}/artifacts" not in files
    assert f"{BUILD_ID_PULL_SIDE_TAG}-{run_id}/artifacts" not in files


def test_normalize_oci_storage_strips_whitespace() -> None:
    assert normalize_oci_storage("  quay.io/example/repo:tag  ") == "quay.io/example/repo:tag"
    assert normalize_oci_storage(None) == ""
    assert normalize_oci_storage("") == ""


def test_side_tag_e2e_name_scoped_with_run_id() -> None:
    assert side_tag_e2e_name(None) == "e2e-test"
    assert side_tag_e2e_name("run1") == "e2e-test-run1"
    assert pull_side_tag_rpm_repo_key("run1") == f"{BUILD_ID_PULL_SIDE_TAG}-run1/side-tag-e2e-test-run1"


def test_oci_repos_included_when_oci_storage_set() -> None:
    oci = "quay.io/example/repo:tag"
    run_id = "run1"
    assert oci_storage_e2e_enabled(oci)
    assert f"{BUILD_ID_UPLOAD_ORAS}-{run_id}/rpms" in rpm_repos_for_run(run_id, oci)
    assert f"{BUILD_ID_UPLOAD_ORAS}-{run_id}/artifacts" in file_repos_for_run(run_id, oci)
