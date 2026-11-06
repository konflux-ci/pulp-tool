"""
Destination repository naming for ``transfer`` (Pulp-to-Pulp promotion).

Build repos under the destination domain as ``konflux-<source-domain>/<source-repo>/{rpms|logs|…}``,
where ``<source-repo>`` is the source build segment (namespace stripped from ``build_id``) and
``<source-domain>`` comes from ``cli.domain`` in the source ``cli.toml`` (always normalized with a
``konflux-`` prefix on the first path segment).
"""

from __future__ import annotations

import logging

from .validation import sanitize_build_id_for_repository, strip_namespace_from_build_id


def normalize_transfer_source_domain_segment(domain: str) -> str:
    """
    Return a Pulp-path-safe domain segment with a ``konflux-`` prefix.

    Config may store ``my-domain`` or ``konflux-my-domain``; the result is always prefixed and
    sanitized for repository base_path use.
    """
    raw = (domain or "").strip()
    if not raw:
        logging.warning(
            "transfer: source cli.domain is missing; using 'konflux-unknown' in destination repository names",
        )
        raw = "unknown"
    if not raw.lower().startswith("konflux-"):
        raw = f"konflux-{raw}"
    return sanitize_build_id_for_repository(raw)


def transfer_destination_repository_base_name(*, build_id: str, source_domain: str) -> str:
    """
    Base path prefix for transfer destination repos: ``konflux-<domain>/<source-repo>``.

    ``source_repo`` is :func:`strip_namespace_from_build_id` of ``build_id``, then sanitized per segment.
    """
    if not build_id or not isinstance(build_id, str) or not build_id.strip():
        raise ValueError(f"Invalid build ID for transfer repository naming: {build_id!r}")

    source_repo = strip_namespace_from_build_id(build_id)
    if not source_repo or not source_repo.strip():
        raise ValueError(f"Empty source repo segment after stripping namespace from build_id: {build_id!r}")

    source_repo_seg = sanitize_build_id_for_repository(source_repo)
    domain_seg = normalize_transfer_source_domain_segment(source_domain)
    if not domain_seg or not source_repo_seg:
        raise ValueError(
            f"Invalid transfer repository base name from build_id={build_id!r}, source_domain={source_domain!r}",
        )
    return f"{domain_seg}/{source_repo_seg}"


__all__ = [
    "normalize_transfer_source_domain_segment",
    "transfer_destination_repository_base_name",
]
