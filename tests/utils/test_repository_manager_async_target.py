"""Tests for RepositoryManager class."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import httpx
import pytest

from pulp_tool.exceptions import PulpToolHTTPError
from pulp_tool.models.pulp_api import RpmRepositoryRequest, TaskResponse
from pulp_tool.utils.repository_manager import RepositoryApiOps, RepositoryManager, _resource_log_label


def _create_or_get_repository_side_effect(
    new_repository: object,
    *_args: object,
    **_kwargs: object,
) -> tuple[str, str | None]:
    """Mock _create_or_get_repository_impl by repo name suffix (concurrency-safe)."""
    name = getattr(new_repository, "name", "")
    repo_type = name.rsplit("/", 1)[-1]
    href = f"{repo_type}-href" if repo_type in ("rpms", "rpms-signed") else None
    return (f"{repo_type}-prn", href)


class TestRepositoryManagerCreateNewRepository:
    """Tests for RepositoryManager._create_new_repository() method."""

    def test_create_new_repository_wrapped_results(self) -> None:
        """Test _create_new_repository with wrapped results (lines 204, 206-210)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        mock_client.check_response = Mock()
        manager = RepositoryManager(mock_client)
        mock_response = Mock()
        mock_response.json.return_value = {"results": [{"prn": "test-prn", "pulp_href": "test-href"}]}
        methods = cast(RepositoryApiOps, SimpleNamespace(create=Mock(return_value=mock_response)))
        new_repo = RpmRepositoryRequest(name="test-build/rpms")
        prn, href = manager._create_new_repository(methods, new_repo, "rpms")
        assert prn == "test-prn"
        assert href == "test-href"

    def test_create_new_repository_wrapped_results_file_api(self) -> None:
        """Test _create_new_repository with wrapped results use file api_type."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        mock_client.check_response = Mock()
        manager = RepositoryManager(mock_client)
        mock_response = Mock()
        mock_response.json.return_value = {"results": [{"prn": "test-prn", "pulp_href": "test-href"}]}
        methods = cast(RepositoryApiOps, SimpleNamespace(create=Mock(return_value=mock_response)))
        new_repo = RpmRepositoryRequest(name="test-build/rpms")
        prn, href = manager._create_new_repository(methods, new_repo, "file")
        assert prn == "test-prn"
        assert href == "test-href"

    def test_create_new_repository_wrapped_results_empty(self) -> None:
        """Test _create_new_repository with empty results list (lines 207-208)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        mock_client.check_response = Mock()
        manager = RepositoryManager(mock_client)
        mock_response = Mock()
        mock_response.json.return_value = {"results": []}
        methods = cast(RepositoryApiOps, SimpleNamespace(create=Mock(return_value=mock_response)))
        new_repo = RpmRepositoryRequest(name="test-build/rpms")
        with pytest.raises(ValueError) as exc_info:
            manager._create_new_repository(methods, new_repo, "rpms")
        assert "No rpms repository found after creation" in str(exc_info.value)

    def test_create_new_repository_uniqueness_conflict(self) -> None:
        """Test _create_new_repository uses existing repo when create returns HTTP 400 unique name."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        conflict_response = Mock()
        conflict_response.status_code = 400
        conflict_response.text = '{"name":["This field must be unique."]}'

        def check_response(_response: object, msg: str) -> None:
            if "create" in msg:
                raise PulpToolHTTPError("Failed to create resource", response=conflict_response)

        mock_client.check_response = check_response
        existing_response = Mock()
        existing_response.status_code = 200
        existing_response.json.return_value = {
            "results": [{"prn": "existing-prn", "pulp_href": "existing-href"}],
        }
        methods = cast(
            RepositoryApiOps,
            SimpleNamespace(
                create=Mock(return_value=Mock()),
                get=Mock(return_value=existing_response),
            ),
        )
        new_repo = RpmRepositoryRequest(name="test-build/logs")
        prn, href = manager._create_new_repository(methods, new_repo, "logs")
        assert prn == "existing-prn"
        assert href == "existing-href"

    def test_create_new_repository_uniqueness_conflict_reraises_when_not_found(self) -> None:
        """HTTP 400 unique name with no matching repo re-raises the create error."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        conflict_response = Mock()
        conflict_response.status_code = 400
        conflict_response.text = '{"name":["This field must be unique."]}'

        def check_response(_response: object, msg: str) -> None:
            if "create" in msg:
                raise PulpToolHTTPError("Failed to create resource", response=conflict_response)

        mock_client.check_response = check_response
        missing_response = Mock()
        missing_response.status_code = 404
        methods = cast(
            RepositoryApiOps,
            SimpleNamespace(
                create=Mock(return_value=Mock()),
                get=Mock(return_value=missing_response),
            ),
        )
        new_repo = RpmRepositoryRequest(name="test-build/logs")
        with pytest.raises(PulpToolHTTPError, match="Failed to create resource"):
            manager._create_new_repository(methods, new_repo, "logs")

    def test_create_new_repository_unexpected_format(self) -> None:
        """Test _create_new_repository with unexpected response format (line 212)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        mock_client.check_response = Mock()
        manager = RepositoryManager(mock_client)
        mock_response = Mock()
        mock_response.json.return_value = {"unexpected": "format"}
        methods = cast(RepositoryApiOps, SimpleNamespace(create=Mock(return_value=mock_response)))
        new_repo = RpmRepositoryRequest(name="test-build/rpms")
        with pytest.raises(ValueError) as exc_info:
            manager._create_new_repository(methods, new_repo, "rpms")
        assert "Unexpected response format" in str(exc_info.value)


class TestRepositoryManagerWaitForDistributionTask:
    """Tests for RepositoryManager._wait_for_distribution_task() method."""

    def test_wait_for_distribution_task_exception_handling(self) -> None:
        """Test _wait_for_distribution_task exception handling (lines 256-257)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        mock_client.config = {"base_url": "https://pulp.example.com"}
        mock_client.session = Mock()
        mock_client.timeout = 30
        mock_client.request_params = {}
        manager = RepositoryManager(mock_client)
        mock_task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/api/v3/distributions/rpm/123/"]
        )
        methods = cast(RepositoryApiOps, SimpleNamespace(wait_for_finished_task=Mock(return_value=mock_task_response)))
        mock_client.session.get.side_effect = httpx.HTTPError("Connection error")
        with patch("pulp_tool.utils.repository_manager.logging") as mock_logging:
            base_path = manager._wait_for_distribution_task(methods, "task-123", "rpms", "test-build")
            mock_logging.warning.assert_called()
            assert base_path is None


