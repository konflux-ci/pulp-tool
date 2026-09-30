"""
Tests for pulp_tool.pull module (download and extract).
"""

from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

from pulp_tool.models.artifacts import ArtifactFile
from pulp_tool.pull import download_artifacts_concurrently
from pulp_tool.pull.reporting import _extract_artifact_info


class TestDownloadArtifactsConcurrently:
    """Test download_artifacts_concurrently function."""

    def test_download_artifacts_concurrently_success(self, tmp_path) -> None:
        """Test successful concurrent downloads (lines 219-220, 222, 228-232, 235, 238-239, 241, 244, 246-252, 254)."""
        import concurrent.futures
        from concurrent.futures import Future

        artifacts = {
            "test.rpm": {
                "pulp_labels": {"build_id": "test-build", "arch": "x86_64"},
                "url": "https://example.com/rpms/Packages/t/test.rpm",
            },
            "test.sbom": {
                "pulp_labels": {"build_id": "test-build", "arch": "noarch"},
                "url": "https://example.com/sbom/test.sbom",
            },
            "test.log": {
                "pulp_labels": {"build_id": "test-build", "arch": "noarch"},
                "url": "https://example.com/logs/test.log",
            },
        }
        distros = {
            "rpms": "https://example.com/rpms/",
            "sbom": "https://example.com/sbom/",
            "logs": "https://example.com/logs/",
        }
        mock_client = Mock()
        future1: Future[tuple[str, str]] = Future()
        future2: Future[tuple[str, str]] = Future()
        future3: Future[tuple[str, str]] = Future()
        future1.set_result(("test.rpm", str(tmp_path / "test.rpm")))
        future2.set_result(("test.sbom", str(tmp_path / "test.sbom")))
        future3.set_result(("test.log", str(tmp_path / "test.log")))
        (tmp_path / "test.rpm").write_text("rpm content")
        (tmp_path / "test.sbom").write_text("sbom content")
        (tmp_path / "test.log").write_text("log content")
        with (
            patch.object(concurrent.futures, "ThreadPoolExecutor") as mock_executor_class,
            patch.object(concurrent.futures, "as_completed") as mock_as_completed,
        ):
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_executor_class.return_value.__exit__.return_value = None
            mock_executor.submit.side_effect = [future1, future2, future3]
            mock_as_completed.return_value = [future1, future2, future3]
            result = download_artifacts_concurrently(artifacts, distros, mock_client, max_workers=4)
            assert result.completed == 3
            assert result.failed == 0
            assert len(result.pulled_artifacts.rpms) == 1
            assert len(result.pulled_artifacts.sboms) == 1
            assert len(result.pulled_artifacts.logs) == 1

    def test_download_artifacts_concurrently_with_dict_labels(self, tmp_path) -> None:
        """Test download with dict-based artifact labels (lines 241)."""
        import concurrent.futures
        from concurrent.futures import Future

        artifacts = {
            "test.rpm": {
                "pulp_labels": {"build_id": "test-build"},
                "url": "https://example.com/rpms/Packages/t/test.rpm",
            }
        }
        distros = {"rpms": "https://example.com/rpms/"}
        mock_client = Mock()
        future1: Future[tuple[str, str]] = Future()
        future1.set_result(("test.rpm", str(tmp_path / "test.rpm")))
        (tmp_path / "test.rpm").write_text("rpm content")
        with (
            patch.object(concurrent.futures, "ThreadPoolExecutor") as mock_executor_class,
            patch.object(concurrent.futures, "as_completed") as mock_as_completed,
        ):
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_executor_class.return_value.__exit__.return_value = None
            mock_executor.submit.return_value = future1
            mock_as_completed.return_value = [future1]
            result = download_artifacts_concurrently(artifacts, distros, mock_client, max_workers=4)
            assert result.completed == 1
            assert "test.rpm" in result.pulled_artifacts.rpms

    def test_download_artifacts_concurrently_with_artifact_metadata(self, tmp_path) -> None:
        """Test download with ArtifactMetadata instances (lines 238-239)."""
        import concurrent.futures
        from concurrent.futures import Future

        from pulp_tool.models.artifacts import ArtifactMetadata

        artifacts = {
            "test.rpm": ArtifactMetadata(
                pulp_labels={"build_id": "test-build", "arch": "x86_64"},
                url="https://example.com/rpms/Packages/t/test.rpm",
            )
        }
        distros = {"rpms": "https://example.com/rpms/"}
        mock_client = Mock()
        future1: Future[tuple[str, str]] = Future()
        future1.set_result(("test.rpm", str(tmp_path / "test.rpm")))
        (tmp_path / "test.rpm").write_text("rpm content")
        with (
            patch.object(concurrent.futures, "ThreadPoolExecutor") as mock_executor_class,
            patch.object(concurrent.futures, "as_completed") as mock_as_completed,
        ):
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_executor_class.return_value.__exit__.return_value = None
            mock_executor.submit.return_value = future1
            mock_as_completed.return_value = [future1]
            result = download_artifacts_concurrently(artifacts, distros, mock_client, max_workers=4)
            assert result.completed == 1
            assert "test.rpm" in result.pulled_artifacts.rpms

    def test_download_artifacts_concurrently_with_httpx_error(self, tmp_path) -> None:
        """Test download handles httpx.HTTPError exceptions (lines 256-260)."""
        import concurrent.futures
        from concurrent.futures import Future

        artifacts = {
            "test.rpm": {
                "pulp_labels": {"build_id": "test-build"},
                "url": "https://example.com/rpms/Packages/t/test.rpm",
            },
            "test2.rpm": {
                "pulp_labels": {"build_id": "test-build"},
                "url": "https://example.com/rpms/Packages/t/test2.rpm",
            },
        }
        distros = {"rpms": "https://example.com/rpms/"}
        mock_client = Mock()
        future1: Future[tuple[str, str]] = Future()
        future2: Future[tuple[str, str]] = Future()
        future1.set_result(("test.rpm", str(tmp_path / "test.rpm")))
        future2.set_exception(httpx.HTTPError("Network error"))
        (tmp_path / "test.rpm").write_text("rpm content")
        with (
            patch.object(concurrent.futures, "ThreadPoolExecutor") as mock_executor_class,
            patch.object(concurrent.futures, "as_completed") as mock_as_completed,
        ):
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_executor_class.return_value.__exit__.return_value = None
            mock_executor.submit.side_effect = [future1, future2]
            mock_as_completed.return_value = [future1, future2]
            result = download_artifacts_concurrently(artifacts, distros, mock_client, max_workers=4)
            assert result.completed == 1
            assert result.failed == 1


