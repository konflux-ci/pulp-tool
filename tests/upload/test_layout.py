"""Tests for :class:`pulp_tool.models.rpm_repo_layout.RpmRepoLayout`."""

from unittest.mock import patch

import pytest

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.rpm_repo_layout import RpmRepoLayout, RpmRepoLayoutMode


class TestRpmRepoLayout:
    """Repository naming and flags derived from upload context."""

    def test_from_context_default_build_rpms(self) -> None:
        ctx = UploadRpmContext(
            build_id="b1",
            date_str="2024-01-01",
            namespace="ns",
            parent_package="pkg",
            rpm_path="/rpms",
        )
        layout = RpmRepoLayout.from_context(ctx)
        assert layout.mode == RpmRepoLayoutMode.BUILD_RPMS
        assert not layout.uses_per_arch_repository

    def test_from_context_per_arch(self) -> None:
        ctx = UploadRpmContext(
            build_id="b1",
            date_str="2024-01-01",
            namespace="ns",
            parent_package="pkg",
            rpm_path="/rpms",
            target_arch_repo=True,
        )
        layout = RpmRepoLayout.from_context(ctx)
        assert layout.mode == RpmRepoLayoutMode.PER_ARCH
        assert layout.repository_name("any-build", "x86_64") == "x86_64"

    def test_from_context_build_scoped(self) -> None:
        ctx = UploadRpmContext(
            build_id="my-build",
            date_str="2024-01-01",
            namespace="ns",
            parent_package="pkg",
            rpm_path="/rpms",
            target_arch_repo=True,
            target_arch_repo_build_scoped=True,
        )
        layout = RpmRepoLayout.from_context(ctx)
        assert layout.mode == RpmRepoLayoutMode.PER_ARCH_BUILD_SCOPED
        assert layout.repository_name("my-build", "x86_64") == "my-build/x86_64"

    def test_repository_name_rejects_invalid_build_id_when_build_scoped(self) -> None:
        layout = RpmRepoLayout(mode=RpmRepoLayoutMode.PER_ARCH_BUILD_SCOPED)
        with pytest.raises(ValueError, match="Invalid build ID"):
            layout.repository_name("", "x86_64")
        with (
            patch("pulp_tool.models.rpm_repo_layout.sanitize_build_id_for_repository", return_value="bad"),
            patch("pulp_tool.models.rpm_repo_layout.validate_build_id", return_value=False),
        ):
            with pytest.raises(ValueError, match="Invalid build ID"):
                layout.repository_name("raw", "x86_64")

    def test_repository_name_matches_build_scoped_modes(self) -> None:
        per_arch = RpmRepoLayout(mode=RpmRepoLayoutMode.PER_ARCH)
        assert per_arch.repository_name("my-build", "x86_64") == "x86_64"
        scoped = RpmRepoLayout(mode=RpmRepoLayoutMode.PER_ARCH_BUILD_SCOPED)
        assert scoped.repository_name("my-build", "x86_64") == "my-build/x86_64"

    def test_repository_name_rejects_build_rpms_mode(self) -> None:
        layout = RpmRepoLayout(mode=RpmRepoLayoutMode.BUILD_RPMS)
        with pytest.raises(ValueError, match="per-arch layout"):
            layout.repository_name("my-build", "x86_64")

    def test_distribution_cache_type_build_rpms_mode(self) -> None:
        layout = RpmRepoLayout(mode=RpmRepoLayoutMode.BUILD_RPMS)
        assert layout.distribution_cache_type("my-build", "x86_64") == "rpm_arch:x86_64"
