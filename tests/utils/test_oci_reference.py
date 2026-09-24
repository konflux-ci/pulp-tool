"""Tests for Konflux ociStorage reference normalization."""

from pulp_tool.utils.oci_reference import oci_storage_oras_target, oci_storage_repository_name


def test_repository_name_strips_tag() -> None:
    assert oci_storage_repository_name("quay.io/ns/repo:tag") == "quay.io/ns/repo"


def test_repository_name_strips_digest() -> None:
    assert oci_storage_repository_name("quay.io/ns/repo@sha256:abc") == "quay.io/ns/repo"


def test_repository_name_bare_konflux_storage() -> None:
    storage = "quay.io/redhat-user-workloads/artifact-storage-tenant/tooling/pulp-e2e-testing"
    assert oci_storage_repository_name(storage) == storage


def test_oras_target_appends_latest_for_bare_repo() -> None:
    storage = "quay.io/redhat-user-workloads/artifact-storage-tenant/tooling/pulp-e2e-testing"
    assert oci_storage_oras_target(storage) == f"{storage}:latest"


def test_oras_target_preserves_explicit_tag() -> None:
    assert oci_storage_oras_target("quay.io/ns/repo:tag") == "quay.io/ns/repo:tag"


def test_oras_target_preserves_digest() -> None:
    ref = "quay.io/ns/repo@sha256:abc"
    assert oci_storage_oras_target(ref) == ref


def test_repository_name_empty() -> None:
    assert oci_storage_repository_name("") == ""
    assert oci_storage_repository_name("   ") == ""


def test_repository_name_without_slash() -> None:
    assert oci_storage_repository_name("myrepo") == "myrepo"


def test_oras_target_empty() -> None:
    assert oci_storage_oras_target("") == ""


def test_oras_target_single_component_repo() -> None:
    assert oci_storage_oras_target("myrepo") == "myrepo:latest"
