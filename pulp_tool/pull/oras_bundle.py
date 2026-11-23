"""Ingest ORAS-pulled RPM bundles (no ``pulp_results.json``) for intermediate ``transfer``."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ..models.artifacts import PulledArtifacts
from ..models.context import PullContext
from ..utils.artifact_detection import detect_arch_from_rpm_filename
from ..utils.validation.build_id import sanitize_build_id_for_repository, strip_namespace_from_build_id

logger = logging.getLogger(__name__)


def _default_labels(context: PullContext) -> dict[str, str]:
    labels: dict[str, str] = {}
    if context.build_id:
        labels["build_id"] = sanitize_build_id_for_repository(strip_namespace_from_build_id(context.build_id))
    if context.namespace:
        labels["namespace"] = context.namespace.strip()
    if context.cluster:
        labels["cluster"] = context.cluster.strip()
    return labels


def collect_pulled_artifacts_from_oras_bundle(bundle_dir: Path, context: PullContext) -> PulledArtifacts:
    """
    Build :class:`~pulp_tool.models.artifacts.PulledArtifacts` from ``*.rpm`` under ``bundle_dir``.

    Mirrors release-service-utils ORAS-pull + ``upload --rpm-path`` layout (flat or nested).
    """
    root = bundle_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"ORAS bundle directory not found: {root}")

    rpm_paths = sorted({p.resolve() for p in root.rglob("*.rpm") if p.is_file()})
    if not rpm_paths:
        raise ValueError(f"No RPM files found under ORAS bundle {root}")

    base_labels = _default_labels(context)
    pulled = PulledArtifacts()
    for rpm_path in rpm_paths:
        name = os.path.basename(rpm_path)
        arch = detect_arch_from_rpm_filename(str(rpm_path)) or "noarch"
        labels = dict(base_labels)
        labels.setdefault("arch", arch)
        pulled.add_rpm(name, str(rpm_path), labels)

    logger.info(
        "Intermediate ORAS bundle: %d RPM file(s) under %s",
        len(rpm_paths),
        root,
    )
    return pulled


__all__ = ["collect_pulled_artifacts_from_oras_bundle"]
