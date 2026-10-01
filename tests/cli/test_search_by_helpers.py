"""Tests for search-by CLI command."""

from typing import Any
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from pulp_tool.models.cli import FoundPackages, SearchByRequest, SearchByResultsJson
from pulp_tool.services.search_by_service import (
    _collect_list,
    _filenames_to_nvras_deduplicated,
    _filenames_to_nvrs_deduplicated,
    _handle_validation_error,
    _log_packages_found,
    _search_pulp_by_filenames_incremental,
)
from tests.support.constants import VALID_CHECKSUM_1
from tests.support.factories import make_rpm_list_response as _make_rpm_response


class TestSearchByChecksumHelpers:
    """Unit tests for search-by helper functions and models."""

    def test_extract_rpm_checksums_from_results(self) -> None:
        """Test SearchByResultsJson.extract_rpm_checksums extracts valid checksums, skips invalid."""
        results = {
            "artifacts": {
                "pkg1.rpm": {"pulp_labels": {}, "url": "x", "sha256": "a" * 64},
                "pkg2.rpm": {"pulp_labels": {}, "url": "y", "sha256": "b" * 64},
                "log.txt": {"pulp_labels": {}, "url": "z", "sha256": "c" * 64},
                "bad.rpm": "not a dict",
            }
        }
        checksums = SearchByResultsJson(results).extract_rpm_checksums()
        assert set(checksums) == {"a" * 64, "b" * 64}

    def test_extract_filenames_from_results(self) -> None:
        """Test SearchByResultsJson.extract_filenames extracts RPM keys, skips non-RPM and invalid."""
        results = {
            "artifacts": {
                "pkg1.rpm": {"pulp_labels": {}, "url": "x", "sha256": "a" * 64},
                "pkg2.rpm": {"pulp_labels": {}, "url": "y", "sha256": "b" * 64},
                ".rpm": {"pulp_labels": {}, "url": "z", "sha256": "c" * 64},
                "log.txt": {"pulp_labels": {}, "url": "z", "sha256": "c" * 64},
                "bad": "not a dict",
            }
        }
        filenames = SearchByResultsJson(results).extract_filenames()
        assert set(filenames) == {"pkg1.rpm", "pkg2.rpm", ".rpm"}

    def test_remove_found_by_signed_by(self) -> None:
        """Test SearchByResultsJson.remove_found removes RPMs with matching labels.signed_by."""
        results = {
            "artifacts": {
                "pkg1.rpm": {"pulp_labels": {"signed_by": "key-123"}, "url": "x", "sha256": "a" * 64},
                "pkg2.rpm": {"pulp_labels": {"signed_by": "key-456"}, "url": "y", "sha256": "b" * 64},
                "pkg3.rpm": {"pulp_labels": {"signed_by": "  key-123  "}, "url": "z", "sha256": "c" * 64},
                "pkg4.rpm": {"labels": ["not-a-dict"]},
                "log.txt": {"pulp_labels": {}, "url": "w", "sha256": "d" * 64},
            }
        }
        found = FoundPackages(signed_by={"key-123", "key-456"}, checksums={"a" * 64, "b" * 64, "c" * 64})
        filtered = SearchByResultsJson(results).remove_found(found)
        assert "pkg1.rpm" not in filtered["artifacts"]
        assert "pkg2.rpm" not in filtered["artifacts"]
        assert "pkg3.rpm" not in filtered["artifacts"]
        assert "pkg4.rpm" in filtered["artifacts"]
        assert "log.txt" in filtered["artifacts"]

    def test_remove_found_signed_by_normalizes_artifact_label_for_match(self) -> None:
        """results.json may store raw signed_by; Pulp returns normalized; removal must still match."""
        from pulp_tool.models.pulp_label_values import normalize_signed_by_value_for_pulp

        raw_sb = "Acme (QA), builders"
        normalized = normalize_signed_by_value_for_pulp(raw_sb)
        assert normalized == "Acme [QA]: builders"
        results = {
            "artifacts": {
                "pkg1.rpm": {"pulp_labels": {"signed_by": raw_sb}, "url": "x", "sha256": "a" * 64},
            }
        }
        found = FoundPackages(signed_by={normalized}, checksums={"a" * 64})
        filtered = SearchByResultsJson(results).remove_found(found)
        assert "pkg1.rpm" not in filtered["artifacts"]

    def test_remove_found_by_filename_basename_match(self) -> None:
        """Test remove_found matches artifact keys by basename when key includes path."""
        results = {
            "artifacts": {
                "namespace/build-123/pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "x", "sha256": "a" * 64},
                "pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "y", "sha256": "b" * 64},
                "log.txt": {"pulp_labels": {}, "url": "z", "sha256": "c" * 64},
            }
        }
        found = FoundPackages(filenames={"pkg-1.0-1.x86_64.rpm"}, checksums={"a" * 64, "b" * 64})
        filtered = SearchByResultsJson(results).remove_found(found)
        assert "namespace/build-123/pkg-1.0-1.x86_64.rpm" not in filtered["artifacts"]
        assert "pkg-1.0-1.x86_64.rpm" not in filtered["artifacts"]
        assert "log.txt" in filtered["artifacts"]

    def test_remove_found_location_href_with_path_matches_artifact_key(self) -> None:
        """Test remove_found matches artifact keys when location_href from Pulp has path."""
        results = {
            "artifacts": {
                "pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "x", "sha256": "a" * 64},
                "path/to/pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "y", "sha256": "b" * 64},
                "log.txt": {"pulp_labels": {}, "url": "z", "sha256": "c" * 64},
            }
        }
        found = FoundPackages(
            filenames={"Packages/p/pkg-1.0-1.x86_64.rpm", "pkg-1.0-1.x86_64.rpm"}, checksums={"a" * 64, "b" * 64}
        )
        filtered = SearchByResultsJson(results).remove_found(found)
        assert "pkg-1.0-1.x86_64.rpm" not in filtered["artifacts"]
        assert "path/to/pkg-1.0-1.x86_64.rpm" not in filtered["artifacts"]
        assert "log.txt" in filtered["artifacts"]

    def test_remove_found_filename_checksum_pairs_requires_both_match(self) -> None:
        """Test remove_found with filename_checksum_pairs requires both basename and sha256 to match."""
        results = {
            "artifacts": {
                "pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "x", "sha256": "a" * 64},
                "other-pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "y", "sha256": "a" * 64},
                "path/pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "z", "sha256": "b" * 64},
            }
        }
        found = FoundPackages(filename_checksum_pairs={("pkg-1.0-1.x86_64.rpm", "a" * 64)}, checksums={"a" * 64})
        filtered = SearchByResultsJson(results).remove_found(found, only_remove_filenames={"pkg-1.0-1.x86_64.rpm"})
        assert "pkg-1.0-1.x86_64.rpm" not in filtered["artifacts"]
        assert "other-pkg-1.0-1.x86_64.rpm" in filtered["artifacts"]
        assert "path/pkg-1.0-1.x86_64.rpm" in filtered["artifacts"]

    def test_remove_found_filename_checksum_pairs_same_basename_different_sha256_not_removed(self) -> None:
        """Test artifact with same basename as Pulp package but different sha256 is NOT removed."""
        results = {"artifacts": {"pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "x", "sha256": "b" * 64}}}
        found = FoundPackages(filename_checksum_pairs={("pkg-1.0-1.x86_64.rpm", "a" * 64)}, checksums={"a" * 64})
        filtered = SearchByResultsJson(results).remove_found(found, only_remove_filenames={"pkg-1.0-1.x86_64.rpm"})
        assert "pkg-1.0-1.x86_64.rpm" in filtered["artifacts"]

    def test_remove_found_fallback_filenames_when_no_checksum_pairs(self) -> None:
        """Test remove_found uses filenames fallback when filename_checksum_pairs empty (no location_href)."""
        results = {"artifacts": {"path/pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "x", "sha256": "a" * 64}}}
        found = FoundPackages(filenames={"pkg-1.0-1.x86_64.rpm"}, checksums={"a" * 64})
        filtered = SearchByResultsJson(results).remove_found(found, only_remove_filenames={"pkg-1.0-1.x86_64.rpm"})
        assert "path/pkg-1.0-1.x86_64.rpm" not in filtered["artifacts"]

    def test_remove_found_filename_checksum_pairs_exact_match_removed(self) -> None:
        """Test artifact with same basename AND same sha256 as Pulp package IS removed."""
        results = {
            "artifacts": {
                "pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "x", "sha256": "a" * 64},
                "path/pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "y", "sha256": "a" * 64},
            }
        }
        found = FoundPackages(filename_checksum_pairs={("pkg-1.0-1.x86_64.rpm", "a" * 64)}, checksums={"a" * 64})
        filtered = SearchByResultsJson(results).remove_found(found, only_remove_filenames={"pkg-1.0-1.x86_64.rpm"})
        assert "pkg-1.0-1.x86_64.rpm" not in filtered["artifacts"]
        assert "path/pkg-1.0-1.x86_64.rpm" not in filtered["artifacts"]

    def test_collect_list_with_items(self) -> None:
        """Test _collect_list merges items tuple with csv, deduplicates, normalizes."""
        result = _collect_list(("a", "b", "a"), "b,c,d", normalize="lower")
        assert result == ["a", "b", "c", "d"]

    def test_filenames_to_nvras_deduplicated_includes_arch(self) -> None:
        """Test _filenames_to_nvras_deduplicated keeps same NVR with different arch as separate entries."""
        filenames = ["pkg-1.0-1.x86_64.rpm", "pkg-1.0-1.aarch64.rpm"]
        result = _filenames_to_nvras_deduplicated(filenames)
        assert result == [("pkg", "1.0", "1", "x86_64"), ("pkg", "1.0", "1", "aarch64")]

    def test_filenames_to_nvras_deduplicated_same_nvra_deduplicates(self) -> None:
        """Test _filenames_to_nvras_deduplicated deduplicates identical NVRA."""
        filenames = ["pkg-1.0-1.x86_64.rpm", "path/pkg-1.0-1.x86_64.rpm"]
        result = _filenames_to_nvras_deduplicated(filenames)
        assert result == [("pkg", "1.0", "1", "x86_64")]

    def test_filenames_to_nvras_deduplicated_skips_unparseable(self, caplog) -> None:
        """Test _filenames_to_nvras_deduplicated skips unparseable filenames with warning."""
        filenames = ["pkg-1.0-1.x86_64.rpm", "not-an-rpm.txt", "invalid.rpm"]
        result = _filenames_to_nvras_deduplicated(filenames)
        assert result == [("pkg", "1.0", "1", "x86_64")]
        assert "Skipping unparseable RPM filename" in caplog.text
        assert "not-an-rpm.txt" in caplog.text
        assert "invalid.rpm" in caplog.text

    def test_filenames_to_nvrs_deduplicated_merges_arches(self) -> None:
        """Test _filenames_to_nvrs_deduplicated collapses same NVR with different arches."""
        filenames = ["pkg-1.0-1.x86_64.rpm", "pkg-1.0-1.aarch64.rpm", "pkg-1.0-1.s390x.rpm"]
        result = _filenames_to_nvrs_deduplicated(filenames)
        assert result == [("pkg", "1.0", "1")]

    def test_filenames_to_nvrs_deduplicated_different_nvrs(self) -> None:
        """Test _filenames_to_nvrs_deduplicated keeps different NVRs."""
        filenames = ["pkg-1.0-1.x86_64.rpm", "other-2.0-2.x86_64.rpm"]
        result = _filenames_to_nvrs_deduplicated(filenames)
        assert result == [("pkg", "1.0", "1"), ("other", "2.0", "2")]

    def test_filenames_to_nvrs_deduplicated_skips_unparseable(self) -> None:
        """Test _filenames_to_nvrs_deduplicated skips unparseable filenames."""
        filenames = ["pkg-1.0-1.x86_64.rpm", "not-an-rpm.txt", "invalid.rpm"]
        result = _filenames_to_nvrs_deduplicated(filenames)
        assert result == [("pkg", "1.0", "1")]

    def test_log_packages_found_truncates_when_many(self, caplog) -> None:
        """Test _log_packages_found truncates DEBUG output when more than max_log packages."""
        from pulp_tool.models.pulp_api import RpmPackageResponse

        packages = [
            RpmPackageResponse(
                pulp_href=f"/api/{i}/",
                sha256=VALID_CHECKSUM_1,
                name="pkg",
                epoch="0",
                version="1.0",
                release="1",
                arch="x86_64",
                pulp_labels={},
            )
            for i in range(15)
        ]
        with caplog.at_level("DEBUG"):
            _log_packages_found(packages, max_log=10)
        assert "RPM exists in Pulp" in caplog.text
        assert "... and 5 more package(s)" in caplog.text

    def test_search_pulp_by_filenames_incremental_empty_artifacts_stops(self) -> None:
        """Test _search_pulp_by_filenames_incremental stops when no filenames (empty artifacts)."""
        client = Mock()
        results_data: dict[str, Any] = {"artifacts": {}, "distributions": {}}
        packages, filtered = _search_pulp_by_filenames_incremental(client, results_data, None, initial_filenames=None)
        assert packages == []
        assert filtered == results_data
        client.get_rpm_by_filenames.assert_not_called()

    def test_search_pulp_by_filenames_incremental_skips_when_no_matching_filename(self) -> None:
        """Test _search_pulp_by_filenames_incremental continues when first_matching is None (line 228)."""
        client = Mock()
        call_count = [0]

        def parse_side_effect(f: str) -> tuple[str, str, str]:
            call_count[0] += 1
            if call_count[0] <= 2:
                return ("a", "1.0", "1") if "a-" in f else ("b", "2.0", "2")
            if call_count[0] <= 4:
                return ("b", "2.0", "2")
            return ("a", "1.0", "1") if "a-" in f else ("b", "2.0", "2")

        with patch("pulp_tool.services.search_by_service.parse_rpm_filename_to_nvr", side_effect=parse_side_effect):
            results_data: dict[str, Any] = {
                "artifacts": {
                    "a-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "x", "sha256": "a" * 64},
                    "b-2.0-2.x86_64.rpm": {"pulp_labels": {}, "url": "y", "sha256": "b" * 64},
                },
                "distributions": {},
            }
            client.get_rpm_by_filenames.return_value = _make_rpm_response(
                [
                    {
                        "pulp_href": "/api/2/",
                        "sha256": "b" * 64,
                        "name": "b",
                        "version": "2.0",
                        "release": "2",
                        "arch": "x86_64",
                        "location_href": "b-2.0-2.x86_64.rpm",
                        "pulp_labels": {},
                    }
                ]
            )
            packages, filtered = _search_pulp_by_filenames_incremental(client, results_data, None)
            assert "b-2.0-2.x86_64.rpm" not in filtered["artifacts"]
            assert "a-1.0-1.x86_64.rpm" in filtered["artifacts"]

    def test_search_pulp_by_filenames_incremental_with_signed_by(self) -> None:
        """Test _search_pulp_by_filenames_incremental uses signed_by when provided."""
        pkg_dict = {
            "pulp_href": "/api/1/",
            "sha256": VALID_CHECKSUM_1,
            "name": "pkg",
            "epoch": "0",
            "version": "1.0",
            "release": "1",
            "arch": "x86_64",
            "location_href": "pkg-1.0-1.x86_64.rpm",
            "pulp_labels": {},
        }
        client = Mock()
        client.get_rpm_by_filenames_and_signed_by.return_value = _make_rpm_response([pkg_dict])
        results_data = {
            "artifacts": {"pkg-1.0-1.x86_64.rpm": {"pulp_labels": {}, "url": "x", "sha256": VALID_CHECKSUM_1}},
            "distributions": {},
        }
        packages, filtered = _search_pulp_by_filenames_incremental(
            client, results_data, "key-123", initial_filenames=None
        )
        assert len(packages) == 1
        client.get_rpm_by_filenames_and_signed_by.assert_called()
        assert "pkg-1.0-1.x86_64.rpm" not in filtered["artifacts"]

    def test_handle_validation_error_else_branch(self) -> None:
        """Test _handle_validation_error else branch for non-checksum ValidationError."""
        try:
            SearchByRequest(checksums=[], filenames=[], signed_by=[])
        except ValidationError as e:
            with pytest.raises(SystemExit):
                _handle_validation_error(e, results_json_context=False)
            return
        pytest.fail("Expected ValidationError")

    def test_search_by_results_json_to_dict(self) -> None:
        """Test SearchByResultsJson.to_dict returns underlying data."""
        data: dict[str, Any] = {"artifacts": {}, "distributions": {}}
        results = SearchByResultsJson(data)
        assert results.to_dict() is data
