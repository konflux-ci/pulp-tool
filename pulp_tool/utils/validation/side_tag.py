"""Side-tag name validation for Pulp repository and distribution naming."""

from .build_id import sanitize_build_id_for_repository


def is_side_tag_rpm_artifact_key(key: str) -> bool:
    """True when ``key`` names an RPM in ``pulp_results.json`` (used for side-tag promotion only)."""
    stripped = (key or "").strip()
    return bool(stripped) and stripped.lower().endswith(".rpm")


def sanitize_side_tag_name(side_tag: str) -> str:
    """
    Sanitize a side-tag name for Pulp repo/distribution identifiers.

    Uses the same character rules as build IDs for repository naming.
    """
    if not side_tag or not isinstance(side_tag, str) or not side_tag.strip():
        raise ValueError("side-tag name must be a non-empty string")
    return sanitize_build_id_for_repository(side_tag.strip())


def side_tag_distribution_base_path(side_tag: str) -> str:
    """
    Distribution base_path for a side-tag RPM repo: the sanitized tag only.

    Pulp-content URLs look like ``…/pulp-content/<domain>/<sanitized-tag>/…`` with no extra
    prefix (side-tag pools are RPM-only and shared across source builds).
    """
    return sanitize_side_tag_name(side_tag)


__all__ = ["is_side_tag_rpm_artifact_key", "sanitize_side_tag_name", "side_tag_distribution_base_path"]
