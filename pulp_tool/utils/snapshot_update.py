"""Update Konflux release snapshot JSON after side-tag ORAS publish."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY = "pulpResultsOciManifest"


def update_snapshot_pulp_results_manifest(snapshot_path: str | Path, oci_manifest_ref: str) -> None:
    """
    Record the published ``pulp_results.json`` OCI reference on the release snapshot.

    Release pipelines that use trusted artifacts (``use-trusted-artifact`` / ``create-trusted-artifact``)
    should run ``pulp-tool`` against a workspace snapshot file, then push the workspace with
    ``create-trusted-artifact`` so downstream tasks see the updated digest — same pattern as
    ``upload-src-rpm-sbom-attestation`` updating snapshot paths before ``create-trusted-artifact``.
    """
    path = Path(snapshot_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Snapshot file not found: {path}")

    ref = oci_manifest_ref.strip()
    if not ref:
        raise ValueError("oci_manifest_ref is empty")

    try:
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Snapshot file is not valid JSON: {path}") from e

    document[SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY] = ref

    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        delete=False,
        suffix=".tmp",
    ) as tmp:
        json.dump(document, tmp, indent=2)
        tmp.write("\n")
        tmp_path = tmp.name
    os.replace(tmp_path, path)
    logging.info(
        "Updated snapshot %s with %s=%s",
        path,
        SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY,
        ref,
    )


__all__ = [
    "SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY",
    "update_snapshot_pulp_results_manifest",
]
