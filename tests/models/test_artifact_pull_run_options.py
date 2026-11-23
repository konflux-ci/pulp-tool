"""Tests for ArtifactPullRunOptions and related pull/transfer CLI models."""

from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.models.artifact_pull_run import ArtifactPullRunOptions, SideTagResolution


class TestArtifactPullRunOptions:
    def test_parsed_content_types_and_archs(self) -> None:
        opts = ArtifactPullRunOptions(
            content_types=" rpm, log ",
            archs="x86_64,noarch",
        )
        assert opts.parsed_content_types() == ["rpm", "log"]
        assert opts.parsed_archs() == ["x86_64", "noarch"]

    def test_distribution_and_pulp_config_paths(self) -> None:
        opts = ArtifactPullRunOptions(
            source_config_path="/build.toml",
            dest_config_path="/release.toml",
            distribution_config="/dist.toml",
        )
        assert opts.distribution_auth_config_path() == "/dist.toml"
        assert opts.pulp_client_config_path() == "/release.toml"

    def test_resolve_side_tag_no_side_tag(self) -> None:
        resolution = ArtifactPullRunOptions().resolve_side_tag()
        assert resolution.ok
        assert resolution.resolved_oci_storage is None

    def test_resolve_side_tag_missing_dest_config(self) -> None:
        resolution = ArtifactPullRunOptions(side_tag="my-tag").resolve_side_tag()
        assert not resolution.ok
        assert "destination --config" in (resolution.error_message or "")

    @patch("pulp_tool.models.artifact_pull_run.resolve_oci_storage", return_value=None)
    @patch("pulp_tool.models.artifact_pull_run.ConfigManager")
    def test_resolve_side_tag_missing_oci_storage(
        self,
        mock_cfg: MagicMock,
        _mock_resolve: MagicMock,
    ) -> None:
        mock_cfg.return_value.load.return_value = None
        mock_cfg.return_value.get.return_value = "prod"
        resolution = ArtifactPullRunOptions(
            side_tag="my-tag",
            dest_config_path="/release.toml",
        ).resolve_side_tag()
        assert not resolution.ok
        assert "--oci-storage" in (resolution.error_message or "")

    @patch("pulp_tool.models.artifact_pull_run.resolve_oci_storage", return_value="quay.io/ns/repo:tag")
    @patch("pulp_tool.models.artifact_pull_run.ConfigManager")
    def test_resolve_side_tag_success(
        self,
        mock_cfg: MagicMock,
        _mock_resolve: MagicMock,
    ) -> None:
        mock_cfg.return_value.load.return_value = None
        mock_cfg.return_value.get.return_value = "cluster-a"
        resolution = ArtifactPullRunOptions(
            side_tag="my-tag",
            dest_config_path="/release.toml",
            oci_storage="quay.io/ns/repo:tag",
        ).resolve_side_tag()
        assert resolution.ok
        assert resolution.resolved_oci_storage == "quay.io/ns/repo:tag"
        assert resolution.cluster == "cluster-a"

    def test_oras_copy_flags_mutually_exclusive(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            ArtifactPullRunOptions(
                dest_config_path="/release.toml",
                oras_cp_target="quay.io/t:tag",
                pulp_oras_cp_target=True,
            )

    def test_to_pull_context(self) -> None:
        opts = ArtifactPullRunOptions(
            dest_config_path="/release.toml",
            build_id="b1",
            namespace="ns",
            max_workers=8,
        )
        side_tag = SideTagResolution(resolved_oci_storage="quay.io/x:y", cluster="c1")
        ctx = opts.to_pull_context(
            resolved_artifact_location="/tmp/pulp_results.json",
            auth_key_path="/key.pem",
            side_tag=side_tag,
            gpg=opts.resolve_gpg(),
        )
        assert ctx.artifact_location == "/tmp/pulp_results.json"
        assert ctx.transfer_dest == "/release.toml"
        assert ctx.transfer_source_config_path == "/release.toml"
        assert ctx.oci_storage == "quay.io/x:y"
        assert ctx.cluster == "c1"
        assert ctx.max_workers == 8
        assert ctx.operation_label == "pull"

    def test_to_pull_context_transfer_sets_source_config(self) -> None:
        opts = ArtifactPullRunOptions(
            operation_label="transfer",
            source_config_path="/build.toml",
            dest_config_path="/release.toml",
        )
        ctx = opts.to_pull_context(
            resolved_artifact_location="/tmp/pulp_results.json",
            auth_key_path=None,
            side_tag=SideTagResolution(),
            gpg=opts.resolve_gpg(),
        )
        assert ctx.operation_label == "transfer"
        assert ctx.transfer_source_config_path == "/build.toml"

    def test_transfer_requires_dest_config(self) -> None:
        with pytest.raises(ValueError, match="dest_config_path"):
            ArtifactPullRunOptions(operation_label="transfer")

    def test_invalid_operation_label(self) -> None:
        with pytest.raises(ValueError, match="operation_label"):
            ArtifactPullRunOptions(operation_label="upload")
