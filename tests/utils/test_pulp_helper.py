"""
Tests for PulpHelper class.

This module contains comprehensive tests for the PulpHelper class methods including
repository setup, distribution URL retrieval, and helper methods.
"""

from unittest.mock import Mock, patch
from httpx import HTTPError
import pytest

from pulp_tool.utils import PulpHelper, RepositoryRefs


class TestPulpHelperInitialization:
    """Test PulpHelper initialization."""

    def test_init(self, mock_pulp_client):
        """Test PulpHelper initialization."""
        helper = PulpHelper(mock_pulp_client)

        assert helper.client == mock_pulp_client
        assert helper.cert_config_path is None

    def test_init_with_cert_config(self, mock_pulp_client):
        """Test PulpHelper initialization with cert config."""
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")

        assert helper.client == mock_pulp_client
        assert helper.cert_config_path == "/path/to/cert-config.toml"


class TestPulpHelperRepositoryMethods:
    """Test PulpHelper repository method access."""

    def test_get_repository_methods(self, mock_pulp_client):
        """Test get_repository_methods method."""
        helper = PulpHelper(mock_pulp_client)

        methods = helper.get_repository_methods("rpm")

        assert "get" in methods
        assert "create" in methods
        assert "distro" in methods
        assert "get_distro" in methods
        assert "update_distro" in methods
        assert "wait_for_finished_task" in methods


class TestPulpHelperRepositorySetup:
    """Test PulpHelper repository setup methods."""

    def test_setup_repositories(self, mock_pulp_client, mock_repositories):
        """Test setup_repositories method."""
        helper = PulpHelper(mock_pulp_client)

        # Expected RepositoryRefs result
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

        with patch.object(helper, "_setup_repositories_impl", return_value=mock_repositories), patch(
            "pulp_tool.utils.validate_repository_setup", return_value=(True, [])
        ):

            result = helper.setup_repositories("test-build-123")

        assert result == expected_refs

    def test_setup_repositories_validation_error(self, mock_pulp_client):
        """Test setup_repositories method with validation error."""
        helper = PulpHelper(mock_pulp_client)

        with patch.object(helper, "_setup_repositories_impl", return_value={}), patch(
            "pulp_tool.utils.validate_repository_setup", return_value=(False, ["Missing repo"])
        ):

            with pytest.raises(RuntimeError, match="Repository setup validation failed"):
                helper.setup_repositories("test-build-123")

    def test_setup_repositories_with_sanitization(self, mock_pulp_client, mock_repositories):
        """Test PulpHelper setup_repositories with sanitization."""
        helper = PulpHelper(mock_pulp_client)

        # Expected RepositoryRefs result
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

        with patch.object(helper, "_setup_repositories_impl", return_value=mock_repositories), patch(
            "pulp_tool.utils.validate_repository_setup", return_value=(True, [])
        ):

            result = helper.setup_repositories("test/build:123")

        assert result == expected_refs

    def test_pulp_helper_invalid_build_id(self, mock_pulp_client):
        """Test PulpHelper with invalid build ID."""
        helper = PulpHelper(mock_pulp_client)

        with pytest.raises(ValueError, match="Invalid build ID"):
            helper.setup_repositories("")


class TestPulpHelperDistributionMethods:
    """Test PulpHelper distribution URL methods."""

    def test_get_distribution_urls(self, mock_pulp_client, mock_distribution_urls):
        """Test get_distribution_urls method."""
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")

        with patch.object(helper, "_get_distribution_urls_impl", return_value=mock_distribution_urls):
            result = helper.get_distribution_urls("test-build-123")

        assert result == mock_distribution_urls

    def test_get_distribution_urls_with_sanitization(self, mock_pulp_client, mock_distribution_urls):
        """Test PulpHelper get_distribution_urls with sanitization."""
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")

        with patch.object(helper, "_get_distribution_urls_impl", return_value=mock_distribution_urls):
            result = helper.get_distribution_urls("test/build:123")

        assert result == mock_distribution_urls


