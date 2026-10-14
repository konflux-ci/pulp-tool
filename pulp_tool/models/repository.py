"""Repository-related models for Konflux Pulp."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import KonfluxBaseModel

if TYPE_CHECKING:
    from .context import UploadRpmContext


class RepositoryRefs(KonfluxBaseModel):
    """
    Repository references for all content types.

    Attributes:
        rpms_href: Pulp href for RPM repository
        rpms_prn: Pulp Resource Name for RPM repository
        logs_href: Pulp href for logs repository
        logs_prn: Pulp Resource Name for logs repository
        sbom_href: Pulp href for SBOM repository
        sbom_prn: Pulp Resource Name for SBOM repository
        artifacts_href: Pulp href for artifacts repository
        artifacts_prn: Pulp Resource Name for artifacts repository
        rpms_signed_href: Pulp href for signed RPM repository (when --signed-by used)
        rpms_signed_prn: Pulp Resource Name for signed RPM repository
        logs_signed_href: Pulp href for signed logs repository
        logs_signed_prn: Pulp Resource Name for signed logs repository
        sbom_signed_href: Pulp href for signed SBOM repository
        sbom_signed_prn: Pulp Resource Name for signed SBOM repository
        artifacts_signed_href: Pulp href for signed artifacts repository
        artifacts_signed_prn: Pulp Resource Name for signed artifacts repository
    """

    rpms_href: str
    rpms_prn: str
    logs_href: str
    logs_prn: str
    sbom_href: str
    sbom_prn: str
    artifacts_href: str
    artifacts_prn: str
    rpms_signed_href: str = ""
    rpms_signed_prn: str = ""
    logs_signed_href: str = ""
    logs_signed_prn: str = ""
    sbom_signed_href: str = ""
    sbom_signed_prn: str = ""
    artifacts_signed_href: str = ""
    artifacts_signed_prn: str = ""

    def rpm_href_for_upload(self, context: "UploadRpmContext") -> str:
        """Return RPM repository href for directory upload (signed aggregate or bulk ``rpms``)."""
        from .context import UploadRpmContext

        if not isinstance(context, UploadRpmContext):
            raise TypeError("context must be UploadRpmContext")
        if context.uses_signed_aggregate_rpm_repo():
            if not self.rpms_signed_href:
                raise ValueError("signed_by requires signed RPM repository href")
            return self.rpms_signed_href
        if not self.rpms_href:
            raise ValueError("RPM repository href is required but not found")
        return self.rpms_href

    def require_logs_prn_for_upload(self) -> str:
        if not self.logs_prn or not str(self.logs_prn).strip():
            raise ValueError(
                "Log files are present but logs repository PRN is empty. "
                "Create the logs repository when uploading logs (do not set skip_logs_repo)."
            )
        return self.logs_prn


class RepositoryInfo(KonfluxBaseModel):
    """
    Information about a created or retrieved repository.

    Attributes:
        href: Pulp href for the repository
        prn: Pulp Resource Name (optional, for file repositories)
    """

    href: str
    prn: str | None = None


__all__ = ["RepositoryRefs", "RepositoryInfo"]
