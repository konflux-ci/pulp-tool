"""Tests for RepositoryManager class."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, call, patch

import httpx
import pytest

from pulp_tool.models.pulp_api import DistributionRequest, RepositoryRequest, TaskResponse
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.utils.repository_manager import RepositoryApiOps, RepositoryManager


class TestRepositoryApiOps:
    """``RepositoryApiOps`` forwards to :meth:`PulpClient.repository_operation` / task wait."""

    def test_delegates_to_client(self) -> None:
        mock_client = Mock()
        mock_resp = httpx.Response(200, json={})
        mock_client.repository_operation = Mock(return_value=mock_resp)
        task_done = TaskResponse(pulp_href="/tasks/1/", state="completed")
        mock_client.wait_for_finished_task = Mock(return_value=task_done)
        ops = RepositoryApiOps(mock_client, "rpm")
        repo = RepositoryRequest(name="r", autopublish=True)
        dist = DistributionRequest(name="d", base_path="d")
        assert ops.get("n1") is mock_resp
        assert ops.create(repo) is mock_resp
        assert ops.distro(dist) is mock_resp
        assert ops.get_distro("n2") is mock_resp
        assert ops.update_distro("/dist/href", "pub") is mock_resp
        assert ops.wait_for_finished_task("/tasks/wait/") is task_done
        mock_client.repository_operation.assert_has_calls(
            [
                call("get_repo", "rpm", name="n1"),
                call("create_repo", "rpm", repository_data=repo),
                call("create_distro", "rpm", distribution_data=dist),
                call("get_distro", "rpm", name="n2"),
                call("update_distro", "rpm", distribution_href="/dist/href", publication="pub"),
            ]
        )
        mock_client.wait_for_finished_task.assert_called_once_with("/tasks/wait/")


class TestRepositoryManagerSetupRepositories:
    """Tests for RepositoryManager.setup_repositories() method."""

    def test_setup_repositories_invalid_after_sanitization(self) -> None:
        """Test setup_repositories raises ValueError when sanitized build_id is invalid (line 72)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with (
            patch("pulp_tool.utils.repository_manager.sanitize_build_id_for_repository", return_value="invalid build"),
            patch("pulp_tool.utils.repository_manager.validate_build_id", return_value=False),
        ):
            with pytest.raises(ValueError) as exc_info:
                manager.setup_repositories("test-build")
            assert "Invalid build ID" in str(exc_info.value)
            assert "sanitized:" in str(exc_info.value)

    def test_setup_repositories_success(self) -> None:
        """Test setup_repositories successfully creates repositories."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        mock_repositories = {
            "rpms_prn": "test-rpms-prn",
            "rpms_href": "test-rpms-href",
            "logs_prn": "test-logs-prn",
            "sbom_prn": "test-sbom-prn",
            "artifacts_prn": "test-artifacts-prn",
        }
        with (
            patch.object(manager, "_setup_repositories_impl", return_value=mock_repositories),
            patch("pulp_tool.utils.repository_manager.validate_repository_setup", return_value=(True, [])),
        ):
            result = manager.setup_repositories("test-build")
            assert isinstance(result, RepositoryRefs)
            assert result.rpms_prn == "test-rpms-prn"
            assert result.rpms_href == "test-rpms-href"


class TestRepositoryManagerCreateOrGetRepository:
    """Tests for RepositoryManager.create_or_get_repository() method."""

    def test_create_or_get_repository_invalid_after_sanitization(self) -> None:
        """Test create_or_get_repository raises ValueError when sanitized build_id is invalid (line 127)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with (
            patch("pulp_tool.utils.repository_manager.sanitize_build_id_for_repository", return_value="invalid build"),
            patch("pulp_tool.utils.repository_manager.validate_build_id", return_value=False),
        ):
            with pytest.raises(ValueError) as exc_info:
                manager.create_or_get_repository("test-build", "rpms")
            assert "Invalid build ID" in str(exc_info.value)
            assert "sanitized:" in str(exc_info.value)

    def test_create_or_get_repository_empty_build_name(self) -> None:
        """Test create_or_get_repository raises ValueError when build_name is empty (line 160)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value=""):
            with pytest.raises(ValueError, match="Empty build_name"):
                manager.create_or_get_repository("test-build", "rpms")

    def test_create_or_get_repository_invalid_full_name_empty(self) -> None:
        """Test create_or_get_repository raises ValueError when full_name is empty (line 163)."""
        from pulp_tool.api import PulpClient
        from pulp_tool.utils.repository_manager import RepositoryManager

        mock_client = Mock(spec=PulpClient)
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value=""):
            with pytest.raises(ValueError, match="Empty build_name"):
                manager.create_or_get_repository("test-build", "rpms")

    def test_create_or_get_repository_invalid_full_name_whitespace(self) -> None:
        """Test create_or_get_repository raises ValueError when build_name is whitespace (line 160)."""
        from pulp_tool.api import PulpClient
        from pulp_tool.utils.repository_manager import RepositoryManager

        mock_client = Mock(spec=PulpClient)
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value="   "):
            with pytest.raises(ValueError, match="Empty build_name"):
                manager.create_or_get_repository("test-build", "rpms")

    def test_create_or_get_repository_invalid_full_name(self) -> None:
        """Test create_or_get_repository raises ValueError when full_name is invalid."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        mock_client.repository_operation = Mock(return_value=Mock(status_code=404))
        mock_client.check_response = Mock()
        manager = RepositoryManager(mock_client)
        with pytest.raises(ValueError, match="Invalid full_name"):
            manager._validate_full_name("", "test", "rpms")
        with pytest.raises(ValueError, match="Invalid full_name"):
            manager._validate_full_name("   ", "test", "rpms")

        def mock_validate_full_name(full_name, build_name, repo_type) -> None:
            """Mock that raises ValueError to test the error path."""
            raise ValueError(f"Invalid full_name constructed: build_name={build_name}, repo_type={repo_type}")

        with (
            patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value="test"),
            patch.object(manager, "_validate_full_name", side_effect=mock_validate_full_name),
        ):
            with pytest.raises(ValueError, match="Invalid full_name"):
                manager.create_or_get_repository("test-build", "rpms")

    def test_create_or_get_repository_empty_base_path(self) -> None:
        """Test create_or_get_repository raises ValueError when base_path is empty (line 170)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with (
            patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value="test-build"),
            patch("pulp_tool.utils.repository_manager.DistributionRequest") as mock_dist_req,
        ):
            mock_dist = Mock()
            mock_dist.base_path = ""
            mock_dist_req.return_value = mock_dist
            with pytest.raises(ValueError, match="base_path is empty"):
                manager.create_or_get_repository("test-build", "rpms")

    def test_get_existing_repository_404(self) -> None:
        """Test _get_existing_repository handles 404 gracefully (line 230)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        mock_client.check_response = Mock()
        manager = RepositoryManager(mock_client)
        mock_response = Mock()
        mock_response.status_code = 404
        methods = cast(RepositoryApiOps, SimpleNamespace(get=Mock(return_value=mock_response)))
        with patch("pulp_tool.utils.repository_manager.logging") as mock_logging:
            result = manager._get_existing_repository(methods, "test-repo", "rpms")
            assert result is None
            mock_logging.debug.assert_called()

    def test_setup_repositories_impl_async_empty_build_name(self) -> None:
        """Test _setup_repositories_impl_async raises ValueError when build_name is empty (line 344)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value=""):
            import asyncio

            async def run_test() -> None:
                with pytest.raises(ValueError, match="Empty build_name"):
                    await manager._setup_repositories_impl_async("test-build")

            asyncio.run(run_test())

    def test_setup_repositories_impl_async_invalid_full_name_empty(self) -> None:
        """Test _setup_repositories_impl_async raises ValueError when full_name is empty (line 347)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value=""):
            import asyncio

            with pytest.raises(ValueError, match="Empty build_name"):
                asyncio.run(manager._setup_repositories_impl_async("test-build"))

    def test_setup_repositories_impl_async_invalid_full_name_whitespace(self) -> None:
        """Test _setup_repositories_impl_async raises ValueError when build_name is whitespace (line 344)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value="   "):
            import asyncio

            with pytest.raises(ValueError, match="Empty build_name"):
                asyncio.run(manager._setup_repositories_impl_async("test-build"))

    def test_setup_repositories_impl_async_invalid_full_name(self) -> None:
        """Test _setup_repositories_impl_async raises ValueError when full_name is invalid."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        mock_client.repository_operation = Mock(return_value=Mock(status_code=404))
        mock_client.check_response = Mock()
        mock_client.wait_for_finished_task = Mock()
        manager = RepositoryManager(mock_client)
        with pytest.raises(ValueError, match="Invalid full_name"):
            manager._validate_full_name("", "test", "rpms")
        with pytest.raises(ValueError, match="Invalid full_name"):
            manager._validate_full_name("   ", "test", "rpms")

        def mock_validate_full_name(full_name, build_name, repo_type) -> None:
            """Mock that raises ValueError to test the error path."""
            raise ValueError(f"Invalid full_name constructed: build_name={build_name}, repo_type={repo_type}")

        with (
            patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value="test"),
            patch.object(manager, "_validate_full_name", side_effect=mock_validate_full_name),
        ):
            import asyncio

            with pytest.raises(ValueError, match="Invalid full_name"):
                asyncio.run(manager._setup_repositories_impl_async("test-build"))

    def test_setup_repositories_impl_async_empty_base_path(self) -> None:
        """Test _setup_repositories_impl_async raises ValueError when base_path is empty (line 352)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with (
            patch("pulp_tool.utils.repository_manager.strip_namespace_from_build_id", return_value="test-build"),
            patch("pulp_tool.utils.repository_manager.DistributionRequest") as mock_dist_req,
        ):
            mock_dist = Mock()
            mock_dist.base_path = ""
            mock_dist_req.return_value = mock_dist
            import asyncio

            async def run_test() -> None:
                with pytest.raises(ValueError, match="base_path is empty"):
                    await manager._setup_repositories_impl_async("test-build")

            asyncio.run(run_test())

    def test_create_or_get_repository_impl_empty_base_path_after_repo_set(self) -> None:
        """Test _create_or_get_repository_impl raises ValueError when base_path is empty."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        from pulp_tool.models.pulp_api import DistributionRequest, RepositoryRequest

        new_repo = RepositoryRequest(name="test-repo", autopublish=True)
        new_distro = DistributionRequest(name="test-repo", base_path="test-repo")
        new_distro.repository = "test-prn"
        new_distro.base_path = ""
        manager._parse_repository_response = Mock(return_value={"prn": "test-prn", "pulp_href": "/repo/123/"})
        manager._create_distribution_task = Mock(return_value=None)
        manager._wait_for_distribution_task = Mock(return_value="test-repo")
        with pytest.raises(ValueError, match="base_path is empty before creating"):
            manager._create_or_get_repository_impl(new_repo, new_distro, "rpms")

    def test_check_existing_distribution_404(self) -> None:
        """Test _check_existing_distribution handles 404 gracefully (line 465)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        mock_client.check_response = Mock()
        manager = RepositoryManager(mock_client)
        mock_response = Mock()
        mock_response.status_code = 404
        methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        with patch("pulp_tool.utils.repository_manager.logging") as mock_logging:
            result = manager._check_existing_distribution(methods, "test-distro", "rpms")
            assert result is False
            mock_logging.debug.assert_called()

    def test_create_distribution_task_empty_base_path(self) -> None:
        """Test _create_distribution_task raises ValueError when base_path is empty (line 535)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        from pulp_tool.models.pulp_api import DistributionRequest

        new_distro = DistributionRequest(name="test-distro", base_path="test-distro")
        object.__setattr__(new_distro, "base_path", "")
        methods = cast(RepositoryApiOps, SimpleNamespace(distro=Mock()))
        with (
            patch("pulp_tool.utils.repository_manager.logging") as mock_logging,
            pytest.raises(ValueError, match="Invalid base_path"),
        ):
            manager._create_distribution_task(methods, new_distro, "rpms", "test-build")
            mock_logging.error.assert_called()
