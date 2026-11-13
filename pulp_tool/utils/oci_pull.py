"""Detect and ORAS-pull ``pulp_results.json`` OCI manifest references for ``pull``."""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import date
from pathlib import Path

from pulp_tool.models.oci_transfer import OciTransferResolution
from pulp_tool.models.pulp_results import PULP_RESULTS_ORAS_MEDIA_TYPE, parse_last_updated

from .constants import RESULTS_JSON_FILENAME
from .oras_publish import OrasPublishError, _run_oras

logger = logging.getLogger(__name__)


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


def _ensure_extracted_files_under_dest(dest_dir: Path) -> None:
    """Reject ORAS layers that write outside ``dest_dir`` (zip-slip style)."""
    root = dest_dir.resolve()
    for path in dest_dir.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise OrasPublishError(f"ORAS pull wrote file outside destination directory: {resolved}")


def _extract_referrer_digests_from_discover_payload(data: object) -> list[str]:
    """Return ``sha256:…`` digests from ``oras discover --format json`` output."""
    items: list[object] = []
    if isinstance(data, list):
        items = list(data)
    elif isinstance(data, dict):
        for key in ("manifests", "referrers", "descriptors"):
            raw = data.get(key)
            if isinstance(raw, list):
                items.extend(raw)
    digests: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_digest = item.get("digest")
        if not isinstance(raw_digest, str) or not raw_digest.strip():
            ref_val = item.get("reference")
            if isinstance(ref_val, str) and "@" in ref_val:
                raw_digest = ref_val.rsplit("@", 1)[-1]
        if not isinstance(raw_digest, str):
            continue
        digest = raw_digest.strip()
        if not digest.startswith("sha256:"):
            digest = f"sha256:{digest}"
        if digest not in seen:
            seen.add(digest)
            digests.append(digest)
    return digests


def discover_pulp_results_referrer_refs(subject_ref: str) -> list[str]:
    """
    List digest-pinned refs for ``pulp_results`` referrers attached to ``subject_ref``.

    Returns an empty list when discover fails or no matching referrers exist.
    """
    ref = normalize_oci_artifact_reference(subject_ref)
    if not ref or "@" not in ref:
        return []
    repo = ref.rsplit("@", 1)[0]
    discover = _run_oras(
        [
            "discover",
            "--artifact-type",
            PULP_RESULTS_ORAS_MEDIA_TYPE,
            "--format",
            "json",
            ref,
        ],
        ref,
    )
    if discover.returncode != 0:
        logger.info(
            "oras discover found no pulp_results referrers for %s (%s)",
            ref,
            (discover.stderr or discover.stdout or "").strip(),
        )
        return []
    try:
        payload = json.loads(discover.stdout or "null")
    except json.JSONDecodeError:
        logger.warning("Invalid oras discover JSON for %s", ref)
        return []
    digests = _extract_referrer_digests_from_discover_payload(payload)
    return [f"{repo}@{digest}" for digest in digests]


