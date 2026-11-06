"""Tests for transfer destination repository base name construction."""

from unittest.mock import patch

import pytest

from pulp_tool.utils.transfer_repository_naming import (
    normalize_transfer_source_domain_segment,
    transfer_destination_repository_base_name,
)


def test_normalize_transfer_source_domain_segment_adds_konflux_prefix() -> None:
    assert normalize_transfer_source_domain_segment("build-pulp") == "konflux-build-pulp"


def test_normalize_transfer_source_domain_segment_idempotent_konflux() -> None:
    assert normalize_transfer_source_domain_segment("konflux-build-pulp") == "konflux-build-pulp"


def test_transfer_destination_repository_base_name() -> None:
    assert (
        transfer_destination_repository_base_name(
            build_id="tenant-1/pipeline-run-abc",
            source_domain="build-pulp",
        )
        == "konflux-build-pulp/pipeline-run-abc"
    )


def test_transfer_destination_repository_base_name_raises_on_empty_build() -> None:
    with pytest.raises(ValueError, match="Invalid build ID"):
        transfer_destination_repository_base_name(build_id="", source_domain="x")


def test_transfer_destination_repository_base_name_raises_when_repo_segment_empty() -> None:
    """``tenant/`` leaves nothing after the first slash (matches strip_namespace_from_build_id)."""
    with pytest.raises(ValueError, match="Empty source repo segment"):
        transfer_destination_repository_base_name(build_id="tenant/", source_domain="build-pulp")


def test_transfer_destination_repository_base_name_raises_when_domain_segment_sanitizes_empty() -> None:
    """If the normalized domain segment is empty after sanitization, raise with context."""
    with (
        patch(
            "pulp_tool.utils.transfer_repository_naming.sanitize_build_id_for_repository",
            side_effect=["repo-seg", ""],
        ),
        pytest.raises(ValueError, match="Invalid transfer repository base name"),
    ):
        transfer_destination_repository_base_name(build_id="ns/bi", source_domain="dom")
