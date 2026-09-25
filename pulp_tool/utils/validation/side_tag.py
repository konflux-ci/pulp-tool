"""Side-tag name validation for Pulp repository and distribution naming."""

from .build_id import sanitize_build_id_for_repository


def sanitize_side_tag_name(side_tag: str) -> str:
    """
    Sanitize a side-tag name for Pulp repo/distribution identifiers.

    Uses the same character rules as build IDs for repository naming.
    """
    if not side_tag or not isinstance(side_tag, str) or not side_tag.strip():
        raise ValueError("side-tag name must be a non-empty string")
    return sanitize_build_id_for_repository(side_tag.strip())


def side_tag_distribution_base_path(side_tag: str) -> str:
    """Distribution base_path segment for a side-tag RPM repo (e.g. side-tag-mytest)."""
    return f"side-tag-{sanitize_side_tag_name(side_tag)}"


__all__ = ["sanitize_side_tag_name", "side_tag_distribution_base_path"]
