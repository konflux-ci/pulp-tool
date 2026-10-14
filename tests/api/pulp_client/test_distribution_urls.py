"""Tests for RPM distribution URL helpers."""

from pulp_tool.api.pulp_client.distribution_urls import (
    build_rpm_distribution_url,
    rpm_distribution_base_url_from_labels,
)


def test_rpm_distribution_base_url_per_arch() -> None:
    url = rpm_distribution_base_url_from_labels(
        base_url="https://pulp.example.com",
        namespace="ns",
        labels={"arch": "x86_64"},
        target_arch_repo_build_scoped=False,
    )
    assert url == "https://pulp.example.com/api/pulp-content/ns/x86_64/"


def test_build_rpm_distribution_url_aggregate() -> None:
    url = build_rpm_distribution_url(
        base_url="https://pulp.example.com",
        namespace="ns",
        relative_path="pkg.rpm",
        distribution_urls={"rpms": "https://pulp.example.com/api/pulp-content/ns/build/rpms/"},
        labels={"arch": "x86_64"},
        target_arch_repo=False,
    )
    assert url.endswith("/Packages/p/pkg.rpm")
