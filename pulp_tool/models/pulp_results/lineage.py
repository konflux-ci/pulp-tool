"""Href lineage and label merge helpers."""

from __future__ import annotations

from typing import Any

from ..artifacts import ArtifactMetadata
from ..href_history import HrefHistoryEntry
from .constants import PULP_RESULTS_SCHEMA_VERSION, SIDE_TAG_TRANSFER_OPERATION
from .normalize import artifact_pulp_labels


def resolve_predecessor_href(artifact: dict[str, Any] | ArtifactMetadata) -> str:
    """Return the immediate predecessor content href for lineage (artifact href or labels)."""
    if isinstance(artifact, ArtifactMetadata):
        href = (artifact.href or "").strip()
        if href:
            return href
        labels = artifact.pulp_labels
        for key in ("source_pulp_href", "pulp_href"):
            value = labels.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    href = (artifact.get("href") or "").strip()
    if href:
        return href
    labels = artifact_pulp_labels(artifact)
    for key in ("source_pulp_href", "pulp_href"):
        value = labels.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def merge_signed_by(existing: str, new: str, *, replace: bool = False) -> str:
    """Merge semicolon-separated signed_by values (default) or replace when ``replace`` is True."""
    new_val = (new or "").strip()
    if replace or not (existing or "").strip():
        return new_val
    if not new_val:
        return (existing or "").strip()
    parts = [p.strip() for p in existing.split(";") if p.strip()]
    if new_val not in parts:
        parts.append(new_val)
    return ";".join(parts)


def merge_origin_pulp_labels(
    labels: dict[str, str],
    *,
    namespace: str | None,
    build_id: str | None,
    cluster: str | None,
) -> dict[str, str]:
    """Set origin_* labels once; never overwrite existing origin_* keys."""
    merged = dict(labels)
    if namespace and not merged.get("origin_namespace"):
        merged["origin_namespace"] = namespace
    if build_id and not merged.get("origin_build_id"):
        merged["origin_build_id"] = build_id
    if cluster and not merged.get("origin_cluster"):
        merged["origin_cluster"] = cluster
    return merged


def side_tag_upload_labels(
    labels: dict[str, str],
    *,
    side_tag: str,
    source_pulp_href: str,
    namespace: str | None,
    build_id: str | None,
    cluster: str | None,
) -> dict[str, str]:
    """Build pulp_labels for content uploaded to a side-tag RPM repository."""
    merged = merge_origin_pulp_labels(labels, namespace=namespace, build_id=build_id, cluster=cluster)
    merged["side_tag"] = side_tag
    if source_pulp_href:
        merged["source_pulp_href"] = source_pulp_href
    return merged


def append_href_history(
    meta: ArtifactMetadata,
    *,
    prior_href: str,
    prior_sha256: str,
    last_updated: str,
    schema_version_value: str = PULP_RESULTS_SCHEMA_VERSION,
    operation: str = SIDE_TAG_TRANSFER_OPERATION,
) -> None:
    """Append a href_history entry when prior_href is set."""
    if not prior_href:
        return
    signed_by = (meta.pulp_labels.get("signed_by") or "").strip()
    entry = HrefHistoryEntry(
        href=prior_href,
        sha256=prior_sha256 or "",
        operation=operation,
        last_updated=last_updated,
        schema_version=schema_version_value,
        signed_by=signed_by,
    )
    meta.href_history = [*meta.href_history, entry]


__all__ = [
    "append_href_history",
    "merge_origin_pulp_labels",
    "merge_signed_by",
    "resolve_predecessor_href",
    "side_tag_upload_labels",
]