class TestExtractArtifactInfo:
    """Test _extract_artifact_info function."""

    def test_extract_artifact_info_with_dict(self) -> None:
        """Test _extract_artifact_info with dict input."""
        artifact_data = {"file": "/path/to/file.rpm", "pulp_labels": {"build_id": "test-build", "arch": "x86_64"}}
        file_path, labels = _extract_artifact_info(artifact_data)
        assert file_path == "/path/to/file.rpm"
        assert labels == {"build_id": "test-build", "arch": "x86_64"}

    def test_extract_artifact_info_with_dict_no_labels(self) -> None:
        """Test _extract_artifact_info with dict input without labels."""
        artifact_data = {"file": "/path/to/file.rpm"}
        file_path, labels = _extract_artifact_info(artifact_data)
        assert file_path == "/path/to/file.rpm"
        assert labels == {}

    def test_extract_artifact_info_with_model(self) -> None:
        """Test _extract_artifact_info with model object."""
        artifact_data = ArtifactFile(file="/path/to/file.rpm", labels={"build_id": "test-build", "arch": "x86_64"})
        file_path, labels = _extract_artifact_info(artifact_data)
        assert file_path == "/path/to/file.rpm"
        assert labels == {"build_id": "test-build", "arch": "x86_64"}

    def test_extract_artifact_info_with_model_no_labels(self) -> None:
        """Test _extract_artifact_info with model object without labels."""

        class MockArtifact:
            file = "/path/to/file.rpm"

        artifact_data = MockArtifact()
        file_path, labels = _extract_artifact_info(artifact_data)
        assert file_path == "/path/to/file.rpm"
        assert labels == {}

    def test_extract_artifact_info_unexpected_type(self) -> None:
        """Test _extract_artifact_info raises ValueError for unexpected type."""
        artifact_data = 123
        with pytest.raises(ValueError, match="Unexpected artifact_data type"):
            _extract_artifact_info(artifact_data)
