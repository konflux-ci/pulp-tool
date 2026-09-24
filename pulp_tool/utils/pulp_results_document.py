"""
Versioned ``pulp_results.json`` document helpers (Path 4 / side-tag transfer).

Pure functions for merging lineage fields: version, href_history, oci_manifest_history,
per-artifact distributions, and origin_* pulp_labels.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, ConfigDict

PULP_RESULTS_ORAS_MEDIA_TYPE = "application/vnd.pulp.results.v0"
SIDE_TAG_TRANSFER_OPERATION = "transfer"


class HrefHistoryEntry(BaseModel):
    """One prior Pulp content href for an artifact."""

    model_config = ConfigDict(extra="ignore")

    href: str
    sha256: str = ""
    operation: str = SIDE_TAG_TRANSFER_OPERATION
    document_version: int = 1
    signed_by: str = ""


class OciManifestHistoryEntry(BaseModel):
    """One prior OCI manifest ref for the results document."""

    model_config = ConfigDict(extra="ignore")

    ref: str
    digest: str = ""
    document_version: int = 1
    operation: str = SIDE_TAG_TRANSFER_OPERATION


class SideTagRpmTransfer(BaseModel):
    """Upload outcome for one RPM promoted to a side-tag repository."""

    model_config = ConfigDict(extra="ignore")

    artifact_key: str
    pulp_href: str
    sha256: str
    distribution_url: str


def resolve_predecessor_href(artifact: dict[str, Any]) -> str:
    """Return the immediate predecessor content href for lineage (artifact href or labels)."""
    href = (artifact.get("href") or "").strip()
    if href:
        return href
    labels = artifact.get("labels") or {}
    if not isinstance(labels, dict):
        return ""
    for key in ("source_pulp_href", "pulp_href"):
        value = labels.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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


def _artifact_distributions_dict(artifact: dict[str, Any]) -> dict[str, str]:
    raw = artifact.get("distributions")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v}


def _retain_distribution_slots(
    artifact: dict[str, Any],
    prior_href: str,
    merged_distributions: dict[str, str],
) -> dict[str, str]:
    """
    Keep per-artifact distribution slots that still point at the same content href.

    Slots are retained when the artifact href is unchanged from ``prior_href``.
    """
    current_href = (artifact.get("href") or "").strip() or prior_href
    if prior_href and current_href != prior_href:
        return merged_distributions
    for slot, url in _artifact_distributions_dict(artifact).items():
        if slot not in merged_distributions and url:
            merged_distributions[slot] = url
    return merged_distributions


def bump_document_version(document: dict[str, Any]) -> int:
    """Increment top-level version (default 1 when absent) and return the new value."""
    current = document.get("version")
    try:
        base = int(current) if current is not None else 1
    except (TypeError, ValueError):
        base = 1
    new_version = base + 1
    document["version"] = new_version
    return new_version


def append_href_history(
    artifact: dict[str, Any],
    *,
    prior_href: str,
    prior_sha256: str,
    document_version: int,
    operation: str = SIDE_TAG_TRANSFER_OPERATION,
) -> None:
    """Append a href_history entry when prior_href is set."""
    if not prior_href:
        return
    labels = artifact.get("labels") or {}
    signed_by = ""
    if isinstance(labels, dict):
        signed_by = (labels.get("signed_by") or "").strip()
    entry = HrefHistoryEntry(
        href=prior_href,
        sha256=prior_sha256 or "",
        operation=operation,
        document_version=document_version,
        signed_by=signed_by,
    )
    history = artifact.get("href_history")
    if not isinstance(history, list):
        history = []
    history.append(entry.model_dump())
    artifact["href_history"] = history


def append_oci_manifest_history(document: dict[str, Any], *, operation: str = SIDE_TAG_TRANSFER_OPERATION) -> None:
    """Move current oci_manifest into oci_manifest_history before replacing it."""
    current = (document.get("oci_manifest") or "").strip()
    if not current:
        return
    ref, digest = current, ""
    if "@" in current:
        ref, digest = current.rsplit("@", 1)
    try:
        doc_version = int(document.get("version") or 1)
    except (TypeError, ValueError):
        doc_version = 1
    entry = OciManifestHistoryEntry(ref=ref, digest=digest, document_version=doc_version, operation=operation)
    history = document.get("oci_manifest_history")
    if not isinstance(history, list):
        history = []
    history.append(entry.model_dump())
    document["oci_manifest_history"] = history
    document.pop("oci_manifest", None)


def set_oci_manifest(document: dict[str, Any], image_ref: str, digest: str) -> None:
    """Set oci_manifest to ref@digest after ORAS push."""
    digest_value = digest if digest.startswith("sha256:") else f"sha256:{digest}" if digest else ""
    if digest_value:
        document["oci_manifest"] = f"{image_ref}@{digest_value}"
    else:
        document["oci_manifest"] = image_ref


def apply_side_tag_transfer_to_document(
    source_document: dict[str, Any],
    transfers: list[SideTagRpmTransfer],
    *,
    side_tag: str,
    top_level_side_tag_distribution_url: str,
) -> dict[str, Any]:
    """
    Merge side-tag RPM transfer outcomes into a copy of the source pulp_results document.

    Mainline top-level distribution slots are preserved. Per-artifact RPM rows get updated
    href/url/sha256, href_history, and a distributions slot keyed by side_tag name.
    """
    document = copy.deepcopy(source_document)
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
        document["artifacts"] = artifacts

    prior_version = document.get("version")
    try:
        old_version = int(prior_version) if prior_version is not None else 1
    except (TypeError, ValueError):
        old_version = 1

    bump_document_version(document)

    top_distributions = document.get("distributions")
    if not isinstance(top_distributions, dict):
        top_distributions = {}
    top_distributions = {str(k): str(v) for k, v in top_distributions.items() if v}
    if top_level_side_tag_distribution_url:
        top_distributions[side_tag] = top_level_side_tag_distribution_url.rstrip("/") + "/"
    document["distributions"] = top_distributions

    for transfer in transfers:
        key = transfer.artifact_key
        existing = artifacts.get(key)
        if not isinstance(existing, dict):
            existing = {"labels": {}}
        prior_href = resolve_predecessor_href(existing)
        prior_sha256 = (existing.get("sha256") or "").strip()

        append_href_history(
            existing,
            prior_href=prior_href,
            prior_sha256=prior_sha256,
            document_version=old_version,
        )

        existing["href"] = transfer.pulp_href
        existing["sha256"] = transfer.sha256
        existing["url"] = transfer.distribution_url

        per_dist = _artifact_distributions_dict(existing)
        per_dist[side_tag] = transfer.distribution_url
        per_dist = _retain_distribution_slots(existing, prior_href, per_dist)
        existing["distributions"] = per_dist

        artifacts[key] = existing

    return document


def document_from_artifact_json(artifact_json: Any) -> dict[str, Any]:
    """Serialize ArtifactJsonResponse (or dict) to a plain document dict for merging."""
    if hasattr(artifact_json, "model_dump"):
        return artifact_json.model_dump(mode="json", exclude_none=True)
    if isinstance(artifact_json, dict):
        return copy.deepcopy(artifact_json)
    raise TypeError(f"Unsupported artifact_json type: {type(artifact_json)}")


__all__ = [
    "PULP_RESULTS_ORAS_MEDIA_TYPE",
    "SIDE_TAG_TRANSFER_OPERATION",
    "HrefHistoryEntry",
    "OciManifestHistoryEntry",
    "SideTagRpmTransfer",
    "resolve_predecessor_href",
    "merge_origin_pulp_labels",
    "side_tag_upload_labels",
    "bump_document_version",
    "append_href_history",
    "append_oci_manifest_history",
    "set_oci_manifest",
    "apply_side_tag_transfer_to_document",
    "document_from_artifact_json",
]
