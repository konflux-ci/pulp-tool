"""Small typed rows for ``pulp_results.json`` and side-tag transfer."""

from __future__ import annotations

from ..base import KonfluxBaseModel
from ..href_history import HrefHistoryEntry


class SideTagRpmTransfer(KonfluxBaseModel):
    """Upload outcome for one RPM promoted to a side-tag repository."""

    artifact_key: str
    pulp_href: str
    sha256: str
    distribution_url: str


__all__ = [
    "HrefHistoryEntry",
    "SideTagRpmTransfer",
]
