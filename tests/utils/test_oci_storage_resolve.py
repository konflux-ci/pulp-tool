"""Tests for ociStorage resolution (CLI flag vs config)."""

from unittest.mock import patch

from pulp_tool.utils.oci_storage_resolve import resolve_oci_storage


class TestResolveOciStorage:
    def test_cli_flag_takes_precedence(self) -> None:
        with patch("pulp_tool.utils.oci_storage_resolve.ConfigManager") as mock_cfg:
            assert resolve_oci_storage("quay.io/from-flag", "/cfg.toml") == "quay.io/from-flag"
            mock_cfg.assert_not_called()

    def test_falls_back_to_config(self) -> None:
        with patch("pulp_tool.utils.oci_storage_resolve.ConfigManager") as mock_cfg_cls:
            mock_cfg = mock_cfg_cls.return_value
            mock_cfg.get.return_value = "quay.io/from-config"
            assert resolve_oci_storage(None, "/cfg.toml") == "quay.io/from-config"
            mock_cfg.load.assert_called_once()

    def test_empty_when_unset(self) -> None:
        with patch("pulp_tool.utils.oci_storage_resolve.ConfigManager") as mock_cfg_cls:
            mock_cfg = mock_cfg_cls.return_value
            mock_cfg.get.return_value = None
            assert resolve_oci_storage("", "/cfg.toml") is None

    def test_returns_none_without_config_path(self) -> None:
        assert resolve_oci_storage(None, None) is None

    def test_returns_none_when_config_load_fails(self) -> None:
        with patch("pulp_tool.utils.oci_storage_resolve.ConfigManager", side_effect=OSError("nope")):
            assert resolve_oci_storage(None, "/cfg.toml") is None
