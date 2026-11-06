"""Tests for e2e run-scoped naming helpers."""

from __future__ import annotations

import sys
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parents[2] / "e2e"
sys.path.insert(0, str(E2E_DIR))

from names import (  # noqa: E402
    BASE_PATH_CREATE_REPOSITORY,
    BASE_PATH_CREATE_REPOSITORY_JSON,
    BUILD_ID_E2E_ERROR_EMPTY,
    BUILD_ID_PULL_GPG_VERIFY,
    BUILD_ID_PULL_SIDE_TAG,
    BUILD_ID_PULL_SIDE_TAG_OCI,
    BUILD_ID_UPLOAD_MINIMAL,
    BUILD_ID_UPLOAD_ORAS,
    BUILD_ID_UPLOAD_TARGET_ARCH,
    e2e_error_upload_repo_names,
    e2e_transfer_destination_repo_prefix,
    file_repos_for_run,
    normalize_oci_storage,
    oci_storage_e2e_enabled,
    pull_side_tag_rpm_repo_key,
    resolve_run_id,
    rpm_repos_for_run,
    scoped_base_path,
    scoped_build_id,
    scoped_oci_storage,
    scoped_repo_name,
    side_tag_e2e_name,
)


def test_e2e_error_upload_repo_names() -> None:
    build = f"{BUILD_ID_E2E_ERROR_EMPTY}-run1"
    names = e2e_error_upload_repo_names(build)
    assert f"{build}/rpms" in names
    assert f"{build}/artifacts" in names


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


def test_scoped_repo_name_scopes_target_arch_build_paths() -> None:
    assert scoped_repo_name(f"{BUILD_ID_UPLOAD_TARGET_ARCH}/aarch64", "run1") == (
        f"{BUILD_ID_UPLOAD_TARGET_ARCH}-run1/aarch64"
    )


def test_rpm_repos_for_run_includes_build_scoped_target_arch_repos() -> None:
    legacy = rpm_repos_for_run(None)
    isolated = rpm_repos_for_run("run1")
    assert f"{BUILD_ID_UPLOAD_TARGET_ARCH}/aarch64" in legacy
    assert f"{BUILD_ID_UPLOAD_TARGET_ARCH}-run1/aarch64" in isolated
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
    assert f"{BUILD_ID_UPLOAD_ORAS}-{run_id}/artifacts" not in files
    domain = "mysuite"
    rpm_dom = rpm_repos_for_run(run_id, None, source_domain=domain)
    gpg_bid = scoped_build_id(BUILD_ID_PULL_GPG_VERIFY, run_id)
    gpg_prefix = e2e_transfer_destination_repo_prefix(source_domain=domain, build_id=gpg_bid)
    assert f"{gpg_prefix}/rpms" in rpm_dom
    side_bid = scoped_build_id(BUILD_ID_PULL_SIDE_TAG, run_id)
    side_prefix = e2e_transfer_destination_repo_prefix(source_domain=domain, build_id=side_bid)
    assert f"{side_prefix}/rpms" not in rpm_dom


def test_normalize_oci_storage_strips_whitespace() -> None:
    assert normalize_oci_storage("  quay.io/example/repo:tag  ") == "quay.io/example/repo:tag"
    assert normalize_oci_storage(None) == ""
    assert normalize_oci_storage("") == ""


def test_side_tag_e2e_name_scoped_with_run_id() -> None:
    assert side_tag_e2e_name(None) == "e2e-test"
    assert side_tag_e2e_name("run1") == "e2e-test-run1"
    assert pull_side_tag_rpm_repo_key("run1") == "e2e-test-run1"


def test_oci_repos_included_when_oci_storage_set() -> None:
    oci = "quay.io/example/repo:tag"
    run_id = "run1"
    domain = "mysuite"
    assert oci_storage_e2e_enabled(oci)
    side_bid = scoped_build_id(BUILD_ID_PULL_SIDE_TAG, run_id)
    side_prefix = e2e_transfer_destination_repo_prefix(source_domain=domain, build_id=side_bid)
    rpm = rpm_repos_for_run(run_id, oci, source_domain=domain)
    files = file_repos_for_run(run_id, oci, source_domain=domain)
    assert f"{BUILD_ID_UPLOAD_ORAS}-{run_id}/rpms" in rpm
    assert f"{BUILD_ID_UPLOAD_ORAS}-{run_id}/artifacts" in files
    assert f"{side_prefix}/rpms" in rpm
    assert f"{side_prefix}/artifacts" in files


def test_transfer_gpg_verify_expected_paths_with_source_domain() -> None:
    run_id = "run1"
    domain = "mysuite"
    bid = scoped_build_id(BUILD_ID_PULL_GPG_VERIFY, run_id)
    prefix = e2e_transfer_destination_repo_prefix(source_domain=domain, build_id=bid)
    rpm = rpm_repos_for_run(run_id, None, source_domain=domain)
    files = file_repos_for_run(run_id, None, source_domain=domain)
    assert f"{prefix}/rpms" in rpm
    assert f"{prefix}/artifacts" in files


def test_scoped_oci_storage_uses_per_build_tag() -> None:
    base = "quay.io/redhat-user-workloads/artifact-storage-tenant/tooling/pulp-e2e-testing"
    oras = scoped_oci_storage(base, BUILD_ID_UPLOAD_ORAS, "abc123")
    side = scoped_oci_storage(base, BUILD_ID_PULL_SIDE_TAG_OCI, "abc123")
    assert oras != side
    assert oras.startswith(f"{base}:e2e-{BUILD_ID_UPLOAD_ORAS}-abc123")
    assert side.startswith(f"{base}:e2e-{BUILD_ID_PULL_SIDE_TAG_OCI}-abc123")
    assert scoped_oci_storage(f"{base}:latest", BUILD_ID_UPLOAD_ORAS, "run1") == (
        f"{base}:e2e-{BUILD_ID_UPLOAD_ORAS}-run1"
    )
    run_scoped_build = f"{BUILD_ID_PULL_SIDE_TAG_OCI}-abc123"
    assert scoped_oci_storage(base, run_scoped_build, "abc123") == f"{base}:e2e-{run_scoped_build}"