class TestRepositoryManagerSetupRepositoriesAsync:
    """Tests for RepositoryManager._setup_repositories_impl_async() method."""

    def test_setup_repositories_impl_async_success(self) -> None:
        """Test _setup_repositories_impl_async creates repositories (lines 276-301)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl") as mock_create:
            mock_create.side_effect = _create_or_get_repository_side_effect
            result = asyncio.run(manager._setup_repositories_impl_async("test-build"))
            assert result["rpms_prn"] == "rpms-prn"
            assert result["rpms_href"] == "rpms-href"
            assert result["logs_prn"] == "logs-prn"
            assert result["sbom_prn"] == "sbom-prn"
            assert result["artifacts_prn"] == "artifacts-prn"
            assert "logs_href" not in result

    def test_setup_repositories_impl_async_skip_artifacts_repo(self) -> None:
        """Test _setup_repositories_impl_async with skip_artifacts_repo excludes artifacts."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl") as mock_create:
            mock_create.side_effect = _create_or_get_repository_side_effect
            result = asyncio.run(manager._setup_repositories_impl_async("test-build", skip_artifacts_repo=True))
            assert mock_create.call_count == 3
            assert "artifacts_prn" not in result

    def test_setup_repositories_impl_async_with_signed_by(self) -> None:
        """Test _setup_repositories_impl_async with signed_by creates signed RPM repo only (line 365)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl") as mock_create:
            mock_create.side_effect = _create_or_get_repository_side_effect
            result = asyncio.run(manager._setup_repositories_impl_async("test-build", signed_by="key-123"))
            assert mock_create.call_count == 5
            assert result["rpms_signed_prn"] == "rpms-signed-prn"
            assert result["rpms_signed_href"] == "rpms-signed-href"

    def test_setup_repositories_impl_async_http_error_403(self) -> None:
        """Test _setup_repositories_impl_async with 403 HTTP error (lines 303, 305-307)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl", side_effect=httpx.HTTPError("403 Forbidden")):
            import asyncio

            with pytest.raises(httpx.HTTPError):
                asyncio.run(manager._setup_repositories_impl_async("test-build"))

    def test_setup_repositories_impl_async_http_error_401(self) -> None:
        """Test _setup_repositories_impl_async with 401 HTTP error (lines 311-312)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl", side_effect=httpx.HTTPError("401 Unauthorized")):
            import asyncio

            with pytest.raises(httpx.HTTPError):
                asyncio.run(manager._setup_repositories_impl_async("test-build"))

    def test_setup_repositories_impl_async_generic_exception(self) -> None:
        """Test _setup_repositories_impl_async with generic exception (lines 319-322)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl", side_effect=ValueError("Generic error")):
            import asyncio

            with pytest.raises(ValueError):
                asyncio.run(manager._setup_repositories_impl_async("test-build"))

    def test_setup_repositories_impl_calls_async(self) -> None:
        """Test _setup_repositories_impl calls async version (line 453)."""
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
        with patch.object(manager, "_setup_repositories_impl_async", return_value=mock_repositories) as mock_async:
            result = manager._setup_repositories_impl("test-build")
            mock_async.assert_called_once_with(
                "test-build",
                signed_by=None,
                skip_artifacts_repo=False,
                target_arch_repo=False,
                skip_logs_repo=False,
                skip_sbom_repo=False,
            )
            assert result == mock_repositories


