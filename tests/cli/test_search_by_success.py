"""Tests for search-by CLI command."""

import json
from unittest.mock import Mock, patch

from click.testing import CliRunner

from pulp_tool.cli import cli
from tests.support.constants import VALID_CHECKSUM_1, VALID_CHECKSUM_2
from tests.support.factories import make_rpm_list_response as _make_rpm_response
from tests.support.temp_config import tempfile_config


class TestSearchByChecksumSuccess:
    """Test successful search-by scenarios."""

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_single_checksum_json_output(self, mock_client_class) -> None:
        """Test single checksum with JSON output."""
        mock_response = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/v3/content/rpm/packages/12345/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "test-package",
                    "epoch": "0",
                    "version": "1.0.0",
                    "release": "1",
                    "arch": "x86_64",
                    "pulp_labels": {"build_id": "test-build"},
                }
            ]
        )
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = mock_response
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(cli, ["--config", config_path, "search-by", "--checksums", VALID_CHECKSUM_1])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 1
        assert output[0]["pkgId"] == VALID_CHECKSUM_1
        assert output[0]["name"] == "test-package"
        assert output[0]["version"] == "1.0.0"
        assert output[0]["arch"] == "x86_64"

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_multiple_checksums_repeated_option(self, mock_client_class) -> None:
        """Test multiple checksums via --checksums comma-separated."""
        mock_response = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/v3/content/rpm/packages/1/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "pkg1",
                    "epoch": "0",
                    "version": "1.0",
                    "release": "1",
                    "arch": "x86_64",
                    "pulp_labels": {},
                },
                {
                    "pulp_href": "/api/v3/content/rpm/packages/2/",
                    "sha256": VALID_CHECKSUM_2,
                    "name": "pkg2",
                    "epoch": "0",
                    "version": "2.0",
                    "release": "1",
                    "arch": "x86_64",
                    "pulp_labels": {},
                },
            ]
        )
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = mock_response
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli, ["--config", config_path, "search-by", "--checksums", f"{VALID_CHECKSUM_1},{VALID_CHECKSUM_2}"]
            )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 2
        assert output[0]["pkgId"] == VALID_CHECKSUM_1
        assert output[1]["pkgId"] == VALID_CHECKSUM_2

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_comma_separated_checksums(self, mock_client_class) -> None:
        """Test comma-separated checksums via --checksums option."""
        mock_response = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/v3/content/rpm/packages/1/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "pkg1",
                    "epoch": "0",
                    "version": "1.0",
                    "release": "1",
                    "arch": "x86_64",
                    "pulp_labels": {},
                }
            ]
        )
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = mock_response
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli, ["--config", config_path, "search-by", "--checksums", f"{VALID_CHECKSUM_1},{VALID_CHECKSUM_2}"]
            )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 1
        assert output[0]["pkgId"] == VALID_CHECKSUM_1

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_empty_results(self, mock_client_class) -> None:
        """Test empty results (no matching packages)."""
        mock_response = _make_rpm_response([])
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = mock_response
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(cli, ["--config", config_path, "search-by", "--checksums", VALID_CHECKSUM_1])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output == []

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_skips_invalid_api_response_items(self, mock_client_class) -> None:
        """Test that invalid API response items are skipped (covers except block)."""
        mock_response = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/v3/content/rpm/packages/1/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "valid-pkg",
                    "epoch": "0",
                    "version": "1.0",
                    "release": "1",
                    "arch": "x86_64",
                    "pulp_labels": {},
                },
                {"invalid": "item", "missing": "required_fields"},
                {"pulp_href": None, "sha256": None},
            ]
        )
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = mock_response
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(cli, ["--config", config_path, "search-by", "--checksums", VALID_CHECKSUM_1])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 1
        assert output[0]["name"] == "valid-pkg"

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_checksums_and_signed_by_single_call(self, mock_client_class) -> None:
        """Test --checksums + --signed-by uses single API call (server-side filter)."""
        pkg1 = {
            "pulp_href": "/api/v3/content/rpm/packages/1/",
            "sha256": VALID_CHECKSUM_1,
            "name": "pkg1",
            "epoch": "0",
            "version": "1.0",
            "release": "1",
            "arch": "x86_64",
            "pulp_labels": {"signed_by": "me"},
        }
        mock_client = Mock()
        mock_client.get_rpm_by_checksums_and_signed_by.return_value = _make_rpm_response([pkg1])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli, ["--config", config_path, "search-by", "--checksums", VALID_CHECKSUM_1, "--signed-by", "me"]
            )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 1
        assert output[0]["pulp_labels"]["signed_by"] == "me"
        mock_client.get_rpm_by_checksums_and_signed_by.assert_called_once_with([VALID_CHECKSUM_1], "me")

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_checksums_and_signed_by_no_match_returns_empty(self, mock_client_class) -> None:
        """Test --checksums + --signed-by returns empty when no match."""
        mock_client = Mock()
        mock_client.get_rpm_by_checksums_and_signed_by.return_value = _make_rpm_response([])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli, ["--config", config_path, "search-by", "--checksums", VALID_CHECKSUM_1, "--signed-by", "me"]
            )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output == []

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_filenames_only_has_packages(self, mock_client_class) -> None:
        """Test --filenames only (no signed_by) returns packages (lines 316-318)."""
        mock_client = Mock()
        mock_client.get_rpm_by_filenames.return_value = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/1/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "pkg",
                    "version": "1.0",
                    "release": "1",
                    "arch": "x86_64",
                    "location_href": "pkg-1.0-1.x86_64.rpm",
                    "pulp_labels": {},
                }
            ]
        )
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(cli, ["--config", config_path, "search-by", "--filenames", "pkg-1.0-1.x86_64.rpm"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 1
        assert output[0]["name"] == "pkg"

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_filenames_only_no_match_returns_empty(self, mock_client_class) -> None:
        """Test --filenames only (no signed_by) returns empty when no match (lines 320-322)."""
        mock_client = Mock()
        mock_client.get_rpm_by_filenames.return_value = _make_rpm_response([])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(cli, ["--config", config_path, "search-by", "--filenames", "pkg-1.0-1.x86_64.rpm"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_signed_by_only_has_packages(self, mock_client_class) -> None:
        """Test --signed-by only (no checksums/filenames) returns packages (lines 319-324)."""
        mock_client = Mock()
        mock_client.get_rpm_by_signed_by.return_value = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/1/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "pkg",
                    "version": "1.0",
                    "release": "1",
                    "arch": "x86_64",
                    "location_href": "pkg-1.0-1.x86_64.rpm",
                    "pulp_labels": {"signed_by": "key-123"},
                }
            ]
        )
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(cli, ["--config", config_path, "search-by", "--signed-by", "key-123"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 1
        assert output[0]["pulp_labels"]["signed_by"] == "key-123"
        mock_client.get_rpm_by_signed_by.assert_called_once_with(["key-123"])

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_signed_by_only_no_match_returns_empty(self, mock_client_class) -> None:
        """Test --signed-by only returns empty when no match (lines 319-324)."""
        mock_client = Mock()
        mock_client.get_rpm_by_signed_by.return_value = _make_rpm_response([])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(cli, ["--config", config_path, "search-by", "--signed-by", "key-123"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []
        mock_client.get_rpm_by_signed_by.assert_called_once_with(["key-123"])

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_filenames_and_signed_by_single_call(self, mock_client_class) -> None:
        """Test --filenames + --signed-by uses single API call (server-side filter)."""
        pkg_href = "/api/v3/content/rpm/packages/1/"
        pkg1 = {
            "pulp_href": pkg_href,
            "sha256": VALID_CHECKSUM_1,
            "name": "pkg1",
            "epoch": "0",
            "version": "1.0",
            "release": "1",
            "arch": "x86_64",
            "location_href": "pkg1-1.0-1.x86_64.rpm",
            "pulp_labels": {"signed_by": "me"},
        }
        mock_client = Mock()
        mock_client.get_rpm_by_filenames_and_signed_by.return_value = _make_rpm_response([pkg1])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli, ["--config", config_path, "search-by", "--filenames", "pkg1-1.0-1.x86_64.rpm", "--signed-by", "me"]
            )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 1
        assert output[0]["name"] == "pkg1"
        assert output[0]["pulp_labels"]["signed_by"] == "me"
        mock_client.get_rpm_by_filenames_and_signed_by.assert_called_once_with(["pkg1-1.0-1.x86_64.rpm"], "me")

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_filenames_and_signed_by_no_match_returns_empty(self, mock_client_class) -> None:
        """Test --filenames + --signed-by returns empty when no match (server-side filter)."""
        mock_client = Mock()
        mock_client.get_rpm_by_filenames_and_signed_by.return_value = _make_rpm_response([])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli, ["--config", config_path, "search-by", "--filenames", "pkg1-1.0-1.x86_64.rpm", "--signed-by", "me"]
            )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 0
