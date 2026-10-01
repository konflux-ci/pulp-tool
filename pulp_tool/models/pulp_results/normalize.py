"""Normalize raw ``pulp_results.json`` dicts at the I/O boundary."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from ..href_history import HrefHistoryEntry
from .constants import PULP_RESULTS_SCHEMA_VERSION


def artifact_pulp_labels(artifact: dict[str, Any]) -> dict[str, str]:
    """Return ``pulp_labels`` from an artifact row."""
    raw = artifact.get("pulp_labels")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v is not None}
    return {}


def coerce_schema_version(raw: Any) -> str:
    if raw is None:
        return PULP_RESULTS_SCHEMA_VERSION
    text = str(raw).strip()
    if not text:
        return PULP_RESULTS_SCHEMA_VERSION
    return text


def parse_last_updated_value(raw: Any) -> date | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    fragment = raw.strip()[:10]
    try:
        return date.fromisoformat(fragment)
    except ValueError:
        return None


def parse_last_updated(raw: Any) -> date | None:
    """Parse ``last_updated`` or ISO datetime prefix to ``date``."""
    return parse_last_updated_value(raw)


def document_last_updated_iso(document: dict[str, Any]) -> str:
    raw = document.get("last_updated")
    if isinstance(raw, str) and raw.strip():
        parsed = parse_last_updated_value(raw)
        if parsed is not None:
            return parsed.isoformat()
    return date.today().isoformat()


def optional_str_field(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _normalize_href_history_entry(entry: dict[str, Any]) -> None:
    entry.pop("revision", None)
    if "schema_version" in entry:
        entry["schema_version"] = coerce_schema_version(entry.get("schema_version"))
    elif "schema_version" not in entry:
        entry["schema_version"] = PULP_RESULTS_SCHEMA_VERSION


def normalize_href_history_rows(rows: list[Any]) -> list[HrefHistoryEntry]:
    out: list[HrefHistoryEntry] = []
    for entry in rows:
        if isinstance(entry, HrefHistoryEntry):
            out.append(entry)
            continue
        if isinstance(entry, dict):
            d = dict(entry)
            _normalize_href_history_entry(d)
            out.append(HrefHistoryEntry.model_validate(d))
    return out


def normalize_document(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Deep-copy and normalize to canonical in-memory shape (``pulp_labels`` only).
    """
    document = copy.deepcopy(raw)
    if document.get("version") is None:
        document["version"] = PULP_RESULTS_SCHEMA_VERSION
    document.pop("revision", None)
    if document.get("last_updated") is None:
        document["last_updated"] = date.today().isoformat()

    document.pop("oci_manifest", None)
    document.pop("oci_manifest_history", None)
    document.pop("labels", None)
    document["version"] = coerce_schema_version(document.get("version"))
    document["last_updated"] = document_last_updated_iso(document)

    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        document["artifacts"] = {}
        artifacts = document["artifacts"]

    for _key, row in list(artifacts.items()):
        if not isinstance(row, dict):
            continue
        labels = artifact_pulp_labels(row)
        if labels:
            row["pulp_labels"] = labels
        row.pop("labels", None)
        if not isinstance(row.get("distributions"), dict):
            row.pop("distributions", None)
        if not isinstance(row.get("href_history"), list):
            row["href_history"] = []
        else:
            row["href_history"] = [e.model_dump() for e in normalize_href_history_rows(row["href_history"])]

    if document.get("distributions") is not None and not isinstance(document.get("distributions"), dict):
        document["distributions"] = {}

    return document


def schema_version(document: dict[str, Any]) -> str:
    """Return JSON schema ``version`` semver (default ``PULP_RESULTS_SCHEMA_VERSION``)."""
    return coerce_schema_version(document.get("version"))


def document_last_updated(document: dict[str, Any]) -> str:
    """Return document ``last_updated`` (ISO date), defaulting to today when unset."""
    return document_last_updated_iso(document)


__all__ = [
    "artifact_pulp_labels",
    "coerce_schema_version",
    "document_last_updated",
    "document_last_updated_iso",
    "normalize_document",
    "normalize_href_history_rows",
    "optional_str_field",
    "parse_last_updated",
    "parse_last_updated_value",
    "schema_version",
]
