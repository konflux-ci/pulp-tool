"""
Tests for pulp_tool.pull module (setup and load).
"""

import json
from unittest.mock import Mock, patch

import pytest

from pulp_tool.pull import load_and_validate_artifacts, setup_repositories_if_needed


class TestSetupRepositories:
    """Test setup_repositories_if_needed function."""

    def test_setup_repositories_adds_konflux_prefix(self, tmp_path, mock_config) -> None:
        """Test setup_repositories_if_needed adds konflux- prefix to domain."""
        from pulp_tool.models.context import PullContext

        config_file = tmp_path / "config.toml"
        config_file.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "test-domain"')
        args = PullContext(
            config=str(config_file), transfer_dest=str(config_file), build_id="test-build", namespace="test-namespace"
        )
        with (
            patch("pulp_tool.pull.download.PulpClient") as mock_client_class,
            patch("pulp_tool.pull.download.PulpHelper") as mock_helper_class,
            patch("pulp_tool.pull.download.logging") as mock_logging,
        ):
            mock_client = Mock()
            mock_client_class.create_from_config_file.return_value = mock_client
            mock_helper = Mock()
            mock_helper.setup_repositories.return_value = Mock()
            mock_helper_class.return_value = mock_helper
            setup_repositories_if_needed(args)
            mock_client_class.create_from_config_file.assert_called_once()
            call_args = mock_client_class.create_from_config_file.call_args
            kwargs = call_args[1] if isinstance(call_args, tuple) else call_args.kwargs
            assert kwargs["domain"] == "konflux-test-domain"
            mock_logging.debug.assert_called()

    def test_setup_repositories_preserves_existing_konflux_prefix(self, tmp_path, mock_config) -> None:
        """Test setup_repositories_if_needed preserves existing konflux- prefix."""
        from pulp_tool.models.context import PullContext

        config_file = tmp_path / "config.toml"
        config_file.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "konflux-test-domain"')
        args = PullContext(
            config=str(config_file), transfer_dest=str(config_file), build_id="test-build", namespace="test-namespace"
        )
        with (
            patch("pulp_tool.pull.download.PulpClient") as mock_client_class,
            patch("pulp_tool.pull.download.PulpHelper") as mock_helper_class,
            patch("pulp_tool.pull.download.logging") as mock_logging,
        ):
            mock_client = Mock()
            mock_client_class.create_from_config_file.return_value = mock_client
            mock_helper = Mock()
            mock_helper.setup_repositories.return_value = Mock()
            mock_helper_class.return_value = mock_helper
            setup_repositories_if_needed(args)
            call_args = mock_client_class.create_from_config_file.call_args
            kwargs = call_args[1] if isinstance(call_args, tuple) else call_args.kwargs
            assert kwargs["domain"] == "konflux-test-domain"
            mock_logging.debug.assert_called()

    def test_setup_repositories_with_artifact_json_parent_package(self, mock_config, temp_config_file) -> None:
        """Test setup_repositories_if_needed extracts parent_package from artifact_json (lines 113-114)."""
        args = Mock()
        args.config = temp_config_file
        args.transfer_dest = temp_config_file
        args.build_id = "test-build"
        artifact_json = {"parent_package": "test-package"}
        with (
            patch("pulp_tool.pull.download.PulpClient.create_from_config_file") as mock_create,
            patch("pulp_tool.pull.download.determine_build_id", return_value="test-build"),
            patch("pulp_tool.pull.download.extract_metadata_from_artifact_json") as mock_extract,
            patch("pulp_tool.pull.download.PulpHelper") as mock_helper,
        ):
            mock_client = Mock()
            mock_create.return_value = mock_client
            mock_helper_instance = Mock()
            mock_helper.return_value = mock_helper_instance
            mock_extract.return_value = "test-package"
            from pulp_tool.models.repository import RepositoryRefs

            mock_repos = RepositoryRefs(
                rpms_href="/test/",
                rpms_prn="",
                logs_href="",
                logs_prn="",
                sbom_href="",
                sbom_prn="",
                artifacts_href="",
                artifacts_prn="",
            )
            mock_helper_instance.setup_repositories.return_value = mock_repos
            result = setup_repositories_if_needed(args, artifact_json=artifact_json)
            assert result is not None
            assert result.client == mock_client
            mock_extract.assert_called_once_with(artifact_json, "parent_package")
            mock_helper.assert_called_once_with(mock_client, parent_package="test-package")


