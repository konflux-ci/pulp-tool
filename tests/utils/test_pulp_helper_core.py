"""
Tests for PulpHelper class.

This module contains comprehensive tests for the PulpHelper class methods including
repository setup, distribution URL retrieval, and helper methods.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

from pulp_tool.models.pulp_api import RpmDistributionRequest, RpmRepositoryRequest
from pulp_tool.utils import PulpHelper, RepositoryRefs
from pulp_tool.utils.repository_manager import RepositoryApiOps


class TestPulpHelperInitialization:
    """Test PulpHelper initialization."""

    def test_init(self, mock_pulp_client) -> None:
        """Test PulpHelper initialization."""
        helper = PulpHelper(mock_pulp_client)
        assert helper.client == mock_pulp_client


class TestPulpHelperRepositoryMethods:
    """Test PulpHelper repository method access."""

    def test_get_repository_methods(self, mock_pulp_client) -> None:
        """Test get_repository_methods method."""
        helper = PulpHelper(mock_pulp_client)
        methods = helper._repository_manager.get_repository_methods("rpm")
        assert callable(methods.get)
        assert callable(methods.create)
        assert callable(methods.distro)
        assert callable(methods.get_distro)
        assert callable(methods.update_distro)
        assert callable(methods.wait_for_finished_task)


class TestPulpHelperSideTagRepository:
    """Side-tag RPM repository helper."""

    def test_ensure_side_tag_rpm_repository(self, mock_pulp_client) -> None:
        helper = PulpHelper(mock_pulp_client)
        captured_distro = None

        def _capture_create(_build_id, _repo_type, new_repository=None, new_distribution=None):
            nonlocal captured_distro
            captured_distro = new_distribution
            return ("prn:rpm", "/pulp/rpm/href/")

        with (
            patch.object(helper, "create_or_get_repository", side_effect=_capture_create),
            patch.object(helper, "distribution_url_for_base_path", return_value="https://pulp.example/ns/side-tag-t/"),
        ):
            href, url = helper.ensure_side_tag_rpm_repository("build-1", "t")
        assert href == "/pulp/rpm/href/"
        assert "side-tag-t" in url
        assert captured_distro is not None
        assert captured_distro.base_path == "build-1/side-tag-t"
        assert captured_distro.name == "build-1/side-tag-t"

    def test_ensure_side_tag_rpm_repository_missing_href(self, mock_pulp_client) -> None:
        helper = PulpHelper(mock_pulp_client)
        with patch.object(helper, "create_or_get_repository", return_value=("prn:rpm", None)):
            with pytest.raises(RuntimeError, match="No repository href"):
                helper.ensure_side_tag_rpm_repository("build-1", "t")


class TestPulpHelperRepositorySetup:
    """Test PulpHelper repository setup methods."""

    def test_setup_repositories(self, mock_pulp_client, mock_repositories) -> None:
        """Test setup_repositories method."""
        helper = PulpHelper(mock_pulp_client)
        expected_refs = RepositoryRefs(
            rpms_href=mock_repositories.get("rpms_href", ""),
            rpms_prn=mock_repositories.get("rpms_prn", ""),
            logs_href=mock_repositories.get("logs_href", ""),
            logs_prn=mock_repositories.get("logs_prn", ""),
            sbom_href=mock_repositories.get("sbom_href", ""),
            sbom_prn=mock_repositories.get("sbom_prn", ""),
            artifacts_href=mock_repositories.get("artifacts_href", ""),
            artifacts_prn=mock_repositories.get("artifacts_prn", ""),
        )
        with (
            patch.object(helper._repository_manager, "_setup_repositories_impl", return_value=mock_repositories),
            patch("pulp_tool.utils.validate_repository_setup", return_value=(True, [])),
        ):
            result = helper.setup_repositories("test-build-123")
        assert result == expected_refs

    def test_setup_repositories_validation_error(self, mock_pulp_client) -> None:
        """Test setup_repositories method with validation error."""
        helper = PulpHelper(mock_pulp_client)
        with (
            patch.object(helper._repository_manager, "_setup_repositories_impl", return_value={}),
            patch("pulp_tool.utils.validate_repository_setup", return_value=(False, ["Missing repo"])),
        ):
            with pytest.raises(RuntimeError, match="Repository setup validation failed"):
                helper.setup_repositories("test-build-123")

    def test_setup_repositories_with_sanitization(self, mock_pulp_client, mock_repositories) -> None:
        """Test PulpHelper setup_repositories with sanitization."""
        helper = PulpHelper(mock_pulp_client)
        expected_refs = RepositoryRefs(
            rpms_href=mock_repositories.get("rpms_href", ""),
            rpms_prn=mock_repositories.get("rpms_prn", ""),
            logs_href=mock_repositories.get("logs_href", ""),
            logs_prn=mock_repositories.get("logs_prn", ""),
            sbom_href=mock_repositories.get("sbom_href", ""),
            sbom_prn=mock_repositories.get("sbom_prn", ""),
            artifacts_href=mock_repositories.get("artifacts_href", ""),
            artifacts_prn=mock_repositories.get("artifacts_prn", ""),
        )
        with (
            patch.object(helper._repository_manager, "_setup_repositories_impl", return_value=mock_repositories),
            patch("pulp_tool.utils.validate_repository_setup", return_value=(True, [])),
        ):
            result = helper.setup_repositories("test/build:123")
        assert result == expected_refs

    def test_pulp_helper_invalid_build_id(self, mock_pulp_client) -> None:
        """Test PulpHelper with invalid build ID."""
        helper = PulpHelper(mock_pulp_client)
        with pytest.raises(ValueError, match="Invalid build ID"):
            helper.setup_repositories("")


class TestPulpHelperDistributionMethods:
    """Test PulpHelper distribution URL methods."""

    def test_get_distribution_urls(self, mock_pulp_client, mock_distribution_urls) -> None:
        """Test get_distribution_urls method."""
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")
        with patch.object(
            helper._distribution_manager, "_get_distribution_urls_impl", return_value=mock_distribution_urls
        ):
            result = helper.get_distribution_urls("test-build-123")
        assert result == mock_distribution_urls

    def test_get_distribution_urls_with_sanitization(self, mock_pulp_client, mock_distribution_urls) -> None:
        """Test PulpHelper get_distribution_urls with sanitization."""
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")
        with patch.object(
            helper._distribution_manager, "_get_distribution_urls_impl", return_value=mock_distribution_urls
        ):
            result = helper.get_distribution_urls("test/build:123")
        assert result == mock_distribution_urls

    def test_distribution_url_for_base_path_delegates(self, mock_pulp_client) -> None:
        """PulpHelper.distribution_url_for_base_path forwards to DistributionManager."""
        helper = PulpHelper(mock_pulp_client)
        assert (
            helper.distribution_url_for_base_path("x86_64")
            == "https://pulp.example.com/api/pulp-content/test-domain/x86_64/"
        )


class TestPulpHelperRepositoryOperations:
    """Test PulpHelper repository creation/retrieval operations."""

    def test_create_or_get_repository(self, mock_pulp_client, mock_repositories) -> None:
        """Test create_or_get_repository method."""
        helper = PulpHelper(mock_pulp_client)
        with patch.object(
            helper._repository_manager, "_create_or_get_repository_impl", return_value=("test-prn", "test-href")
        ):
            prn, href = helper.create_or_get_repository("test-build-123", "rpms")
        assert prn == "test-prn"
        assert href == "test-href"

    def test_create_or_get_repository_predefined(self, mock_pulp_client, mock_repositories) -> None:
        """Test create_or_get_repository method."""
        helper = PulpHelper(mock_pulp_client)
        new_repo = RpmRepositoryRequest(name="test-repo")
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-base-path")
        with patch.object(
            helper._repository_manager, "_create_or_get_repository_impl", return_value=("test-prn", "test-href")
        ):
            prn, href = helper.create_or_get_repository(None, "rpm", new_repo, new_distro)
        assert prn == "test-prn"
        assert href == "test-href"

    def test_ensure_rpm_repository_for_arch_delegates_to_repository_manager(self, mock_pulp_client) -> None:
        """ensure_rpm_repository_for_arch forwards to RepositoryManager."""
        helper = PulpHelper(mock_pulp_client)
        with patch.object(
            helper._repository_manager, "ensure_rpm_repository_for_arch", return_value="/rpm/href/"
        ) as mock_ensure:
            assert helper.ensure_rpm_repository_for_arch("my-build", "s390x") == "/rpm/href/"
        mock_ensure.assert_called_once_with("my-build", "s390x")

    def test_create_or_get_repository_invalid_type(self, mock_pulp_client) -> None:
        """Test create_or_get_repository method with invalid type."""
        helper = PulpHelper(mock_pulp_client)
        with pytest.raises(ValueError, match="Invalid repository or API type"):
            helper.create_or_get_repository("test-build-123", "invalid")

    def test_create_or_get_repository_with_sanitization(self, mock_pulp_client) -> None:
        """Test PulpHelper create_or_get_repository with sanitization."""
        helper = PulpHelper(mock_pulp_client)
        with patch.object(
            helper._repository_manager, "_create_or_get_repository_impl", return_value=("test-prn", "test-href")
        ):
            prn, href = helper.create_or_get_repository("test/build:123", "rpms")
        assert prn == "test-prn"
        assert href == "test-href"


class TestPulpHelperInternalMethods:
    """Test PulpHelper internal/private methods."""

    def test_parse_repository_response_error(self, mock_pulp_client) -> None:
        """Test PulpHelper _parse_repository_response with JSON error."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "Invalid response text"
        with pytest.raises(ValueError, match="Invalid JSON response from Pulp API"):
            helper._repository_manager._parse_repository_response(mock_response, "rpm", "test")

    def test_get_existing_repository(self, mock_pulp_client) -> None:
        """Test PulpHelper _get_existing_repository."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"prn": "test-prn", "pulp_href": "/pulp/api/v3/repositories/rpm/rpm/12345/"}]
        }
        methods = cast(RepositoryApiOps, SimpleNamespace(get=Mock(return_value=mock_response)))
        mock_pulp_client.check_response = Mock()
        result = helper._repository_manager._get_existing_repository(methods, "test-build/rpms", "rpms")
        assert result == ("test-prn", "/pulp/api/v3/repositories/rpm/rpm/12345/")

    def test_get_existing_repository_not_found(self, mock_pulp_client) -> None:
        """Test PulpHelper _get_existing_repository when not found."""
        helper = PulpHelper(mock_pulp_client)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        methods = cast(RepositoryApiOps, SimpleNamespace(get=Mock(return_value=mock_response)))
        mock_pulp_client.check_response = Mock()
        result = helper._repository_manager._get_existing_repository(methods, "test-build/rpms", "rpms")
        assert result is None

    def test_create_new_repository(self, mock_pulp_client) -> None:
        """Test PulpHelper _create_new_repository."""
        helper = PulpHelper(mock_pulp_client)
        mock_create_response = Mock()
        mock_create_response.json.return_value = {
            "prn": "test-prn",
            "pulp_href": "/pulp/api/v3/repositories/rpm/rpm/12345/",
        }
        methods = cast(RepositoryApiOps, SimpleNamespace(create=Mock(return_value=mock_create_response)))
        mock_pulp_client.check_response = Mock()
        new_repo = RpmRepositoryRequest(name="test-repo", autopublish=True)
        prn, href = helper._repository_manager._create_new_repository(methods, new_repo, "rpms")
        assert prn == "test-prn"
        assert href == "/pulp/api/v3/repositories/rpm/rpm/12345/"

    def test_wait_for_distribution_task(self, mock_pulp_client) -> None:
        """Test PulpHelper _wait_for_distribution_task."""
        from pulp_tool.models.pulp_api import TaskResponse

        helper = PulpHelper(mock_pulp_client)
        mock_task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/12345/",
            state="completed",
            created_resources=["/pulp/api/v3/distributions/rpm/rpm/12345/"],
        )
        mock_distro_response = Mock()
        mock_distro_response.is_success = True
        mock_distro_response.json.return_value = {"base_path": "test-build/rpms"}
        mock_pulp_client.session.get = Mock(return_value=mock_distro_response)
        methods = cast(RepositoryApiOps, SimpleNamespace(wait_for_finished_task=Mock(return_value=mock_task_response)))
        result = helper._repository_manager._wait_for_distribution_task(methods, "task-123", "rpms", "test-build")
        methods.wait_for_finished_task.assert_called_once_with("task-123")
        assert result == "test-build/rpms"

    def test_wait_for_distribution_task_no_resources(self, mock_pulp_client) -> None:
        """Test PulpHelper _wait_for_distribution_task with no created resources."""
        from pulp_tool.models.pulp_api import TaskResponse

        helper = PulpHelper(mock_pulp_client)
        mock_task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/12345/", state="completed", created_resources=[]
        )
        methods = cast(RepositoryApiOps, SimpleNamespace(wait_for_finished_task=Mock(return_value=mock_task_response)))
        helper._repository_manager._wait_for_distribution_task(methods, "task-123", "rpms", "test-build")
        methods.wait_for_finished_task.assert_called_once_with("task-123")

    def test_wait_for_distribution_task_json_error(self, mock_pulp_client) -> None:
        """Test PulpHelper _wait_for_distribution_task with failed task."""
        from pulp_tool.models.pulp_api import TaskResponse

        helper = PulpHelper(mock_pulp_client)
        mock_task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/12345/",
            state="failed",
            error={"description": "Task failed"},
            created_resources=[],
        )
        methods = cast(RepositoryApiOps, SimpleNamespace(wait_for_finished_task=Mock(return_value=mock_task_response)))
        with pytest.raises(ValueError, match="Distribution creation task failed"):
            helper._repository_manager._wait_for_distribution_task(methods, "task-123", "rpms", "test-build")

    def test_wait_for_distribution_task_uniqueness_conflict(self, mock_pulp_client) -> None:
        """Uniqueness task failure uses existing distribution instead of raising."""
        from pulp_tool.models.pulp_api import TaskResponse

        helper = PulpHelper(mock_pulp_client)
        uniqueness_error = (
            "{'base_path': [ErrorDetail(string='This field must be unique.', code='unique')], "
            "'name': [ErrorDetail(string='This field must be unique.', code='unique')]}"
        )
        mock_task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/12345/",
            state="failed",
            error={"description": uniqueness_error},
            created_resources=[],
        )
        mock_distro_response = Mock()
        mock_distro_response.status_code = 200
        mock_distro_response.json.return_value = {
            "results": [
                {
                    "name": "test-build/rpms",
                    "base_path": "test-build/rpms",
                    "repository": "expected-prn",
                }
            ]
        }
        mock_pulp_client.check_response = Mock()
        methods = cast(
            RepositoryApiOps,
            SimpleNamespace(
                wait_for_finished_task=Mock(return_value=mock_task_response),
                get_distro=Mock(return_value=mock_distro_response),
            ),
        )
        result = helper._repository_manager._wait_for_distribution_task(
            methods,
            "task-123",
            "rpms",
            "test-build",
            distribution_name="test-build/rpms",
            expected_repository="expected-prn",
        )
        assert result == "test-build/rpms"

    def test_wait_for_distribution_task_uniqueness_wrong_repository(self, mock_pulp_client) -> None:
        """Uniqueness task failure raises when existing distribution belongs elsewhere."""
        from pulp_tool.models.pulp_api import TaskResponse

        helper = PulpHelper(mock_pulp_client)
        uniqueness_error = (
            "{'base_path': [ErrorDetail(string='This field must be unique.', code='unique')], "
            "'name': [ErrorDetail(string='This field must be unique.', code='unique')]}"
        )
        mock_task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/12345/",
            state="failed",
            error={"description": uniqueness_error},
            created_resources=[],
        )
        mock_distro_response = Mock()
        mock_distro_response.status_code = 200
        mock_distro_response.json.return_value = {
            "results": [
                {
                    "name": "test-build/rpms",
                    "base_path": "test-build/rpms",
                    "repository": "other-prn",
                }
            ]
        }
        mock_pulp_client.check_response = Mock()
        methods = cast(
            RepositoryApiOps,
            SimpleNamespace(
                wait_for_finished_task=Mock(return_value=mock_task_response),
                get_distro=Mock(return_value=mock_distro_response),
            ),
        )
        with pytest.raises(ValueError, match="attached to repository"):
            helper._repository_manager._wait_for_distribution_task(
                methods,
                "task-123",
                "rpms",
                "test-build",
                distribution_name="test-build/rpms",
                expected_repository="expected-prn",
            )
