"""RPM repository layout for upload (aggregate ``{build}/rpms`` vs per-arch)."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from pydantic import ConfigDict

from ..utils.constants import SUPPORTED_ARCHITECTURES
from ..utils.validation import sanitize_build_id_for_repository, validate_build_id
from .base import KonfluxBaseModel

if TYPE_CHECKING:
    from .context import UploadContext


class RpmRepoLayoutMode(str, Enum):
    """How RPM repositories and distributions are named during upload."""

    BUILD_RPMS = "build_rpms"
    PER_ARCH = "per_arch"
    PER_ARCH_BUILD_SCOPED = "per_arch_build_scoped"


class RpmRepoLayout(KonfluxBaseModel):
    """Single source for per-arch vs build-scoped RPM repo naming and URL paths."""

    model_config = ConfigDict(frozen=True)

    mode: RpmRepoLayoutMode = RpmRepoLayoutMode.BUILD_RPMS

    @classmethod
    def from_context(cls, context: UploadContext) -> RpmRepoLayout:
        """Derive layout from upload context CLI flags."""
        return cls.from_target_arch_flags(
            bool(getattr(context, "target_arch_repo", False)),
            bool(getattr(context, "target_arch_repo_build_scoped", False)),
        )

    @classmethod
    def from_target_arch_flags(cls, target_arch_repo: bool, build_scoped: bool) -> RpmRepoLayout:
        if not target_arch_repo:
            return cls(mode=RpmRepoLayoutMode.BUILD_RPMS)
        if build_scoped:
            return cls(mode=RpmRepoLayoutMode.PER_ARCH_BUILD_SCOPED)
        return cls(mode=RpmRepoLayoutMode.PER_ARCH)

    @property
    def uses_per_arch_repository(self) -> bool:
        return self.mode != RpmRepoLayoutMode.BUILD_RPMS

    @property
    def target_arch_repo(self) -> bool:
        """Compatibility with distribution manager and legacy call sites."""
        return self.uses_per_arch_repository

    @property
    def target_arch_repo_build_scoped(self) -> bool:
        return self.mode == RpmRepoLayoutMode.PER_ARCH_BUILD_SCOPED

    def repository_name(self, build_id: str, arch: str) -> str:
        """Pulp repository/distribution name for this layout and architecture."""
        arch_name = arch.strip()
        if arch_name not in SUPPORTED_ARCHITECTURES:
            raise ValueError(f"Unsupported architecture for RPM repository: {arch}")
        if self.mode == RpmRepoLayoutMode.BUILD_RPMS:
            raise ValueError("repository_name requires per-arch layout")
        if self.mode == RpmRepoLayoutMode.PER_ARCH:
            return arch_name
        if not build_id or not build_id.strip():
            raise ValueError(f"Invalid build ID: {build_id}")
        sanitized_build_id = sanitize_build_id_for_repository(build_id)
        if not validate_build_id(sanitized_build_id):
            raise ValueError(f"Invalid build ID: {build_id} (sanitized: {sanitized_build_id})")
        return f"{sanitized_build_id}/{arch_name}"

    def distribution_cache_type(self, build_id: str, arch: str) -> str:
        """Cache key segment for idempotent repository create."""
        arch_key = arch.strip()
        if self.mode == RpmRepoLayoutMode.PER_ARCH_BUILD_SCOPED:
            sanitized = sanitize_build_id_for_repository(build_id)
            return f"rpm_arch:{sanitized}:{arch_key}"
        if self.mode == RpmRepoLayoutMode.PER_ARCH:
            return f"rpm_arch:{arch_key}"
        return f"rpm_arch:{arch_key}"


def target_arch_repository_name(build_id: str, arch: str, *, build_scoped: bool) -> str:
    """Backward-compatible helper; prefer :meth:`RpmRepoLayout.repository_name`."""
    mode = RpmRepoLayoutMode.PER_ARCH_BUILD_SCOPED if build_scoped else RpmRepoLayoutMode.PER_ARCH
    return RpmRepoLayout(mode=mode).repository_name(build_id, arch)
