"""Upload pipeline: artifacts, batch JSON, results, and orchestration."""

# pylint: disable=undefined-all-variable

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import UploadService

__all__ = [
    "UploadService",
    "collect_results",
    "create_labels",
    "upload_artifacts_to_repository",
    "upload_log",
    "upload_rpms",
    "upload_rpms_logs",
    "upload_sbom",
    "UploadOrchestrator",
]


def __getattr__(name: str):
    if name == "UploadService":
        from .service import UploadService

        return UploadService
    if name == "collect_results":
        from .results import collect_results

        return collect_results
    if name == "upload_sbom":
        from .sbom import upload_sbom

        return upload_sbom
    if name == "UploadOrchestrator":
        from .pipeline import UploadOrchestrator

        return UploadOrchestrator
    if name == "create_labels":
        from .artifacts import create_labels

        return create_labels
    if name == "upload_artifacts_to_repository":
        from .artifacts import upload_artifacts_to_repository

        return upload_artifacts_to_repository
    if name == "upload_log":
        from .artifacts import upload_log

        return upload_log
    if name == "upload_rpms":
        from .artifacts import upload_rpms

        return upload_rpms
    if name == "upload_rpms_logs":
        from .artifacts import upload_rpms_logs

        return upload_rpms_logs
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