class TestLoadAndValidateArtifacts:
    """Test load_and_validate_artifacts function."""

    def test_load_and_validate_artifacts_no_location(self) -> None:
        """Test load_and_validate_artifacts exits when no artifact_location (lines 151-152)."""
        import sys

        args = Mock()
        args.artifact_location = None
        mock_client = Mock()
        with patch.object(sys, "exit", side_effect=SystemExit(1)) as mock_exit:
            with pytest.raises(SystemExit):
                load_and_validate_artifacts(args, mock_client)
            mock_exit.assert_called_once_with(1)

    def test_load_and_validate_artifacts_no_artifacts(self, temp_file) -> None:
        """Test load_and_validate_artifacts exits when no artifacts found (lines 157-161)."""
        import sys

        args = Mock()
        args.artifact_location = temp_file
        with open(temp_file, "w") as f:
            json.dump({"distributions": {}}, f)
        mock_client = Mock()
        with patch.object(sys, "exit", side_effect=SystemExit(1)) as mock_exit:
            with pytest.raises(SystemExit):
                load_and_validate_artifacts(args, mock_client)
            mock_exit.assert_called_once_with(1)

    def test_load_and_validate_artifacts_validation_fails_bad_url(self, temp_file) -> None:
        """Invalid artifact url exits with validation error."""
        import sys

        args = Mock()
        args.artifact_location = temp_file
        with open(temp_file, "w") as f:
            json.dump({"artifacts": {"a.rpm": {"labels": {}, "url": "ftp://example.com/a.rpm"}}}, f)
        mock_client = Mock()
        with patch.object(sys, "exit", side_effect=SystemExit(1)) as mock_exit, pytest.raises(SystemExit):
            load_and_validate_artifacts(args, mock_client)
        mock_exit.assert_called_once_with(1)

    def test_load_and_validate_artifacts_validation_fails_extra_top_level_key(self, temp_file) -> None:
        """Unknown top-level keys are rejected (strict document shape)."""
        import sys

        args = Mock()
        args.artifact_location = temp_file
        with open(temp_file, "w") as f:
            json.dump(
                {
                    "artifacts": {"a.rpm": {"labels": {}, "url": "https://example.com/a.rpm"}},
                    "build_id": "should-not-be-here",
                },
                f,
            )
        mock_client = Mock()
        with patch.object(sys, "exit", side_effect=SystemExit(1)) as mock_exit, pytest.raises(SystemExit):
            load_and_validate_artifacts(args, mock_client)
        mock_exit.assert_called_once_with(1)

    def test_load_and_validate_artifacts_converts_to_typed_models(self, temp_file) -> None:
        """Test load_and_validate_artifacts converts artifacts to typed models (lines 164, 166, 170)."""
        args = Mock()
        args.artifact_location = temp_file
        artifact_data = {
            "artifacts": {
                "test.rpm": {
                    "labels": {"build_id": "test-build", "arch": "x86_64"},
                    "url": "https://example.com/api/pulp-content/ns/build/rpms/Packages/t/test.rpm",
                    "sha256": "a" * 64,
                },
                "test.sbom": {
                    "labels": {"build_id": "test-build", "arch": "noarch"},
                    "url": "https://example.com/api/pulp-content/ns/build/sbom/test.sbom",
                },
            },
            "distributions": {"rpms": "https://example.com/rpms/", "sbom": "https://example.com/sbom/"},
        }
        with open(temp_file, "w") as f:
            json.dump(artifact_data, f)
        mock_client = Mock()
        result = load_and_validate_artifacts(args, mock_client)
        assert result.artifacts is not None
        assert len(result.artifacts) == 2
        assert "test.rpm" in result.artifacts
        assert "test.sbom" in result.artifacts
        from pulp_tool.models.artifacts import ArtifactMetadata

        assert isinstance(result.artifacts["test.rpm"], ArtifactMetadata)
        assert isinstance(result.artifacts["test.sbom"], ArtifactMetadata)
        from pulp_tool.models.artifacts import ArtifactJsonResponse

        assert isinstance(result.artifact_json, ArtifactJsonResponse)