def _clear_files_under_dir(dest_dir: Path) -> None:
    """Remove only files directly under ``dest_dir`` before a fresh ORAS pull."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for existing in dest_dir.iterdir():
        if existing.is_file():
            existing.unlink()


def _oras_pull_ref_to_dir(pull_ref: str, dest_dir: Path, *, clear_files: bool = True) -> None:
    """Run ``oras pull`` for ``pull_ref`` into ``dest_dir``."""
    ref = normalize_oci_artifact_reference(pull_ref)
    if not ref:
        raise OrasPublishError("OCI manifest reference is empty")
    if clear_files:
        _clear_files_under_dir(dest_dir)
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)

    pull_result = _run_oras(["pull", ref, "-o", str(dest_dir)], ref)
    if pull_result.returncode != 0:
        raise OrasPublishError(
            f"oras pull failed (exit {pull_result.returncode}): {pull_result.stderr or pull_result.stdout}"
        )
    _ensure_extracted_files_under_dest(dest_dir)


def _locate_pulp_results_json_in_dir(dest_dir: Path) -> Path | None:
    """Return ``pulp_results.json`` (or any ``*.json``) under ``dest_dir`` when present."""
    preferred = dest_dir / RESULTS_JSON_FILENAME
    if preferred.is_file():
        return preferred
    json_files = sorted(dest_dir.glob("*.json"))
    if not json_files:
        return None
    return json_files[0]


def _bundle_dir_has_rpms(dest_dir: Path) -> bool:
    return any(dest_dir.rglob("*.rpm"))


def _pull_pulp_results_json_direct(pull_ref: str, dest_dir: Path) -> Path:
    """ORAS-pull ``pulp_results.json`` from ``pull_ref`` without referrer discovery."""
    ref = normalize_oci_artifact_reference(pull_ref)
    _oras_pull_ref_to_dir(ref, dest_dir)
    located = _locate_pulp_results_json_in_dir(dest_dir)
    if located is None:
        raise OrasPublishError(f"No .json file under {dest_dir} after oras pull of {ref}")
    return located


def _select_newest_referrer_by_last_updated(referrer_refs: list[str]) -> str:
    best = referrer_refs[0]
    best_day: date | None = None
    with tempfile.TemporaryDirectory(prefix="pulp-results-referrer-") as tmp:
        root = Path(tmp)
        for idx, candidate in enumerate(referrer_refs):
            sub = root / str(idx)
            sub.mkdir()
            try:
                path = _pull_pulp_results_json_direct(candidate, sub)
                doc = json.loads(path.read_text(encoding="utf-8"))
                day = parse_last_updated(doc.get("last_updated"))
            except (OrasPublishError, OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if day is not None and (best_day is None or day > best_day):
                best_day = day
                best = candidate
    return best


def resolve_pulp_results_oci_pull_ref(subject_ref: str) -> str:
    """
    Resolve the OCI ref to pull for ``pulp_results.json``.

    When ``update-build`` (or similar) ORAS-attached a newer results JSON to the subject,
    prefer that referrer over the original subject artifact.
    """
    subject = normalize_oci_artifact_reference(subject_ref)
    referrers = discover_pulp_results_referrer_refs(subject)
    if not referrers:
        return subject
    if len(referrers) == 1:
        return referrers[0]
    return _select_newest_referrer_by_last_updated(referrers)


def pull_pulp_results_json(oci_manifest_ref: str, dest_dir: Path) -> Path:
    """
    ORAS-pull ``pulp_results.json`` from ``oci_manifest_ref`` into ``dest_dir``.

    Discovers attached ``pulp_results`` referrers on the subject first; falls back to the
    subject manifest when none exist.

    Returns the path to the pulled JSON file (prefers ``pulp_results.json``).
    """
    subject = normalize_oci_artifact_reference(oci_manifest_ref)
    pull_ref = resolve_pulp_results_oci_pull_ref(subject)
    if pull_ref != subject:
        logger.info("Using attached pulp_results at %s (subject %s)", pull_ref, subject)
    return _pull_pulp_results_json_direct(pull_ref, dest_dir)


def resolve_oci_transfer_artifact(subject_ref: str, work_root: Path) -> OciTransferResolution:
    """
    Resolve digest-pinned OCI input for ``transfer`` in order:

    1. ``pulp_results`` attached to the subject (ORAS referrer).
    2. ``pulp_results.json`` embedded in the subject manifest layers.
    3. Intermediate ORAS bundle (RPMs only, legacy promote path).
    """
    subject = normalize_oci_artifact_reference(subject_ref)
    if not subject:
        raise OrasPublishError("OCI manifest reference is empty")

    work_root.mkdir(parents=True, exist_ok=True)

    referrers = discover_pulp_results_referrer_refs(subject)
    if referrers:
        pull_ref = referrers[0] if len(referrers) == 1 else resolve_pulp_results_oci_pull_ref(subject)
        attach_dir = work_root / "attached"
        try:
            _oras_pull_ref_to_dir(pull_ref, attach_dir)
            attached_json = _locate_pulp_results_json_in_dir(attach_dir)
            if attached_json is not None:
                logger.info("Resolved pulp_results from attached referrer %s", pull_ref)
                return OciTransferResolution(kind="pulp_results", pulp_results_path=attached_json)
        except OrasPublishError as exc:
            logger.info("Attached referrer pull failed (%s); trying subject manifest", exc)

    subject_dir = work_root / "subject"
    _oras_pull_ref_to_dir(subject, subject_dir)
    subject_json = _locate_pulp_results_json_in_dir(subject_dir)
    if subject_json is not None:
        logger.info("Resolved pulp_results from subject OCI artifact %s", subject)
        return OciTransferResolution(kind="pulp_results", pulp_results_path=subject_json)

    if _bundle_dir_has_rpms(subject_dir):
        logger.info(
            "No pulp_results.json on %s; using intermediate ORAS RPM bundle at %s",
            subject,
            subject_dir,
        )
        return OciTransferResolution(kind="oci_bundle", bundle_dir=subject_dir)

    raise OrasPublishError(
        f"OCI ref {subject} has no pulp_results.json (attach or subject) and no RPM files after oras pull"
    )


__all__ = [
    "_ensure_extracted_files_under_dest",
    "discover_pulp_results_referrer_refs",
    "is_oci_artifact_reference",
    "normalize_oci_artifact_reference",
    "pull_pulp_results_json",
    "resolve_oci_transfer_artifact",
    "resolve_pulp_results_oci_pull_ref",
]
