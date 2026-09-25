"""Tests for side-tag name sanitization."""

import pytest

from pulp_tool.utils.validation.side_tag import sanitize_side_tag_name, side_tag_distribution_base_path


def test_sanitize_side_tag_name() -> None:
    assert sanitize_side_tag_name("my-test") == "my-test"


def test_sanitize_side_tag_name_rejects_empty() -> None:
    with pytest.raises(ValueError):
        sanitize_side_tag_name("  ")


def test_side_tag_distribution_base_path() -> None:
    assert side_tag_distribution_base_path("mytest") == "side-tag-mytest"
