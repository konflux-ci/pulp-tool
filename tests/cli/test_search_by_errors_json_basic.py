"""Tests for search-by CLI error handling (checksum args)."""

from unittest.mock import Mock, patch

import httpx
from click.testing import CliRunner

from pulp_tool.cli import cli
from tests.support.constants import VALID_CHECKSUM_1
from tests.support.temp_config import tempfile_config


class TestSearchByChecksumErrors:
    """Test search-by error handling."""

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_http_error(self, mock_client_class) -> None:
        """Test HTTP error handling."""
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.side_effect = httpx.HTTPError("Connection failed")
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(cli, ["--config", config_path, "search-by", "--checksums", VALID_CHECKSUM_1])
        assert result.exit_code == 1

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_generic_exception(self, mock_client_class) -> None:
        """Test generic exception handling."""
        mock_client_class.create_from_config_file.side_effect = ValueError("Config error")
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(cli, ["--config", config_path, "search-by", "--checksums", VALID_CHECKSUM_1])
        assert result.exit_code == 1
