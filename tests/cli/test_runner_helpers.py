"""Tests for shared CLI runner helpers."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pulp_tool.cli.runner_helpers import (
    PullRunnerError,
    artifact_row_from_json,
    load_distribution_auth_from_config,
    oci_pull_tempdir,
    resolve_artifact_location_for_pull,
    resolve_pulp_api_base_url_for_remote,
    resolve_results_json_local_path,
    validate_remote_pull_auth,
)
from pulp_tool.models.artifacts import ArtifactMetadata
from pulp_tool.utils.results_json_io import ResultsJsonIOError


class TestResolveArtifactLocationForPull:
    def test_rejects_artifact_location_with_build_id(self) -> None:
        with pytest.raises(PullRunnerError, match="Cannot use --artifact-location"):
            resolve_artifact_location_for_pull(
                artifact_location="http://example/x.json",
                namespace="ns",
                build_id="b1",
                source_config_path=None,
                dest_config_path=None,
            )

    def test_requires_build_id_and_namespace_together(self) -> None:
        with pytest.raises(PullRunnerError, match="Both --build-id"):
            resolve_artifact_location_for_pull(
                artifact_location=None,
                namespace="ns",
                build_id=None,
                source_config_path="/tmp/x.toml",
                dest_config_path=None,
            )

    def test_builds_url_from_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "cli.toml"
        cfg.write_text('[cli]\nbase_url = "https://pulp.example.com"\n', encoding="utf-8")
        loc = resolve_artifact_location_for_pull(
            artifact_location=None,
            namespace="my-ns",
            build_id="my-build",
            source_config_path=str(cfg),
            dest_config_path=None,
        )
        assert "pulp.example.com" in loc
        assert "my-ns" in loc
        assert loc.endswith("pulp_results.json")

    def test_passes_through_local_path(self) -> None:
        loc = resolve_artifact_location_for_pull(
            artifact_location="/tmp/pulp_results.json",
            namespace=None,
            build_id=None,
            source_config_path=None,
            dest_config_path=None,
        )
        assert loc == "/tmp/pulp_results.json"

    @patch("pulp_tool.cli.runner_helpers.resolve_results_json_path")
    def test_oras_pull_with_oci_dest_dir(self, mock_resolve: object, tmp_path: Path) -> None:
        pulled = tmp_path / "pulp_results.json"
        mock_resolve.return_value = pulled  # type: ignore[attr-defined]
        loc = resolve_artifact_location_for_pull(
            artifact_location="quay.io/ns/repo@sha256:abc",
            namespace=None,
            build_id=None,
            source_config_path=None,
            dest_config_path=None,
            oci_dest_dir=tmp_path,
        )
        assert loc == str(pulled)

    def test_oras_pull_without_oci_dest_dir_raises(self) -> None:
        with pytest.raises(PullRunnerError, match="Internal error"):
            resolve_artifact_location_for_pull(
                artifact_location="quay.io/ns/repo@sha256:abc",
                namespace=None,
                build_id=None,
                source_config_path=None,
                dest_config_path=None,
                oci_dest_dir=None,
            )

    @patch("pulp_tool.cli.runner_helpers.resolve_results_json_path")
    def test_oras_pull_maps_results_json_io_error(self, mock_resolve: object, tmp_path: Path) -> None:
        mock_resolve.side_effect = ResultsJsonIOError("oras failed")  # type: ignore[attr-defined]
        with pytest.raises(PullRunnerError, match="oras failed"):
            resolve_artifact_location_for_pull(
                artifact_location="quay.io/ns/repo@sha256:abc",
                namespace=None,
                build_id=None,
                source_config_path=None,
                dest_config_path=None,
                oci_dest_dir=tmp_path,
            )


class TestDistributionAuth:
    def test_load_from_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "c.toml"
        cfg.write_text(
            '[cli]\nbase_url = "https://pulp.example.com"\nusername = "u"\npassword = "p"\n',
            encoding="utf-8",
        )
        auth = load_distribution_auth_from_config(auth_config_path=str(cfg))
        assert auth.username == "u"
        assert auth.password == "p"
        assert auth.pulp_api_base_url == "https://pulp.example.com"

    def test_validate_remote_requires_auth(self) -> None:
        from pulp_tool.cli.runner_helpers import DistributionAuthSettings

        auth = DistributionAuthSettings()
        with pytest.raises(PullRunnerError, match="Authentication required"):
            validate_remote_pull_auth("https://example.com/x.json", auth)

    def test_resolve_base_url_fallback(self, tmp_path: Path) -> None:
        from pulp_tool.cli.runner_helpers import DistributionAuthSettings

        cfg = tmp_path / "c.toml"
        cfg.write_text('[cli]\nbase_url = "https://fallback.example"\n', encoding="utf-8")
        auth = DistributionAuthSettings()
        updated = resolve_pulp_api_base_url_for_remote(
            artifact_location="https://remote/x.json",
            auth=auth,
            fallback_config_paths=(str(cfg),),
        )
        assert updated.pulp_api_base_url == "https://fallback.example"


class TestOciPullTempdir:
    def test_yields_path_and_cleans_up(self) -> None:
        seen: Path | None = None
        with oci_pull_tempdir() as path:
            seen = path
            assert path.is_dir()
        assert seen is not None
        assert not seen.exists()


class TestResolveResultsJsonLocalPath:
    def test_local_file(self, tmp_path: Path) -> None:
        j = tmp_path / "pulp_results.json"
        j.write_text('{"artifacts": {}}', encoding="utf-8")
        local, temp = resolve_results_json_local_path(str(j), oci_dest_dir=None)
        assert local == str(j.resolve())
        assert temp is None

    def test_missing_file_raises(self) -> None:
        with pytest.raises(PullRunnerError, match="not found"):
            resolve_results_json_local_path("/nonexistent/pulp_results.json", oci_dest_dir=None)

    @patch("pulp_tool.cli.runner_helpers.resolve_results_json_path")
    def test_oci_with_explicit_dest_dir(self, mock_resolve: object, tmp_path: Path) -> None:
        pulled = tmp_path / "pulp_results.json"
        mock_resolve.return_value = pulled  # type: ignore[attr-defined]
        local, temp = resolve_results_json_local_path(
            "quay.io/ns/repo@sha256:abc",
            oci_dest_dir=tmp_path,
        )
        assert local == str(pulled)
        assert temp is None

    @patch("pulp_tool.cli.runner_helpers.resolve_results_json_path")
    def test_oci_with_dest_dir_maps_results_json_io_error(self, mock_resolve: object, tmp_path: Path) -> None:
        mock_resolve.side_effect = ResultsJsonIOError("bad oci")  # type: ignore[attr-defined]
        with pytest.raises(PullRunnerError, match="bad oci"):
            resolve_results_json_local_path("quay.io/ns/repo@sha256:abc", oci_dest_dir=tmp_path)

    @patch("pulp_tool.cli.runner_helpers.resolve_results_json_path")
    def test_oci_creates_temp_directory(self, mock_resolve: object) -> None:
        def write_json(_ref: str, dest: Path) -> Path:
            path = dest / "pulp_results.json"
            path.write_text('{"artifacts": {}}', encoding="utf-8")
            return path

        mock_resolve.side_effect = write_json  # type: ignore[attr-defined]
        local, temp = resolve_results_json_local_path("quay.io/ns/repo@sha256:abc", oci_dest_dir=None)
        assert temp is not None
        assert Path(local).is_file()
        temp.cleanup()

    @patch("pulp_tool.cli.runner_helpers.resolve_results_json_path")
    def test_oci_temp_cleaned_up_on_resolve_error(self, mock_resolve: object) -> None:
        mock_resolve.side_effect = ResultsJsonIOError("pull failed")  # type: ignore[attr-defined]
        with pytest.raises(PullRunnerError, match="pull failed"):
            resolve_results_json_local_path("quay.io/ns/repo@sha256:abc", oci_dest_dir=None)


class TestArtifactRowFromJson:
    def test_passes_through_metadata_instance(self) -> None:
        meta = ArtifactMetadata(pulp_labels={"build_id": "b1"})
        assert artifact_row_from_json(meta) is meta

    def test_dict_row(self) -> None:
        meta = artifact_row_from_json({"pulp_labels": {"build_id": "b1"}})
        assert isinstance(meta, ArtifactMetadata)
        assert meta.build_id == "b1"

    def test_invalid_returns_none(self) -> None:
        assert artifact_row_from_json(42) is None

    def test_invalid_dict_returns_none(self) -> None:
        assert artifact_row_from_json({"href_history": [{"operation": "x"}]}) is None
