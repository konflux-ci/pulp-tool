"""Small typed rows for ``pulp_results.json`` and side-tag transfer."""

from __future__ import annotations

from pydantic import field_validator

from ..base import KonfluxBaseModel
from ..href_history import HrefHistoryEntry


class SideTagRpmTransfer(KonfluxBaseModel):
    """Upload outcome for one RPM promoted to a side-tag repository."""

    artifact_key: str
    pulp_href: str
    sha256: str
    distribution_url: str

    @field_validator("artifact_key")
    @classmethod
    def artifact_key_must_name_rpm(cls, value: str) -> str:
        key = (value or "").strip()
        if not key.lower().endswith(".rpm"):
            raise ValueError(
                f"side-tag transfer only records RPM artifacts; artifact_key must end with .rpm (got {value!r})",
            )
        return key


__all__ = [
    "HrefHistoryEntry",
    "SideTagRpmTransfer",
]
