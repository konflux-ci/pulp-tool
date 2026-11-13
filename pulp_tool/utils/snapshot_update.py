"""Update Konflux release snapshot JSON after transfer (ORAS publish / oras cp)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from .oci_pull import normalize_oci_artifact_reference

SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY = "pulpResultsOciManifest"
SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY = "containerImage"


def _digest_from_oci_ref(ref: str) -> str:
    normalized = normalize_oci_artifact_reference(ref.strip())
    if not normalized or "@" not in normalized:
        return ""
    digest = normalized.rsplit("@", 1)[-1].strip()
    if digest and not digest.startswith("sha256:"):
        digest = f"sha256:{digest}"
    return digest


def _atomic_write_snapshot(path: Path, document: dict[str, Any]) -> None:
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


def _load_snapshot_document(snapshot_path: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(snapshot_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Snapshot file not found: {path}")
    try:
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Snapshot file is not valid JSON: {path}") from e
    if not isinstance(document, dict):
        raise ValueError(f"Snapshot root must be a JSON object: {path}")
    return path, document


def update_snapshot_pulp_results_manifest(snapshot_path: str | Path, oci_manifest_ref: str) -> None:
    """
    Record the published ``pulp_results.json`` OCI reference on the release snapshot.

    Release pipelines that use trusted artifacts (``use-trusted-artifact`` / ``create-trusted-artifact``)
    should run ``pulp-tool`` against a workspace snapshot file, then push the workspace with
    ``create-trusted-artifact`` so downstream tasks see the updated digest — same pattern as
    ``upload-src-rpm-sbom-attestation`` updating snapshot paths before ``create-trusted-artifact``.
    """
    ref = oci_manifest_ref.strip()
    if not ref:
        raise ValueError("oci_manifest_ref is empty")

    path, document = _load_snapshot_document(snapshot_path)
    document[SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY] = ref
    _atomic_write_snapshot(path, document)
    logging.info(
        "Updated snapshot %s with %s=%s",
        path,
        SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY,
        ref,
    )


def update_snapshot_component_container_images(
    snapshot_path: str | Path,
    container_image_ref: str,
    *,
    match_source_ref: str | None = None,
) -> int:
    """
    Set ``components[].containerImage`` on matching snapshot components.

    When ``match_source_ref`` is set (digest-pinned), only components whose current
    ``containerImage`` shares the same ``sha256:`` digest are updated — same selective
    update model as ``upload_src_rpm_sbom_attestation`` per component.
    """
    new_ref = normalize_oci_artifact_reference(container_image_ref.strip())
    if not new_ref:
        raise ValueError("container_image_ref is empty")

    path, document = _load_snapshot_document(snapshot_path)
    components = document.get("components")
    if components is None:
        components = []
    if not isinstance(components, list):
        raise ValueError(f"Snapshot field 'components' must be an array: {path}")

    match_digest = _digest_from_oci_ref(match_source_ref or "")
    updated = 0
    for component in components:
        if not isinstance(component, dict):
            raise TypeError("Each snapshot component must be an object")
        current = str(component.get(SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY) or "").strip()
        if not current:
            continue
        if match_digest:
            if _digest_from_oci_ref(current) != match_digest:
                continue
        component[SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY] = new_ref
        updated += 1
        name = str(component.get("name") or "")
        logging.info(
            "Updated snapshot component %r containerImage -> %s",
            name or updated,
            new_ref,
        )

    if updated:
        _atomic_write_snapshot(path, document)
    return updated


__all__ = [
    "SNAPSHOT_COMPONENT_CONTAINER_IMAGE_KEY",
    "SNAPSHOT_PULP_RESULTS_OCI_MANIFEST_KEY",
    "update_snapshot_component_container_images",
    "update_snapshot_pulp_results_manifest",
]
