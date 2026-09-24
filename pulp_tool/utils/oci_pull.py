"""Detect and ORAS-pull ``pulp_results.json`` OCI manifest references for ``pull``."""

from __future__ import annotations

from pathlib import Path

from .constants import RESULTS_JSON_FILENAME
from .oras_publish import OrasPublishError, _run_oras


def normalize_oci_artifact_reference(location: str) -> str:
    """Strip Konflux ``oci:`` prefix from a trusted-artifact URI."""
    ref = (location or "").strip()
    if ref.lower().startswith("oci:"):
        return ref[4:].strip()
    return ref


def is_oci_artifact_reference(location: str) -> bool:
    """
    Return True when ``location`` is an OCI manifest ref (``repo@sha256:…``), not HTTP or a local path.

    Bare ``ociStorage`` repository URLs without a digest are not accepted here.
    """
    ref = normalize_oci_artifact_reference(location)
    if not ref or ref.startswith(("http://", "https://")):
        return False
    if "@" not in ref:
        return False
    digest = ref.rsplit("@", 1)[-1]
    return digest.startswith("sha256:")


def pull_pulp_results_json(oci_manifest_ref: str, dest_dir: Path) -> Path:
    """
    ORAS-pull ``pulp_results.json`` from ``oci_manifest_ref`` into ``dest_dir``.

    Returns the path to the pulled JSON file (prefers ``pulp_results.json``).
    """
    ref = normalize_oci_artifact_reference(oci_manifest_ref)
    if not ref:
        raise OrasPublishError("OCI manifest reference is empty")

    dest_dir.mkdir(parents=True, exist_ok=True)
    for existing in dest_dir.iterdir():
        if existing.is_file():
            existing.unlink()

    pull_result = _run_oras(
        ["pull", "--allow-path-traversal", ref, "-o", str(dest_dir)],
        ref,
    )
    if pull_result.returncode != 0:
        raise OrasPublishError(
            f"oras pull failed (exit {pull_result.returncode}): {pull_result.stderr or pull_result.stdout}"
        )

    preferred = dest_dir / RESULTS_JSON_FILENAME
    if preferred.is_file():
        return preferred

    json_files = sorted(dest_dir.glob("*.json"))
    if not json_files:
        raise OrasPublishError(f"No .json file under {dest_dir} after oras pull of {ref}")
    return json_files[0]


__all__ = ["is_oci_artifact_reference", "normalize_oci_artifact_reference", "pull_pulp_results_json"]
