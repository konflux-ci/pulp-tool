"""Tests for side-tag name sanitization."""

import pytest
from pydantic import ValidationError

from pulp_tool.models.pulp_results import SideTagRpmTransfer
from pulp_tool.utils.validation.side_tag import (
    is_side_tag_rpm_artifact_key,
    sanitize_side_tag_name,
    side_tag_distribution_base_path,
)


def test_sanitize_side_tag_name() -> None:
    assert sanitize_side_tag_name("my-test") == "my-test"


def test_sanitize_side_tag_name_rejects_empty() -> None:
    with pytest.raises(ValueError):
        sanitize_side_tag_name("  ")


def test_side_tag_distribution_base_path() -> None:
    assert side_tag_distribution_base_path("mytest") == "mytest"


def test_is_side_tag_rpm_artifact_key() -> None:
    assert is_side_tag_rpm_artifact_key("pkg-1.0-1.noarch.rpm") is True
    assert is_side_tag_rpm_artifact_key("sbom.json") is False
    assert is_side_tag_rpm_artifact_key("") is False


def test_side_tag_rpm_transfer_requires_rpm_artifact_key() -> None:
    SideTagRpmTransfer(
        artifact_key="x.rpm",
        pulp_href="/h",
        sha256="a",
        distribution_url="https://ex/",
    )
    with pytest.raises(ValidationError):
        SideTagRpmTransfer(
            artifact_key="sbom.json",
            pulp_href="/h",
            sha256="a",
            distribution_url="https://ex/",
        )
