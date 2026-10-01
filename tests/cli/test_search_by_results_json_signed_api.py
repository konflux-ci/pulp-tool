"""Tests for search-by --results-json (signed-by and API parsing)."""

import json
from unittest.mock import Mock, patch

from click.testing import CliRunner

from pulp_tool.cli import cli
from tests.support.constants import VALID_CHECKSUM_1
from tests.support.factories import make_rpm_list_response as _make_rpm_response
from tests.support.temp_config import tempfile_config


class TestSearchByResultsJsonSignedAndApiSkips:
    """search-by --results-json signed-by and invalid API rows."""

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_filename_handles_invalid_api_response(self, mock_client_class, tmp_path) -> None:
        """Test --filename skips invalid API response items (covers exception pass)."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg1-1.0-1.x86_64.rpm": {
                            "pulp_labels": {},
                            "url": "https://example.com/pkg1.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        }
                    },
                    "distributions": {},
                },
                indent=2,
            )
        )
        mock_response = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/1/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "pkg1",
                    "version": "1.0",
                    "release": "1",
                    "arch": "x86_64",
                    "location_href": "pkg1-1.0-1.x86_64.rpm",
                    "pulp_labels": {},
                },
                {"invalid": "item"},
            ]
        )
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = _make_rpm_response([])
        mock_client.get_rpm_by_filenames.return_value = mock_response
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--filename",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 0
        out = json.loads(results_output.read_text())
        assert "pkg1-1.0-1.x86_64.rpm" not in out["artifacts"]

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_signed_by_handles_invalid_api_response(self, mock_client_class, tmp_path) -> None:
        """Test --signed-by skips invalid API response items (covers exception pass)."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg1.rpm": {
                            "pulp_labels": {"signed_by": "key-123"},
                            "url": "https://example.com/pkg1.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        }
                    },
                    "distributions": {},
                },
                indent=2,
            )
        )
        mock_response = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/1/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "pkg1",
                    "version": "1",
                    "release": "1",
                    "arch": "x86_64",
                    "pulp_labels": {"signed_by": "key-123"},
                },
                {"invalid": "item"},
            ]
        )
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = _make_rpm_response([])
        mock_client.get_rpm_by_filenames.return_value = _make_rpm_response([])
        mock_client.get_rpm_by_signed_by.return_value = mock_response
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                    "--signed-by",
                    "key-123",
                ],
            )
        assert result.exit_code == 0
        out = json.loads(results_output.read_text())
        assert "pkg1.rpm" not in out["artifacts"]

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_filename_no_rpm_artifacts(self, mock_client_class, tmp_path) -> None:
        """Test results-json with no RPM artifacts writes input unchanged (no Pulp calls)."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {"sbom.json": {"pulp_labels": {}, "url": "https://x/sbom.json", "sha256": "f" * 64}},
                    "distributions": {},
                },
                indent=2,
            )
        )
        mock_client = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                    "--keep-files",
                ],
            )
        assert result.exit_code == 0
        assert "no RPM artifacts to filter" in result.output
        mock_client_class.create_from_config_file.assert_not_called()
        out = json.loads(results_output.read_text())
        assert out == json.loads(results_input.read_text())

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_signed_by_no_rpm_artifacts(self, mock_client_class, tmp_path) -> None:
        """Test --signed-by with no RPM artifacts: still searches Pulp, writes input unchanged."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {"sbom.json": {"pulp_labels": {}, "url": "https://x/sbom.json", "sha256": "f" * 64}},
                    "distributions": {},
                },
                indent=2,
            )
        )
        mock_response = _make_rpm_response([])
        mock_client = Mock()
        mock_client.get_rpm_by_signed_by.return_value = mock_response
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                    "--signed-by",
                    "key-id-123",
                    "--keep-files",
                ],
            )
        assert result.exit_code == 0
        mock_client.get_rpm_by_signed_by.assert_called_once_with(["key-id-123"])
        out = json.loads(results_output.read_text())
        assert out == json.loads(results_input.read_text())

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_signed_by_empty_key_uses_extraction(self, mock_client_class, tmp_path) -> None:
        """Test --signed-by with empty value: empty keys are filtered, extraction used, no RPM artifacts."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(json.dumps({"artifacts": {}, "distributions": {}}, indent=2))
        mock_client = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                    "--signed-by",
                    "",
                ],
            )
        assert result.exit_code == 0
        assert "no RPM artifacts to filter" in result.output

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_results_json_no_rpm_artifacts(self, mock_client_class, tmp_path) -> None:
        """Test results.json with no RPM artifacts writes unchanged."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {"log.txt": {"pulp_labels": {}, "url": "https://x.com/log", "sha256": "a" * 64}},
                    "distributions": {},
                },
                indent=2,
            )
        )
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                    "--keep-files",
                ],
            )
        assert result.exit_code == 0
        assert "no RPM artifacts to filter" in result.output
        assert results_output.exists()
        out = json.loads(results_output.read_text())
        assert out == json.loads(results_input.read_text())

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_output_results_default_removes_logs_and_sboms(self, mock_client_class, tmp_path) -> None:
        """Test default (no --keep-files): output-results contains only RPM artifacts."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg1.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg1.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        },
                        "log.txt": {"pulp_labels": {}, "url": "https://example.com/log.txt", "sha256": "f" * 64},
                        "sbom.json": {"pulp_labels": {}, "url": "https://example.com/sbom.json", "sha256": "e" * 64},
                    },
                    "distributions": {"rpms": "https://example.com/rpms/"},
                },
                indent=2,
            )
        )
        mock_response = _make_rpm_response([])
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = mock_response
        mock_client.get_rpm_by_filenames.return_value = _make_rpm_response([])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--checksum",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 0
        out = json.loads(results_output.read_text())
        assert "pkg1.rpm" in out["artifacts"]
        assert "log.txt" not in out["artifacts"]
        assert "sbom.json" not in out["artifacts"]
        assert out["distributions"] == {"rpms": "https://example.com/rpms/"}
