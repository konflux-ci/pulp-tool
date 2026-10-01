"""Load ``pulp_results.json`` from a local path or OCI manifest reference."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..models.pulp_results import PulpResultsDocument
from .oci_pull import is_oci_artifact_reference, pull_pulp_results_json


class ResultsJsonIOError(ValueError):
    """Invalid or unreadable results JSON location."""


def require_digest_pinned_oci_ref(location: str) -> None:
    """Reject OCI refs without ``@sha256:…`` for Tekton-style digest-pinned reads."""
    ref = location.strip()
    if ref.startswith("oci:"):
        ref = ref[4:]
    if "@" not in ref:
        raise ResultsJsonIOError(f"OCI results JSON reference must be digest-pinned (repo@sha256:…), got: {location!r}")
    _repo, digest = ref.rsplit("@", 1)
    if not digest.startswith("sha256:"):
        raise ResultsJsonIOError(f"OCI results JSON reference must use sha256 digest, got: {location!r}")


def resolve_results_json_path(location: str, dest_dir: Path) -> Path:
    """
    Resolve ``location`` to a local ``pulp_results.json`` path.

    ORAS-pulls when ``location`` is an OCI manifest reference.
    """
    loc = location.strip()
    if not loc:
        raise ResultsJsonIOError("results JSON location is empty")
    if is_oci_artifact_reference(loc):
        require_digest_pinned_oci_ref(loc)
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = pull_pulp_results_json(loc, dest_dir)
        logging.info("ORAS-pulled pulp_results.json from %s to %s", loc, path)
        return path
    path = Path(loc).expanduser().resolve()
    if not path.is_file():
        raise ResultsJsonIOError(f"Results JSON file not found: {path}")
    return path


def load_results_document(location: str, *, dest_dir: Path) -> PulpResultsDocument:
    """Load and normalize a results document from path or OCI ref."""
    path = resolve_results_json_path(location, dest_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ResultsJsonIOError(f"Failed to read results JSON {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ResultsJsonIOError(f"Results JSON root must be an object: {path}")
    return PulpResultsDocument.from_raw(raw)


__all__ = [
    "ResultsJsonIOError",
    "require_digest_pinned_oci_ref",
    "resolve_results_json_path",
    "load_results_document",
]
