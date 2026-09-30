"""Per-artifact and top-level distribution slot helpers."""

from __future__ import annotations

from typing import Any

from ..artifacts import ArtifactMetadata


def _artifact_distributions_dict(artifact: dict[str, Any]) -> dict[str, str]:
    raw = artifact.get("distributions")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v}


def recompute_distributions(
    artifact: dict[str, Any] | ArtifactMetadata,
    verified_slots: set[str],
    *,
    slot_updates: dict[str, str] | None = None,
) -> dict[str, str]:
    """Keep per-artifact distribution slots in ``verified_slots``; prune stale slots."""
    if isinstance(artifact, ArtifactMetadata):
        base = dict(artifact.distributions)
    else:
        base = _artifact_distributions_dict(artifact)
    merged = {k: v for k, v in base.items() if k in verified_slots}
    if slot_updates:
        for slot, url in slot_updates.items():
            if slot in verified_slots and url:
                merged[slot] = url
    return merged


def aggregate_top_level_distributions(document: dict[str, Any]) -> dict[str, str]:
    """Optional aggregate ``distributions`` from per-artifact slots (for pull backward compat)."""
    aggregate: dict[str, str] = {}
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        return aggregate
    for row in artifacts.values():
        if not isinstance(row, dict):
            continue
        for slot, url in _artifact_distributions_dict(row).items():
            if url and slot not in aggregate:
                aggregate[slot] = url
    existing = document.get("distributions")
    if isinstance(existing, dict):
        for slot, url in existing.items():
            if url and slot not in aggregate:
                aggregate[str(slot)] = str(url)
    return aggregate


def aggregate_top_level_from_artifacts(
    artifacts: dict[str, ArtifactMetadata],
    existing_top: dict[str, str],
) -> dict[str, str]:
    aggregate = dict(existing_top)
    for meta in artifacts.values():
        for slot, url in meta.distributions.items():
            if url and slot not in aggregate:
                aggregate[slot] = url
    return aggregate


def retain_distribution_slots(
    meta: ArtifactMetadata,
    prior_href: str,
    merged_distributions: dict[str, str],
) -> dict[str, str]:
    """Keep per-artifact distribution slots when href is unchanged from ``prior_href``."""
    current_href = (meta.href or "").strip() or prior_href
    if prior_href and current_href != prior_href:
        return merged_distributions
    for slot, url in meta.distributions.items():
        if slot not in merged_distributions and url:
            merged_distributions[slot] = url
    return merged_distributions


__all__ = [
    "aggregate_top_level_distributions",
    "aggregate_top_level_from_artifacts",
    "recompute_distributions",
    "retain_distribution_slots",
]
