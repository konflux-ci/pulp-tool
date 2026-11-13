"""Tests for Pulp container-push OCI provisioning."""

from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.utils.pulp_container_oci import (
    PulpContainerOciError,
    oras_copy_target_for_base_path,
    provision_pulp_oras_cp_target,
    pulp_container_oci_object_name,
)


def test_pulp_container_oci_object_name_joins_namespace_and_build_id() -> None:
    assert pulp_container_oci_object_name("my-ns", "test/build:1") == "my-ns/oci/test-build-1"


def test_container_distribution_api_name_flattens_registry_path() -> None:
    from pulp_tool.utils.pulp_container_oci import _container_distribution_api_name

    assert _container_distribution_api_name("my-ns/oci/test-build-1") == "my-ns__oci__test-build-1"


def test_pulp_container_oci_object_name_requires_build_id() -> None:
    with pytest.raises(PulpContainerOciError, match="build_id"):
        pulp_container_oci_object_name("ns", "")


def test_oras_copy_target_for_base_path() -> None:
    target = oras_copy_target_for_base_path(
        {"base_url": "https://packages.example.com", "api_root": "/api"},
        "ns/oci/bid",
    )
    assert target == "packages.example.com/ns/oci/bid:latest"


def test_ensure_creates_distribution_when_missing() -> None:
    client = MagicMock()
    client.config = {"base_url": "https://example.com"}
    client._create_distribution.return_value = MagicMock(json=lambda: {"pulp_href": "/dist/1/"})
    distro_after = {"pulp_href": "/dist/", "base_path": "tenant/oci/build-1"}
    with patch(
        "pulp_tool.utils.pulp_container_oci._get_container_resource",
        side_effect=[None, distro_after],
    ):
        from pulp_tool.utils.pulp_container_oci import ensure_container_push_oci_storage

        base_path, target = ensure_container_push_oci_storage(client, "tenant/oci/build-1")
    assert base_path == "tenant/oci/build-1"
    assert target.startswith("example.com/")
    client._create_repository.assert_not_called()
    client._create_distribution.assert_called_once()
    client.invalidate_get_cache.assert_called()


def test_provision_pulp_oras_cp_target_uses_existing_distribution() -> None:
    client = MagicMock()
    client.config = {"base_url": "https://example.com", "container_registry": "registry.example.com"}
    existing = {"pulp_href": "/dist/1/", "base_path": "tenant/oci/build-1"}
    with patch(
        "pulp_tool.utils.pulp_container_oci._get_container_resource",
        return_value=existing,
    ):
        target = provision_pulp_oras_cp_target(client, "tenant", "build-1")
    assert target == "registry.example.com/tenant/oci/build-1:latest"
    client._create_repository.assert_not_called()
    client._create_distribution.assert_not_called()
