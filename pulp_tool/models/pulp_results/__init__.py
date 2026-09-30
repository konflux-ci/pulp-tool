"""Canonical ``pulp_results.json`` model and document operations."""

from .constants import (
    BTS_UPDATE_OPERATION,
    BUILD_SIGN_OPERATION,
    BUILD_UPLOAD_OPERATION,
    PULP_RESULTS_ORAS_MEDIA_TYPE,
    PULP_RESULTS_SCHEMA_VERSION,
    RELEASE_SIGN_OPERATION,
    SIDE_TAG_TRANSFER_OPERATION,
)
from .distributions import aggregate_top_level_distributions, recompute_distributions, retain_distribution_slots
from .document import PulpResultsDocument
from .entries import HrefHistoryEntry, SideTagRpmTransfer
from .lineage import (
    append_href_history,
    merge_origin_pulp_labels,
    merge_signed_by,
    resolve_predecessor_href,
    side_tag_upload_labels,
)
from .normalize import (
    artifact_pulp_labels,
    document_last_updated,
    normalize_document,
    parse_last_updated,
    schema_version,
)

__all__ = [
    "PULP_RESULTS_ORAS_MEDIA_TYPE",
    "BUILD_UPLOAD_OPERATION",
    "BUILD_SIGN_OPERATION",
    "RELEASE_SIGN_OPERATION",
    "BTS_UPDATE_OPERATION",
    "SIDE_TAG_TRANSFER_OPERATION",
    "HrefHistoryEntry",
    "SideTagRpmTransfer",
    "PulpResultsDocument",
    "PULP_RESULTS_SCHEMA_VERSION",
    "artifact_pulp_labels",
    "normalize_document",
    "resolve_predecessor_href",
    "merge_signed_by",
    "merge_origin_pulp_labels",
    "side_tag_upload_labels",
    "recompute_distributions",
    "aggregate_top_level_distributions",
    "retain_distribution_slots",
    "schema_version",
    "document_last_updated",
    "parse_last_updated",
    "append_href_history",
]
