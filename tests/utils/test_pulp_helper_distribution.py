"""
Tests for PulpHelper class.

This module contains comprehensive tests for the PulpHelper class methods including
repository setup, distribution URL retrieval, and helper methods.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest
from httpx import HTTPError

from pulp_tool.exceptions import PulpToolHTTPError
from pulp_tool.models.pulp_api import RpmDistributionRequest, RpmRepositoryRequest
from pulp_tool.utils import PulpHelper
from pulp_tool.utils.repository_manager import (
    RepositoryApiOps,
    _is_distribution_uniqueness_error,
    _repository_identifiers_match,
    _repository_resource_id,
)


class TestRepositoryIdentifierHelpers:
    """Tests for PRN/href normalization helpers."""

    def test_repository_resource_id_empty(self) -> None:
        assert _repository_resource_id(None) is None
        assert _repository_resource_id("") is None
        assert _repository_resource_id("   ") is None

    def test_repository_identifiers_match_empty_or_exact(self) -> None:
        assert _repository_identifiers_match(None, "prn:x") is False
        assert _repository_identifiers_match("prn:x", None) is False
        assert _repository_identifiers_match("same-ref", "same-ref") is True


class TestPulpHelperDistributionOperations:
    """Test PulpHelper distribution checking and creation."""

    def test_is_distribution_uniqueness_error(self) -> None:
        """Detect Pulp uniqueness validation errors in task/HTTP bodies."""
        assert _is_distribution_uniqueness_error(
            "{'base_path': [ErrorDetail(string='This field must be unique.', code='unique')]}"
        )
        assert not _is_distribution_uniqueness_error("Task failed")
        assert not _is_distribution_uniqueness_error("")

    def test_get_existing_distribution(self, mock_pulp_client) -> None:
        """Return base_path and repository when distribution exists."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"base_path": "test-build/rpms", "repository": "prn:rpm:rpm:test-build/rpms"}]
        }
        mock_pulp_client.check_response = Mock()
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        existing = helper._repository_manager._get_existing_distribution(methods, "test-build/rpms", "rpms")
        assert existing is not None
        assert existing.base_path == "test-build/rpms"
        assert existing.repository == "prn:rpm:rpm:test-build/rpms"

    def test_resolve_existing_distribution_base_path(self, mock_pulp_client) -> None:
        """Validated lookup succeeds when repository matches."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"base_path": "test-build/rpms", "repository": "expected-prn"}]}
        mock_pulp_client.check_response = Mock()
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        base_path = helper._repository_manager._resolve_existing_distribution_base_path(
            methods, "test-build/rpms", "rpms", "expected-prn"
        )
        assert base_path == "test-build/rpms"

    def test_resolve_existing_distribution_base_path_href_matches_prn(self, mock_pulp_client) -> None:
        """Validated lookup accepts pulp_href when expected value is a PRN."""
        helper = PulpHelper(mock_pulp_client)
        repo_uuid = "019fcd4f-4293-7b90-9ddf-f7c8ead7a1c1"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "base_path": "test-build/artifacts",
                    "repository": f"/api/pulp/example/api/v3/repositories/file/file/{repo_uuid}/",
                }
            ]
        }
        mock_pulp_client.check_response = Mock()
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        base_path = helper._repository_manager._resolve_existing_distribution_base_path(
            methods,
            "test-build/artifacts",
            "artifacts",
            f"prn:file.filerepository:{repo_uuid}",
        )
        assert base_path == "test-build/artifacts"

    def test_resolve_existing_distribution_base_path_wrong_repository(self, mock_pulp_client) -> None:
        """Validated lookup fails when repository does not match."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"base_path": "test-build/rpms", "repository": "other-prn"}]}
        mock_pulp_client.check_response = Mock()
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        with pytest.raises(ValueError, match="attached to repository"):
            helper._repository_manager._resolve_existing_distribution_base_path(
                methods, "test-build/rpms", "rpms", "expected-prn"
            )

    def test_resolve_existing_distribution_base_path_not_loaded(self, mock_pulp_client) -> None:
        """Validated lookup fails when distribution cannot be loaded."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 404
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        with pytest.raises(ValueError, match="could not be loaded from Pulp"):
            helper._repository_manager._resolve_existing_distribution_base_path(
                methods, "test-build/rpms", "rpms", "expected-prn"
            )

    def test_resolve_existing_distribution_base_path_unknown_repository(self, mock_pulp_client) -> None:
        """Validated lookup fails when expected repository is unknown."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"base_path": "test-build/rpms", "repository": "expected-prn"}]}
        mock_pulp_client.check_response = Mock()
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        with pytest.raises(ValueError, match="expected repository is unknown"):
            helper._repository_manager._resolve_existing_distribution_base_path(
                methods, "test-build/rpms", "rpms", None
            )

    def test_resolve_existing_distribution_base_path_missing_repository_field(self, mock_pulp_client) -> None:
        """Validated lookup fails when existing distribution has no repository field."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"base_path": "test-build/rpms"}]}
        mock_pulp_client.check_response = Mock()
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        with pytest.raises(ValueError, match="has no repository"):
            helper._repository_manager._resolve_existing_distribution_base_path(
                methods, "test-build/rpms", "rpms", "expected-prn"
            )

    def test_get_existing_distribution_missing_base_path(self, mock_pulp_client) -> None:
        """Return None when distribution row has no base_path."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"repository": "expected-prn"}]}
        mock_pulp_client.check_response = Mock()
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        existing = helper._repository_manager._get_existing_distribution(methods, "test-build/rpms", "rpms")
        assert existing is None

    def test_get_existing_distribution_base_path(self, mock_pulp_client) -> None:
        """Return base_path when distribution exists."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"base_path": "test-build/rpms"}]}
        mock_pulp_client.check_response = Mock()
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        base_path = helper._repository_manager._get_existing_distribution_base_path(methods, "test-build/rpms", "rpms")
        assert base_path == "test-build/rpms"

    def test_get_existing_distribution_base_path_not_found(self, mock_pulp_client) -> None:
        """Return None when distribution is missing."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 404
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        base_path = helper._repository_manager._get_existing_distribution_base_path(methods, "test-build/rpms", "rpms")
        assert base_path is None

    def test_get_existing_distribution_base_path_empty_results(self, mock_pulp_client) -> None:
        """Return None when lookup succeeds but has no matching distribution."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_pulp_client.check_response = Mock()
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        base_path = helper._repository_manager._get_existing_distribution_base_path(methods, "test-build/rpms", "rpms")
        assert base_path is None

    def test_get_existing_distribution_base_path_lookup_error(self, mock_pulp_client) -> None:
        """Return None when distribution lookup raises."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(side_effect=HTTPError("API error"))))
        base_path = helper._repository_manager._get_existing_distribution_base_path(methods, "test-build/rpms", "rpms")
        assert base_path is None

    def test_cache_distribution_base_path(self, mock_pulp_client) -> None:
        """Cache validated base_path when expected repository is provided."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace())
        with patch.object(
            helper._repository_manager,
            "_resolve_existing_distribution_base_path",
            return_value="test-build/rpms",
        ) as mock_resolve:
            helper._repository_manager._cache_distribution_base_path(
                "test-build",
                "rpms",
                "test-build/rpms",
                methods,
                fallback_base_path="fallback",
                expected_repository="expected-prn",
            )
        mock_resolve.assert_called_once()
        assert helper._repository_manager._distribution_cache[("test-build", "rpms")] == "test-build/rpms"

    def test_cache_distribution_base_path_without_expected_repository(self, mock_pulp_client) -> None:
        """Cache uses unvalidated lookup when expected repository is omitted."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace())
        with patch.object(
            helper._repository_manager, "_get_existing_distribution_base_path", return_value="test-build/rpms"
        ):
            helper._repository_manager._cache_distribution_base_path(
                "test-build", "rpms", "test-build/rpms", methods, fallback_base_path="fallback"
            )
        assert helper._repository_manager._distribution_cache[("test-build", "rpms")] == "test-build/rpms"

    def test_cache_distribution_base_path_no_build_id(self, mock_pulp_client) -> None:
        """Skip caching when build_id is missing."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace())
        with patch.object(helper._repository_manager, "_get_existing_distribution_base_path") as mock_lookup:
            helper._repository_manager._cache_distribution_base_path(None, "rpms", "test-build/rpms", methods)
        mock_lookup.assert_not_called()

    def test_new_distribution_task_http_400_other_error_raises(self, mock_pulp_client) -> None:
        """Non-uniqueness HTTP 400 errors are still raised."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Invalid repository reference"
        methods = cast(RepositoryApiOps, SimpleNamespace(distro=Mock(return_value=mock_response)))
        mock_pulp_client.check_response = Mock(
            side_effect=PulpToolHTTPError("Failed to create distribution", response=mock_response)
        )
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-distro", repository="test-repo")
        with pytest.raises(PulpToolHTTPError):
            helper._repository_manager._new_distribution_task(methods, new_distro, "rpm")

    def test_create_distribution_task_http_400_already_exists(self, mock_pulp_client) -> None:
        """Create task returns empty string when POST reports distribution already exists."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace())
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-distro", repository="test-repo")
        with (
            patch.object(helper._repository_manager, "_check_existing_distribution", return_value=False),
            patch.object(helper._repository_manager, "_new_distribution_task", return_value=""),
            patch.object(helper._repository_manager, "_cache_distribution_base_path") as mock_cache,
        ):
            task_id = helper._repository_manager._create_distribution_task(
                methods, new_distro, "rpms", build_id="test-build"
            )
        assert task_id == ""
        mock_cache.assert_called_once()

    def test_check_existing_distribution(self, mock_pulp_client) -> None:
        """Test PulpHelper _check_existing_distribution."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"name": "test-build/rpms", "base_path": "test-build/rpms"}]}
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        result = helper._repository_manager._check_existing_distribution(methods, "test-build/rpms", "rpms")
        assert result is True

    def test_check_existing_distribution_not_found(self, mock_pulp_client) -> None:
        """Test PulpHelper _check_existing_distribution when not found."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        result = helper._repository_manager._check_existing_distribution(methods, "test-build/rpms", "rpms")
        assert result is False

    def test_check_existing_distribution_error(self, mock_pulp_client) -> None:
        """Test PulpHelper _check_existing_distribution with error."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(side_effect=HTTPError("API error"))))
        result = helper._repository_manager._check_existing_distribution(methods, "test-build/rpms", "rpms")
        assert result is False

    def test_check_existing_distribution_attribute_error(self, mock_pulp_client) -> None:
        """Test PulpHelper _check_existing_distribution with AttributeError."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace())
        result = helper._repository_manager._check_existing_distribution(methods, "test-build/rpms", "rpms")
        assert result is False

    def test_check_existing_distribution_value_error(self, mock_pulp_client) -> None:
        """Test PulpHelper _check_existing_distribution with ValueError."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(side_effect=ValueError("JSON error"))))
        result = helper._repository_manager._check_existing_distribution(methods, "test-build/rpms", "rpms")
        assert result is False

    def test_new_distribution_task(self, mock_pulp_client) -> None:
        """Test pulphelper _test_new_distribution_task"""
        helper = PulpHelper(mock_pulp_client)
        mock_distro_response = Mock()
        mock_distro_response.json.return_value = {"task": "/pulp/api/v3/tasks/12345/"}
        methods = cast(
            RepositoryApiOps,
            SimpleNamespace(
                distro=Mock(return_value=mock_distro_response),
                get_distro=Mock(return_value=Mock(json=lambda: {"results": []})),
            ),
        )
        mock_pulp_client.check_response = Mock()
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-distro", repository="test-repo")
        task_id = helper._repository_manager._new_distribution_task(methods, new_distro, "rpm")
        assert task_id == "/pulp/api/v3/tasks/12345/"

    def test_new_distribution_task_http_400_already_exists(self, mock_pulp_client) -> None:
        """HTTP 400 uniqueness on create is treated as already exists when repository matches."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = (
            "{'base_path': [ErrorDetail(string='This field must be unique.', code='unique')], "
            "'name': [ErrorDetail(string='This field must be unique.', code='unique')]}"
        )
        mock_lookup = Mock()
        mock_lookup.status_code = 200
        mock_lookup.json.return_value = {"results": [{"base_path": "test-distro", "repository": "test-repo"}]}
        methods = cast(
            RepositoryApiOps,
            SimpleNamespace(distro=Mock(return_value=mock_response), get_distro=Mock(return_value=mock_lookup)),
        )

        def check_response_side_effect(_response: Mock, operation: str = "request") -> None:
            if operation.startswith("create"):
                raise PulpToolHTTPError("Failed to create distribution", response=mock_response)

        mock_pulp_client.check_response = Mock(side_effect=check_response_side_effect)
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-distro", repository="test-repo")
        task_id = helper._repository_manager._new_distribution_task(methods, new_distro, "rpm")
        assert task_id == ""

    def test_new_distribution_task_http_400_wrong_repository(self, mock_pulp_client) -> None:
        """HTTP 400 uniqueness fails when existing distribution belongs elsewhere."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = (
            "{'base_path': [ErrorDetail(string='This field must be unique.', code='unique')], "
            "'name': [ErrorDetail(string='This field must be unique.', code='unique')]}"
        )
        mock_lookup = Mock()
        mock_lookup.status_code = 200
        mock_lookup.json.return_value = {"results": [{"base_path": "test-distro", "repository": "other-repo"}]}
        methods = cast(
            RepositoryApiOps,
            SimpleNamespace(distro=Mock(return_value=mock_response), get_distro=Mock(return_value=mock_lookup)),
        )

        def check_response_side_effect(_response: Mock, operation: str = "request") -> None:
            if operation.startswith("create"):
                raise PulpToolHTTPError("Failed to create distribution", response=mock_response)

        mock_pulp_client.check_response = Mock(side_effect=check_response_side_effect)
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-distro", repository="test-repo")
        with pytest.raises(ValueError, match="attached to repository"):
            helper._repository_manager._new_distribution_task(methods, new_distro, "rpm")

    def test_create_distribution_task(self, mock_pulp_client) -> None:
        """Test PulpHelper _create_distribution_task."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace())
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-distro", repository="test-repo")
        with (
            patch.object(helper._repository_manager, "_check_existing_distribution", return_value=False),
            patch.object(
                helper._repository_manager, "_new_distribution_task", return_value="/pulp/api/v3/tasks/12345/"
            ),
        ):
            task_id = helper._repository_manager._create_distribution_task(
                methods, new_distro, "rpms", build_id="test-build"
            )
        assert task_id == "/pulp/api/v3/tasks/12345/"

    def test_create_distribution_task_already_exists(self, mock_pulp_client) -> None:
        """Test PulpHelper _create_distribution_task when already exists."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace())
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-distro", repository="test-repo")
        with (
            patch.object(helper._repository_manager, "_check_existing_distribution", return_value=True),
            patch.object(helper._repository_manager, "_cache_distribution_base_path") as mock_cache,
        ):
            task_id = helper._repository_manager._create_distribution_task(methods, new_distro, "rpms")
        assert task_id == ""
        mock_cache.assert_called_once()

    def test_create_distribution_task_skips_for_new_repo_when_distribution_exists(self, mock_pulp_client) -> None:
        """New repositories still skip create when distribution already exists (504 retry case)."""
        helper = PulpHelper(mock_pulp_client)
        methods = cast(RepositoryApiOps, SimpleNamespace())
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-distro", repository="test-repo")
        with (
            patch.object(helper._repository_manager, "_check_existing_distribution", return_value=True),
            patch.object(helper._repository_manager, "_cache_distribution_base_path"),
            patch.object(helper._repository_manager, "_new_distribution_task") as mock_new,
        ):
            task_id = helper._repository_manager._create_distribution_task(
                methods, new_distro, "rpms", build_id="test-build"
            )
        assert task_id == ""
        mock_new.assert_not_called()

    def test_get_single_distribution_url(self, mock_pulp_client) -> None:
        """Test PulpHelper _get_single_distribution_url."""
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"results": [{"base_path": "test-build/rpms"}]}
        mock_pulp_client.repository_operation = Mock(return_value=mock_response)
        url = helper._distribution_manager._get_single_distribution_url(
            "test-build", "rpms", "https://pulp.example.com/pulp-content/"
        )
        assert url == "https://pulp.example.com/pulp-content/test-domain/test-build/rpms/"

    def test_get_single_distribution_url_not_found(self, mock_pulp_client) -> None:
        """Test PulpHelper _get_single_distribution_url when not found.

        Even when distribution is not found in API, we compute and return the expected URL.
        """
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"results": []}
        url = helper._distribution_manager._get_single_distribution_url(
            "test-build", "rpms", "https://pulp.example.com/pulp-content/"
        )
        assert url == "https://pulp.example.com/pulp-content/test-domain/test-build/rpms/"

    def test_get_single_distribution_url_error(self, mock_pulp_client) -> None:
        """Test PulpHelper _get_single_distribution_url with error.

        Even with API errors, we compute and return the expected URL.
        """
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")
        mock_response = Mock()
        mock_response.is_success = False
        mock_response.status_code = 404
        mock_response.text = "Not found"
        url = helper._distribution_manager._get_single_distribution_url(
            "test-build", "rpms", "https://pulp.example.com/pulp-content/"
        )
        assert url == "https://pulp.example.com/pulp-content/test-domain/test-build/rpms/"

    def test_get_single_distribution_url_exception(self, mock_pulp_client) -> None:
        """Test PulpHelper _get_single_distribution_url with exception.

        Even when exceptions occur, we compute and return the expected URL.
        """
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")
        url = helper._distribution_manager._get_single_distribution_url(
            "test-build", "rpms", "https://pulp.example.com/pulp-content/"
        )
        assert url == "https://pulp.example.com/pulp-content/test-domain/test-build/rpms/"

    def test_get_distribution_urls_impl(self, mock_pulp_client) -> None:
        """Test PulpHelper _get_distribution_urls_impl."""
        helper = PulpHelper(mock_pulp_client)
        with patch.object(helper._distribution_manager, "_get_single_distribution_url") as mock_get_url:
            mock_get_url.side_effect = lambda build_id, repo_type, base_url: (
                f"{base_url}{helper.namespace}/{build_id}/{repo_type}/"
            )
            result = helper._distribution_manager._get_distribution_urls_impl("test-build")
        assert len(result) == 4
        assert "rpms" in result
        assert "logs" in result
        assert "sbom" in result
        assert "artifacts" in result
        assert result["rpms"] == "https://pulp.example.com/api/pulp-content/test-domain/test-build/rpms/"


