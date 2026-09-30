"""Tests for search-by --results-json (NVR and explicit filenames)."""

import json
from unittest.mock import Mock, patch

from click.testing import CliRunner

from pulp_tool.cli import cli
from tests.support.constants import VALID_CHECKSUM_1, VALID_CHECKSUM_2, VALID_CHECKSUM_3
from tests.support.factories import make_rpm_list_response as _make_rpm_response
from tests.support.temp_config import tempfile_config


class TestSearchByResultsJsonNvrAndExplicit:
    """search-by --results-json NVR and explicit filenames."""

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_filename_different_nvrs_make_separate_calls(self, mock_client_class, tmp_path) -> None:
        """Test that artifacts with different NVRs still make separate API calls."""
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
                        "other-2.0-1.x86_64.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/other.rpm",
                            "sha256": VALID_CHECKSUM_3,
                        },
                    },
                    "distributions": {"rpms": "https://example.com/rpms/"},
                },
                indent=2,
            )
        )
        mock_response_pkg = _make_rpm_response(
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
        mock_response_other = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/3/",
                    "sha256": VALID_CHECKSUM_3,
                    "name": "other",
                    "version": "2.0",
                    "release": "1",
                    "arch": "x86_64",
                    "location_href": "other-2.0-1.x86_64.rpm",
                    "pulp_labels": {},
                }
            ]
        )
        mock_client = Mock()
        mock_client.get_rpm_by_filenames.side_effect = [mock_response_pkg, mock_response_other]
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
        assert "other-2.0-1.x86_64.rpm" not in out["artifacts"]
        assert mock_client.get_rpm_by_filenames.call_count == 2

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_filename_many_packages_truncates_msg(self, mock_client_class, tmp_path) -> None:
        """Test results-json with many packages found shows truncated msg (N packages)."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        arches = ["x86_64", "i686", "aarch64", "s390x", "ppc64le", "src", "noarch"] * 2
        checksums = ["a" * 63 + hex(i)[-1] for i in range(12)]
        artifacts = {
            f"pkg-1.0-1.{arch}.rpm": {"pulp_labels": {}, "url": "x", "sha256": checksums[i]}
            for i, arch in enumerate(arches[:12])
        }
        results_input.write_text(json.dumps({"artifacts": artifacts, "distributions": {}}, indent=2))
        mock_response = _make_rpm_response(
            [
                {
                    "pulp_href": f"/api/{i}/",
                    "sha256": checksums[i],
                    "name": "pkg",
                    "version": "1.0",
                    "release": "1",
                    "arch": arches[i],
                    "location_href": f"pkg-1.0-1.{arches[i]}.rpm",
                    "pulp_labels": {},
                }
                for i in range(12)
            ]
        )
        mock_client = Mock()
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
        assert "(12 packages)" in result.output

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_signed_by_removes_found_rpms(self, mock_client_class, tmp_path) -> None:
        """Test --signed-by: user specifies signing key(s), searches Pulp, removes found RPMs."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg1.rpm": {
                            "pulp_labels": {"arch": "x86_64", "signed_by": "key-id-123"},
                            "url": "https://example.com/pkg1.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        },
                        "pkg2.rpm": {
                            "pulp_labels": {"arch": "x86_64", "signed_by": "key-id-456"},
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
                    "pulp_labels": {"signed_by": "key-id-123"},
                }
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
                    "key-id-123",
                    "--keep-files",
                ],
            )
        assert result.exit_code == 0
        assert "removed 1 found RPM" in result.output
        mock_client.get_rpm_by_signed_by.assert_called_once_with(["key-id-123"])
        assert results_output.exists()
        out = json.loads(results_output.read_text())
        assert "pkg1.rpm" not in out["artifacts"]
        assert "pkg2.rpm" in out["artifacts"]
        assert "log.txt" in out["artifacts"]

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_results_json_checksums_and_signed_by_single_call(self, mock_client_class, tmp_path) -> None:
        """Test results-json with --checksums + --signed-by uses single API call."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg1.rpm": {
                            "pulp_labels": {"arch": "x86_64", "signed_by": "key-123"},
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
        pkg1 = {
            "pulp_href": "/api/v3/content/rpm/packages/1/",
            "sha256": VALID_CHECKSUM_1,
            "name": "pkg1",
            "epoch": "0",
            "version": "1.0",
            "release": "1",
            "arch": "x86_64",
            "pulp_labels": {"signed_by": "key-123"},
        }
        mock_client = Mock()
        mock_client.get_rpm_by_checksums_and_signed_by.return_value = _make_rpm_response([pkg1])
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
                    "--checksums",
                    VALID_CHECKSUM_1,
                    "--signed-by",
                    "key-123",
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
        mock_client.get_rpm_by_checksums_and_signed_by.assert_called_once_with([VALID_CHECKSUM_1], "key-123")

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_by_filenames_explicit_only(self, mock_client_class, tmp_path) -> None:
        """Test --filenames with explicit values (no flag, no extraction)."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(json.dumps({"artifacts": {}, "distributions": {}}, indent=2))
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = _make_rpm_response([])
        mock_client.get_rpm_by_filenames.return_value = _make_rpm_response(
            [
                {
                    "pulp_href": "/api/1/",
                    "sha256": VALID_CHECKSUM_1,
                    "name": "explicit",
                    "version": "1.0",
                    "release": "1",
                    "arch": "x86_64",
                    "location_href": "explicit-1.0-1.x86_64.rpm",
                    "pulp_labels": {},
                }
            ]
        )
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
                    "--filenames",
                    "explicit-1.0-1.x86_64.rpm",
                ],
            )
        assert result.exit_code == 0
        mock_client.get_rpm_by_filenames.assert_called_once_with(["explicit-1.0-1.x86_64.rpm"])
