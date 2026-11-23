"""OCI artifact resolution for ``transfer`` (attach → subject → RPM bundle)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from .base import KonfluxBaseModel


class OciTransferResolution(KonfluxBaseModel):
    """
    Outcome of resolving a digest-pinned OCI ref for ``transfer``.

    * ``pulp_results`` — local ``pulp_results.json`` (attached referrer or subject layer).
    * ``oci_bundle`` — ORAS-pulled RPM bundle with no ``pulp_results.json`` (legacy/intermediate path).
    """

    kind: Literal["pulp_results", "oci_bundle"]
    pulp_results_path: Path | None = None
    bundle_dir: Path | None = None

    @property
    def ok(self) -> bool:
        if self.kind == "pulp_results":
            return self.pulp_results_path is not None and self.pulp_results_path.is_file()
        return self.bundle_dir is not None and self.bundle_dir.is_dir()


__all__ = ["OciTransferResolution"]
