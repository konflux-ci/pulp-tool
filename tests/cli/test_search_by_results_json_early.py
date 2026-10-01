"""Tests for search-by --results-json (early flows)."""

import json
from unittest.mock import Mock, patch

from click.testing import CliRunner

from pulp_tool.cli import cli
from tests.support.constants import VALID_CHECKSUM_1, VALID_CHECKSUM_2
from tests.support.factories import make_rpm_list_response as _make_rpm_response
from tests.support.temp_config import tempfile_config


class TestSearchByResultsJsonEarlyFlows:
    """search-by --results-json early extraction and filename flows."""

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_results_json_handles_invalid_api_response_items(self, mock_client_class, tmp_path) -> None:
        """Test that invalid API response items are skipped when building found set."""
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
                    "sha256": VALID_CHECKSUM_1,
                    "pulp_href": "/api/1/",
                    "name": "pkg1",
                    "version": "1",
                    "release": "1",
                    "arch": "x86_64",
                    "epoch": "0",
                    "pulp_labels": {},
                },
                {"invalid": "item"},
            ]
        )
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
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 0
        out = json.loads(results_output.read_text())
        assert "pkg1.rpm" not in out["artifacts"]

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_results_json_real_world_structure(self, mock_client_class, tmp_path) -> None:
        """Test with real-world results.json: path-style keys, distributions, mixed types."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "ns/build-id/sbom-merged.json": {
                            "pulp_labels": {"arch": "", "build_id": "build-id"},
                            "url": "https://example.com/sbom/sbom-merged.json",
                            "sha256": "1" * 64,
                        },
                        "ns/build-id/s390x/state.log": {
                            "pulp_labels": {"arch": "s390x", "build_id": "build-id"},
                            "url": "https://example.com/logs/s390x/state.log",
                            "sha256": "2" * 64,
                        },
                        "pkg-1.0-1.el10.s390x.rpm": {
                            "pulp_labels": {"arch": "s390x", "build_id": "build-id"},
                            "url": "https://example.com/rpms/pkg.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        },
                        "pkg-debuginfo-1.0-1.el10.s390x.rpm": {
                            "pulp_labels": {"arch": "s390x", "build_id": "build-id"},
                            "url": "https://example.com/rpms/pkg-debuginfo.rpm",
                            "sha256": VALID_CHECKSUM_2,
                        },
                    },
                    "distributions": {
                        "rpms": "https://example.com/rpms/",
                        "logs": "https://example.com/logs/",
                        "sbom": "https://example.com/sbom/",
                        "artifacts": "https://example.com/artifacts/",
                    },
                },
                indent=2,
            )
        )
        mock_response = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/1/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "pkg",
                    "version": "1.0",
                    "release": "1",
                    "arch": "s390x",
                    "epoch": "0",
                    "pulp_labels": {},
                }
            ]
        )
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
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                    "--keep-files",
                ],
            )
        assert result.exit_code == 0
        out = json.loads(results_output.read_text())
        assert "pkg-1.0-1.el10.s390x.rpm" not in out["artifacts"]
        assert "pkg-debuginfo-1.0-1.el10.s390x.rpm" in out["artifacts"]
        assert "ns/build-id/sbom-merged.json" in out["artifacts"]
        assert "ns/build-id/s390x/state.log" in out["artifacts"]
        assert out["distributions"] == {
            "rpms": "https://example.com/rpms/",
            "logs": "https://example.com/logs/",
            "sbom": "https://example.com/sbom/",
            "artifacts": "https://example.com/artifacts/",
        }

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_results_json_checksum_flag_extracts_and_removes_found_rpms(self, mock_client_class, tmp_path) -> None:
        """Test --checksum flag: extracts checksums from results.json, removes found RPMs."""
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
                        "pkg2.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg2.rpm",
                            "sha256": VALID_CHECKSUM_2,
                        },
                        "log.txt": {"pulp_labels": {}, "url": "https://example.com/log.txt", "sha256": "f" * 64},
                    },
                    "distributions": {"rpms": "https://example.com/rpms/"},
                },
                indent=2,
            )
        )
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
                    "--keep-files",
                ],
            )
        assert result.exit_code == 0
        assert "removed 1 found RPM" in result.output
        assert "pkg1-1.0-1.x86_64" in result.output
        assert results_output.exists()
        out = json.loads(results_output.read_text())
        assert "pkg1.rpm" not in out["artifacts"]
        assert "pkg2.rpm" in out["artifacts"]
        assert "log.txt" in out["artifacts"]
        assert out["distributions"] == {"rpms": "https://example.com/rpms/"}

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_filename_flag_extracts_from_results_json(self, mock_client_class, tmp_path) -> None:
        """Test --filename flag: extracts artifact keys from results.json, searches Pulp."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg1-1.0-1.x86_64.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg1.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        },
                        "pkg2-2.0-2.x86_64.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg2.rpm",
                            "sha256": VALID_CHECKSUM_2,
                        },
                        "log.txt": {"pulp_labels": {}, "url": "https://example.com/log.txt", "sha256": "f" * 64},
                    },
                    "distributions": {"rpms": "https://example.com/rpms/"},
                },
                indent=2,
            )
        )
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
                    "location_href": "pkg1-1.0-1.x86_64.rpm",
                    "pulp_labels": {},
                }
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
                    "--keep-files",
                ],
            )
        assert result.exit_code == 0
        assert "removed 1 found RPM" in result.output
        assert mock_client.get_rpm_by_filenames.call_count == 2
        all_calls = [c[0][0][0] for c in mock_client.get_rpm_by_filenames.call_args_list]
        assert "pkg1-1.0-1.x86_64.rpm" in all_calls
        assert "pkg2-2.0-2.x86_64.rpm" in all_calls
        assert results_output.exists()
        out = json.loads(results_output.read_text())
        assert "pkg1-1.0-1.x86_64.rpm" not in out["artifacts"]
        assert "pkg2-2.0-2.x86_64.rpm" in out["artifacts"]
        assert "log.txt" in out["artifacts"]

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_filename_removes_all_arches_for_same_nvr(self, mock_client_class, tmp_path) -> None:
        """Test that artifacts sharing the same NVR are all removed in one API call."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg-1.0-1.x86_64.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        },
                        "pkg-1.0-1.s390x.rpm": {
                            "pulp_labels": {"arch": "s390x"},
                            "url": "https://example.com/pkg-s390x.rpm",
                            "sha256": VALID_CHECKSUM_2,
                        },
                    },
                    "distributions": {"rpms": "https://example.com/rpms/"},
                },
                indent=2,
            )
        )
        mock_response_both = _make_rpm_response(
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
                },
                {
                    "pulp_href": "/api/2/",
                    "sha256": VALID_CHECKSUM_2,
                    "name": "pkg",
                    "version": "1.0",
                    "release": "1",
                    "arch": "s390x",
                    "location_href": "pkg-1.0-1.s390x.rpm",
                    "pulp_labels": {},
                },
            ]
        )
        mock_client = Mock()
        mock_client.get_rpm_by_filenames.return_value = mock_response_both
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
        assert "pkg-1.0-1.x86_64.rpm" not in out["artifacts"]
        assert "pkg-1.0-1.s390x.rpm" not in out["artifacts"]
        assert mock_client.get_rpm_by_filenames.call_count == 1