class TestPulpHelperRepositoryImplementation:
    """Test PulpHelper repository implementation methods."""

    def test_create_or_get_repository_impl_new(self, mock_pulp_client) -> None:
        """Test PulpHelper _create_or_get_repository_impl with new repository."""
        helper = PulpHelper(mock_pulp_client)
        with (
            patch.object(helper._repository_manager, "get_repository_methods") as mock_get_methods,
            patch.object(helper._repository_manager, "_get_existing_repository", return_value=None),
            patch.object(helper._repository_manager, "_create_new_repository", return_value=("test-prn", "test-href")),
            patch.object(helper._repository_manager, "_create_distribution_task", return_value="task-123"),
            patch.object(helper._repository_manager, "_wait_for_distribution_task"),
        ):
            mock_get_methods.return_value = {}
            new_repo_def = RpmRepositoryRequest(name="test-repo")
            new_distro_def = RpmDistributionRequest(name="test-repo", base_path="test-repo")
            prn, href = helper._repository_manager._create_or_get_repository_impl(
                new_repo_def, new_distro_def, "rpms", "test-build"
            )
        assert new_distro_def.repository == "test-prn"
        assert prn == "test-prn"
        assert href == "test-href"

    def test_create_or_get_repository_impl_existing(self, mock_pulp_client) -> None:
        """Test PulpHelper _create_or_get_repository_impl with existing repository."""
        helper = PulpHelper(mock_pulp_client)
        with (
            patch.object(helper._repository_manager, "get_repository_methods") as mock_get_methods,
            patch.object(
                helper._repository_manager, "_get_existing_repository", return_value=("test-prn", "test-href")
            ),
            patch.object(helper._repository_manager, "_create_distribution_task", return_value="task-123"),
            patch.object(helper._repository_manager, "_wait_for_distribution_task"),
        ):
            mock_get_methods.return_value = {}
            new_repo_def = RpmRepositoryRequest(name="test-repo")
            new_distro_def = RpmDistributionRequest(name="test-repo", base_path="test-repo")
            prn, href = helper._repository_manager._create_or_get_repository_impl(
                new_repo_def, new_distro_def, "file", "test-build"
            )
        assert new_distro_def.repository == "test-prn"
        assert prn == "test-prn"
        assert href == "test-href"

    def test_create_or_get_repository_impl_no_task(self, mock_pulp_client) -> None:
        """Test PulpHelper _create_or_get_repository_impl with no distribution task."""
        helper = PulpHelper(mock_pulp_client)
        with (
            patch.object(helper._repository_manager, "get_repository_methods") as mock_get_methods,
            patch.object(
                helper._repository_manager, "_get_existing_repository", return_value=("test-prn", "test-href")
            ),
            patch.object(helper._repository_manager, "_create_distribution_task", return_value=""),
        ):
            mock_get_methods.return_value = {}
            mock_get_methods.return_value = {}
            new_repo_def = RpmRepositoryRequest(name="test-repo")
            new_distro_def = RpmDistributionRequest(name="test-repo", base_path="test-repo")
            prn, href = helper._repository_manager._create_or_get_repository_impl(
                new_repo_def, new_distro_def, "rpms", "test-build"
            )
        assert prn == "test-prn"
        assert href == "test-href"