class TestRepositoryManagerCheckExistingDistribution:
    """Tests for RepositoryManager._check_existing_distribution() method."""

    def test_check_existing_distribution_attribute_error(self) -> None:
        """Test _check_existing_distribution handles AttributeError (lines 380-381)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        mock_response = Mock()
        del mock_response.status_code
        mock_methods = cast(RepositoryApiOps, SimpleNamespace(get_distro=Mock(return_value=mock_response)))
        with patch("pulp_tool.utils.repository_manager.logging") as mock_logging:
            result = manager._check_existing_distribution(mock_methods, "test-build/rpms", "rpms")
            assert result is False
            debug_calls = [call[0][0] if call[0] else "" for call in mock_logging.debug.call_args_list]
            assert any("Distribution check method not available" in str(call) for call in debug_calls)


def test_resource_log_label_empty_string() -> None:
    """_resource_log_label returns empty string unchanged (early return)."""
    assert _resource_log_label("") == ""


class TestRepositoryManagerTargetArchRepo:
    """Per-architecture RPM repository setup and ensure helpers."""

    def test_setup_repositories_target_arch_repo_no_bulk_rpms(self) -> None:
        """target_arch_repo skips rpms keys; validation does not require rpms_href."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        mock_repositories = {
            "logs_prn": "test-logs-prn",
            "sbom_prn": "test-sbom-prn",
            "artifacts_prn": "test-artifacts-prn",
        }
        with (
            patch.object(manager, "_setup_repositories_impl", return_value=mock_repositories),
            patch("pulp_tool.utils.repository_manager.validate_repository_setup", return_value=(True, [])),
        ):
            result = manager.setup_repositories("test-build", target_arch_repo=True)
        assert result.rpms_href == ""
        assert result.rpms_prn == ""

    def test_ensure_rpm_repository_for_arch(self) -> None:
        """ensure_rpm_repository_for_arch creates arch-named repo and returns href."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl", return_value=("prn-1", "/rpm/href/")) as mock_impl:
            href = manager.ensure_rpm_repository_for_arch("test-build", "x86_64")
        assert href == "/rpm/href/"
        req = mock_impl.call_args[0][0]
        assert req.name == "x86_64"
        assert mock_impl.call_args[0][2] == "rpm"
        assert mock_impl.call_args.kwargs.get("build_id") == "test-build"
        assert mock_impl.call_args.kwargs.get("distribution_cache_type") == "rpm_arch:x86_64"

    def test_ensure_rpm_repository_for_arch_second_arch_same_pattern(self) -> None:
        """Another arch uses the same naming pattern (no rpms-signed suffix)."""
        mock_client = Mock()
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl", return_value=("prn-1", "/rpm/s/")) as mock_impl:
            href = manager.ensure_rpm_repository_for_arch("test-build", "aarch64")
        assert href == "/rpm/s/"
        req = mock_impl.call_args[0][0]
        assert req.name == "aarch64"
        assert mock_impl.call_args.kwargs.get("build_id") == "test-build"
        assert mock_impl.call_args.kwargs.get("distribution_cache_type") == "rpm_arch:aarch64"

    def test_ensure_rpm_repository_for_arch_rejects_unsupported_arch(self) -> None:
        """Whitespace-only or unknown arch is not in SUPPORTED_ARCHITECTURES."""
        mock_client = Mock()
        manager = RepositoryManager(mock_client)
        with pytest.raises(ValueError, match="Unsupported architecture"):
            manager.ensure_rpm_repository_for_arch("test-build", "   ")
        with pytest.raises(ValueError, match="Unsupported architecture"):
            manager.ensure_rpm_repository_for_arch("test-build", "bogus")

    def test_ensure_rpm_repository_for_arch_rejects_invalid_build_id(self) -> None:
        """Invalid or unsanitizable build_id raises ValueError."""
        mock_client = Mock()
        manager = RepositoryManager(mock_client)
        with pytest.raises(ValueError, match="Invalid build ID"):
            manager.ensure_rpm_repository_for_arch("", "x86_64")
        with (
            patch("pulp_tool.utils.repository_manager.sanitize_build_id_for_repository", return_value="bad"),
            patch("pulp_tool.utils.repository_manager.validate_build_id", return_value=False),
        ):
            with pytest.raises(ValueError, match="Invalid build ID"):
                manager.ensure_rpm_repository_for_arch("raw", "x86_64")

    def test_ensure_rpm_repository_for_arch_empty_distribution_base_path(self) -> None:
        """Defensive check when DistributionRequest has empty base_path."""
        mock_client = Mock()
        manager = RepositoryManager(mock_client)
        mock_dist = Mock()
        mock_dist.base_path = ""
        with patch.object(manager, "_validate_full_name"):
            with patch("pulp_tool.utils.repository_manager.RepositoryRequest", return_value=Mock()):
                with patch("pulp_tool.utils.repository_manager.DistributionRequest", return_value=mock_dist):
                    with pytest.raises(ValueError, match="Invalid distribution base_path"):
                        manager.ensure_rpm_repository_for_arch("test-build", "x86_64")

    def test_ensure_rpm_repository_for_arch_raises_when_no_href(self) -> None:
        """RPM create path without href raises RuntimeError."""
        mock_client = Mock()
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl", return_value=("prn", None)):
            with pytest.raises(RuntimeError, match="No repository href"):
                manager.ensure_rpm_repository_for_arch("test-build", "ppc64le")

    def test_setup_repositories_impl_async_target_arch_repo_excludes_rpm_repos(self) -> None:
        """Async setup does not create rpms or rpms-signed when target_arch_repo is set."""
        from pulp_tool.api import PulpClient

        mock_client = Mock(spec=PulpClient)
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl", return_value=("p", "h")):
            result = asyncio.run(
                manager._setup_repositories_impl_async(
                    "my-build", signed_by="key", skip_artifacts_repo=False, target_arch_repo=True
                )
            )
        assert "rpms_prn" not in result
        assert "rpms_signed_prn" not in result
        assert "logs_prn" in result

    def test_setup_repositories_impl_async_skips_logs_and_sbom_when_flags(self) -> None:
        """Async setup omits logs and sbom repos when skip flags set."""
        from pulp_tool.api import PulpClient

        mock_client = Mock(spec=PulpClient)
        mock_client.namespace = "test-namespace"
        manager = RepositoryManager(mock_client)
        with patch.object(manager, "_create_or_get_repository_impl", return_value=("p", None)) as mock_create:
            result = asyncio.run(
                manager._setup_repositories_impl_async(
                    "my-build",
                    signed_by=None,
                    skip_artifacts_repo=False,
                    target_arch_repo=False,
                    skip_logs_repo=True,
                    skip_sbom_repo=True,
                )
            )
        assert "logs_prn" not in result
        assert "sbom_prn" not in result
        assert "rpms_prn" in result
        assert "artifacts_prn" in result
        assert mock_create.call_count == 2