class TestPulpHelperRepositoryOperations:
    """Test PulpHelper repository creation/retrieval operations."""

    def test_create_or_get_repository(self, mock_pulp_client, mock_repositories):
        """Test create_or_get_repository method."""
        helper = PulpHelper(mock_pulp_client)

        with patch.object(helper, "_create_or_get_repository_impl", return_value=("test-prn", "test-href")):
            prn, href = helper.create_or_get_repository("test-build-123", "rpms")

        assert prn == "test-prn"
        assert href == "test-href"

    def test_create_or_get_repository_invalid_type(self, mock_pulp_client):
        """Test create_or_get_repository method with invalid type."""
        helper = PulpHelper(mock_pulp_client)

        with pytest.raises(ValueError, match="Invalid repository type"):
            helper.create_or_get_repository("test-build-123", "invalid")

    def test_create_or_get_repository_with_sanitization(self, mock_pulp_client):
        """Test PulpHelper create_or_get_repository with sanitization."""
        helper = PulpHelper(mock_pulp_client)

        with patch.object(helper, "_create_or_get_repository_impl", return_value=("test-prn", "test-href")):
            prn, href = helper.create_or_get_repository("test/build:123", "rpms")

        assert prn == "test-prn"
        assert href == "test-href"


class TestPulpHelperInternalMethods:
    """Test PulpHelper internal/private methods."""

    def test_parse_repository_response_error(self, mock_pulp_client):
        """Test PulpHelper _parse_repository_response with JSON error."""
        helper = PulpHelper(mock_pulp_client)

        mock_response = Mock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "Invalid response text"

        with pytest.raises(ValueError, match="Invalid JSON response from Pulp API"):
            helper._parse_repository_response(mock_response, "rpm", "test")

    def test_get_existing_repository(self, mock_pulp_client):
        """Test PulpHelper _get_existing_repository."""
        helper = PulpHelper(mock_pulp_client)

        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [{"prn": "test-prn", "pulp_href": "/pulp/api/v3/repositories/rpm/rpm/12345/"}]
        }

        methods = {"get": Mock(return_value=mock_response)}

        mock_pulp_client.check_response = Mock()

        result = helper._get_existing_repository(methods, "test-build/rpms", "rpms")

        assert result == ("test-prn", "/pulp/api/v3/repositories/rpm/rpm/12345/")

    def test_get_existing_repository_not_found(self, mock_pulp_client):
        """Test PulpHelper _get_existing_repository when not found."""
        helper = PulpHelper(mock_pulp_client)

        mock_response = Mock()
        mock_response.json.return_value = {"results": []}

        methods = {"get": Mock(return_value=mock_response)}

        mock_pulp_client.check_response = Mock()

        result = helper._get_existing_repository(methods, "test-build/rpms", "rpms")

        assert result is None

    def test_create_new_repository(self, mock_pulp_client):
        """Test PulpHelper _create_new_repository."""
        helper = PulpHelper(mock_pulp_client)

        mock_create_response = Mock()
        # The create response now returns the repository object directly
        mock_create_response.json.return_value = {
            "prn": "test-prn",
            "pulp_href": "/pulp/api/v3/repositories/rpm/rpm/12345/",
        }

        methods = {"create": Mock(return_value=mock_create_response)}

        mock_pulp_client.check_response = Mock()

        prn, href = helper._create_new_repository(methods, "test-build/rpms", "rpms")

        assert prn == "test-prn"
        assert href == "/pulp/api/v3/repositories/rpm/rpm/12345/"

    def test_wait_for_distribution_task(self, mock_pulp_client):
        """Test PulpHelper _wait_for_distribution_task."""
        from pulp_tool.models.pulp_api import TaskResponse

        helper = PulpHelper(mock_pulp_client)

        mock_task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/12345/",
            state="completed",
            created_resources=["/pulp/api/v3/distributions/rpm/rpm/12345/"],
        )

        # Mock the session.get method to return distribution details
        mock_distro_response = Mock()
        mock_distro_response.is_success = True
        mock_distro_response.json.return_value = {"base_path": "test-build/rpms"}
        mock_pulp_client.session.get = Mock(return_value=mock_distro_response)

        methods = {"wait_for_finished_task": Mock(return_value=mock_task_response)}

        result = helper._wait_for_distribution_task(methods, "task-123", "rpms", "test-build")

        methods["wait_for_finished_task"].assert_called_once_with("task-123")
        assert result == "test-build/rpms"

    def test_wait_for_distribution_task_no_resources(self, mock_pulp_client):
        """Test PulpHelper _wait_for_distribution_task with no created resources."""
        from pulp_tool.models.pulp_api import TaskResponse

        helper = PulpHelper(mock_pulp_client)

        mock_task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/12345/", state="completed", created_resources=[]
        )

        methods = {"wait_for_finished_task": Mock(return_value=mock_task_response)}

        helper._wait_for_distribution_task(methods, "task-123", "rpms", "test-build")

        methods["wait_for_finished_task"].assert_called_once_with("task-123")

    def test_wait_for_distribution_task_json_error(self, mock_pulp_client):
        """Test PulpHelper _wait_for_distribution_task with failed task."""
        from pulp_tool.models.pulp_api import TaskResponse

        helper = PulpHelper(mock_pulp_client)

        # Now we test with a failed task instead of JSON error
        mock_task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/12345/",
            state="failed",
            error={"description": "Task failed"},
            created_resources=[],
        )

        methods = {"wait_for_finished_task": Mock(return_value=mock_task_response)}

        with pytest.raises(ValueError, match="Distribution creation task failed"):
            helper._wait_for_distribution_task(methods, "task-123", "rpms", "test-build")


