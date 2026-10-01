"""Tests for ociStorage resolution (--oci-storage flag only)."""

from pulp_tool.utils.oci_storage_resolve import resolve_oci_storage


class TestResolveOciStorage:
    def test_returns_flag_value(self) -> None:
        assert resolve_oci_storage("quay.io/from-flag", "/cfg.toml") == "quay.io/from-flag"

    def test_empty_when_unset(self) -> None:
        assert resolve_oci_storage("", "/cfg.toml") is None
        assert resolve_oci_storage(None, "/cfg.toml") is None

    def test_returns_none_without_config_path(self) -> None:
        assert resolve_oci_storage(None, None) is None
