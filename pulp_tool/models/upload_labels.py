"""Pulp label DTOs for upload operations."""

from __future__ import annotations

from .base import KonfluxBaseModel


class UploadLabels(KonfluxBaseModel):
    """Validated labels attached to uploaded Pulp content."""

    build_id: str
    arch: str = ""
    namespace: str
    parent_package: str | None = None
    date: str
    signed_by: str | None = None

    def to_pulp_dict(self) -> dict[str, str]:
        """Dict for Pulp API label fields."""
        labels: dict[str, str] = {
            "build_id": self.build_id,
            "arch": self.arch,
            "namespace": self.namespace,
            "date": self.date,
        }
        if self.parent_package:
            labels["parent_package"] = self.parent_package
        if self.signed_by and self.signed_by.strip():
            labels["signed_by"] = self.signed_by.strip()
        return labels

    @classmethod
    def from_upload_context(
        cls,
        *,
        build_id: str,
        arch: str,
        namespace: str,
        parent_package: str | None,
        date: str,
        signed_by: str | None = None,
    ) -> UploadLabels:
        return cls(
            build_id=build_id,
            arch=arch,
            namespace=namespace,
            parent_package=parent_package,
            date=date,
            signed_by=signed_by,
        )