class TestPulpHelperDistributionOperations:
    """Test PulpHelper distribution checking and creation."""

    def test_check_existing_distribution(self, mock_pulp_client):
        """Test PulpHelper _check_existing_distribution."""
        helper = PulpHelper(mock_pulp_client)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"name": "test-build/rpms", "base_path": "test-build/rpms"}]}

        methods = {"get_distro": Mock(return_value=mock_response)}

        result = helper._check_existing_distribution(methods, "test-build/rpms", "rpms")

        assert result is True

    def test_check_existing_distribution_not_found(self, mock_pulp_client):
        """Test PulpHelper _check_existing_distribution when not found."""
        helper = PulpHelper(mock_pulp_client)

        mock_response = Mock()
        mock_response.json.return_value = {"results": []}

        methods = {"get_distro": Mock(return_value=mock_response)}

        result = helper._check_existing_distribution(methods, "test-build/rpms", "rpms")

        assert result is False

    def test_check_existing_distribution_error(self, mock_pulp_client):
        """Test PulpHelper _check_existing_distribution with error."""
        helper = PulpHelper(mock_pulp_client)

        methods = {"get_distro": Mock(side_effect=HTTPError("API error"))}

        result = helper._check_existing_distribution(methods, "test-build/rpms", "rpms")

        assert result is False

    def test_check_existing_distribution_attribute_error(self, mock_pulp_client):
        """Test PulpHelper _check_existing_distribution with AttributeError."""
        helper = PulpHelper(mock_pulp_client)

        methods = {}

        result = helper._check_existing_distribution(methods, "test-build/rpms", "rpms")

        assert result is False

    def test_check_existing_distribution_value_error(self, mock_pulp_client):
        """Test PulpHelper _check_existing_distribution with ValueError."""
        helper = PulpHelper(mock_pulp_client)

        methods = {"get_distro": Mock(side_effect=ValueError("JSON error"))}

        result = helper._check_existing_distribution(methods, "test-build/rpms", "rpms")

        assert result is False

    def test_create_distribution_task(self, mock_pulp_client):
        """Test PulpHelper _create_distribution_task."""
        helper = PulpHelper(mock_pulp_client)

        mock_distro_response = Mock()
        mock_distro_response.json.return_value = {"task": "/pulp/api/v3/tasks/12345/"}

        methods = {
            "distro": Mock(return_value=mock_distro_response),
            "get_distro": Mock(return_value=Mock(json=lambda: {"results": []})),
        }

        mock_pulp_client.check_response = Mock()

        with patch.object(helper, "_check_existing_distribution", return_value=False):
            task_id = helper._create_distribution_task("test-build", "rpms", "test-prn", methods)

        assert task_id == "/pulp/api/v3/tasks/12345/"

    def test_create_distribution_task_already_exists(self, mock_pulp_client):
        """Test PulpHelper _create_distribution_task when already exists."""
        helper = PulpHelper(mock_pulp_client)

        methods = {}

        with patch.object(helper, "_check_existing_distribution", return_value=True):
            task_id = helper._create_distribution_task("test-build", "rpms", "test-prn", methods)

        assert task_id == ""  # Empty string indicates distribution already exists

    def test_get_single_distribution_url(self, mock_pulp_client):
        """Test PulpHelper _get_single_distribution_url."""
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"results": [{"base_path": "test-build/rpms"}]}

        mock_pulp_client.repository_operation = Mock(return_value=mock_response)

        with patch.object(helper, "get_repository_methods") as mock_get_methods:
            mock_get_methods.return_value = {"get_distro": Mock(return_value=mock_response)}

            url = helper._get_single_distribution_url("test-build", "rpms", "https://pulp.example.com/pulp-content/")

        assert url == "https://pulp.example.com/pulp-content/test-domain/test-build/rpms/"

    def test_get_single_distribution_url_not_found(self, mock_pulp_client):
        """Test PulpHelper _get_single_distribution_url when not found.

        Even when distribution is not found in API, we compute and return the expected URL.
        """
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"results": []}

        with patch.object(helper, "get_repository_methods") as mock_get_methods:
            mock_get_methods.return_value = {"get_distro": Mock(return_value=mock_response)}

            url = helper._get_single_distribution_url("test-build", "rpms", "https://pulp.example.com/pulp-content/")

        # Now returns computed URL even if not found in API
        assert url == "https://pulp.example.com/pulp-content/test-domain/test-build/rpms/"

    def test_get_single_distribution_url_error(self, mock_pulp_client):
        """Test PulpHelper _get_single_distribution_url with error.

        Even with API errors, we compute and return the expected URL.
        """
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")

        mock_response = Mock()
        mock_response.is_success = False
        mock_response.status_code = 404
        mock_response.text = "Not found"

        with patch.object(helper, "get_repository_methods") as mock_get_methods:
            mock_get_methods.return_value = {"get_distro": Mock(return_value=mock_response)}

            url = helper._get_single_distribution_url("test-build", "rpms", "https://pulp.example.com/pulp-content/")

        # Now returns computed URL even with API error
        assert url == "https://pulp.example.com/pulp-content/test-domain/test-build/rpms/"

    def test_get_single_distribution_url_exception(self, mock_pulp_client):
        """Test PulpHelper _get_single_distribution_url with exception.

        Even when exceptions occur, we compute and return the expected URL.
        """
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")

        with patch.object(helper, "get_repository_methods", side_effect=HTTPError("API error")):
            url = helper._get_single_distribution_url("test-build", "rpms", "https://pulp.example.com/pulp-content/")

        # Now returns computed URL even with exception
        assert url == "https://pulp.example.com/pulp-content/test-domain/test-build/rpms/"

    def test_get_distribution_urls_impl(self, mock_pulp_client):
        """Test PulpHelper _get_distribution_urls_impl."""
        helper = PulpHelper(mock_pulp_client, "/path/to/cert-config.toml")

        mock_pulp_client.get_domain = Mock(return_value="test-domain")

        with patch(
            "pulp_tool.utils.pulp_helper.get_pulp_content_base_url",
            return_value="https://pulp.example.com/pulp-content",
        ), patch.object(helper, "_get_single_distribution_url") as mock_get_url:
            mock_get_url.return_value = "https://pulp.example.com/pulp-content/test-domain/test-build/rpms/"

            result = helper._get_distribution_urls_impl("test-build")

        assert len(result) == 4  # All repo types
        assert "rpms" in result


class TestPulpHelperRepositoryImplementation:
    """Test PulpHelper repository implementation methods."""

    def test_create_or_get_repository_impl_new(self, mock_pulp_client):
        """Test PulpHelper _create_or_get_repository_impl with new repository."""
        helper = PulpHelper(mock_pulp_client)

        with patch.object(helper, "get_repository_methods") as mock_get_methods, patch.object(
            helper, "_get_existing_repository", return_value=None
        ), patch.object(helper, "_create_new_repository", return_value=("test-prn", "test-href")), patch.object(
            helper, "_create_distribution_task", return_value="task-123"
        ), patch.object(
            helper, "_wait_for_distribution_task"
        ):

            mock_get_methods.return_value = {}

            prn, href = helper._create_or_get_repository_impl("test-build", "rpms")

        assert prn == "test-prn"
        assert href == "test-href"

    def test_create_or_get_repository_impl_existing(self, mock_pulp_client):
        """Test PulpHelper _create_or_get_repository_impl with existing repository."""
        helper = PulpHelper(mock_pulp_client)

        with patch.object(helper, "get_repository_methods") as mock_get_methods, patch.object(
            helper, "_get_existing_repository", return_value=("test-prn", "test-href")
        ), patch.object(helper, "_create_distribution_task", return_value="task-123"), patch.object(
            helper, "_wait_for_distribution_task"
        ):

            mock_get_methods.return_value = {}

            prn, href = helper._create_or_get_repository_impl("test-build", "rpms")

        assert prn == "test-prn"
        assert href == "test-href"

    def test_create_or_get_repository_impl_no_task(self, mock_pulp_client):
        """Test PulpHelper _create_or_get_repository_impl with no distribution task."""
        helper = PulpHelper(mock_pulp_client)

        with patch.object(helper, "get_repository_methods") as mock_get_methods, patch.object(
            helper, "_get_existing_repository", return_value=("test-prn", "test-href")
        ), patch.object(helper, "_create_distribution_task", return_value=None):

            mock_get_methods.return_value = {}

            prn, href = helper._create_or_get_repository_impl("test-build", "rpms")

        assert prn == "test-prn"
        assert href == "test-href"
