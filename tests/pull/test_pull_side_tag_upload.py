"""Tests for side-tag RPM upload during pull."""

from unittest.mock import Mock, patch

import httpx
import pytest

from pulp_tool.models.artifacts import ArtifactData, ArtifactMetadata, PulledArtifacts
from pulp_tool.models.context import PullContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.pull.side_tag import SideTagUploadResult, upload_rpms_to_side_tag_repository


class TestUploadRpmsToSideTagRepository:
    def test_returns_empty_without_rpms(self) -> None:
        context = PullContext(artifact_location="http://example.com/json", side_tag="mytest")
        assert upload_rpms_to_side_tag_repository(
            Mock(), PulledArtifacts(), ArtifactData(artifact_json={}, artifacts={}), context
        ) == SideTagUploadResult(transfers=[], distribution_base_url="")

    def test_upload_rpms_to_side_tag_returns_transfers(self) -> None:
        mock_client = Mock()
        mock_client.add_content.return_value = Mock(pulp_href="/tasks/add/")
        pulled = PulledArtifacts()
        pulled.add_rpm("pkg.rpm", "/tmp/pkg.rpm", {"build_id": "b1", "namespace": "ns", "arch": "x86_64"})
        artifact_data = ArtifactData(
            artifact_json=PulpResultsDocument(
                artifacts={
                    "pkg.rpm": ArtifactMetadata(
                        href="/pulp/source/",
                        url="https://example.com/pkg.rpm",
                        pulp_labels={"build_id": "b1", "namespace": "ns"},
                    )
                }
            ),
            artifacts={
                "pkg.rpm": ArtifactMetadata(
                    href="/pulp/source/",
                    url="https://example.com/pkg.rpm",
                    pulp_labels={"build_id": "b1", "namespace": "ns"},
                )
            },
        )
        context = PullContext(
            artifact_location="http://example.com/json",
            side_tag="mytest",
            namespace="ns",
            build_id="b1",
            cluster="c1",
        )
        with (
            patch("pulp_tool.pull.side_tag.PulpHelper") as mock_helper_cls,
            patch(
                "pulp_tool.pull.side_tag.upload_rpms_parallel",
                return_value=([("/tmp/pkg.rpm", "/pulp/new/")], []),
            ),
            patch("pulp_tool.pull.side_tag.wait_for_successful_task"),
            patch("pulp_tool.pull.side_tag.calculate_sha256_checksum", return_value="deadbeef"),
        ):
            mock_helper = mock_helper_cls.return_value
            mock_helper.ensure_side_tag_rpm_repository.return_value = (
                "/pulp/side/repo/",
                "https://rok.example/mytest/",
            )
            mock_client._build_artifact_distribution_url.return_value = "https://rok.example/mytest/Packages/p/pkg.rpm"
            result = upload_rpms_to_side_tag_repository(mock_client, pulled, artifact_data, context)
        assert len(result.transfers) == 1
        assert result.transfers[0].pulp_href == "/pulp/new/"
        assert result.transfers[0].artifact_key == "pkg.rpm"
        assert result.distribution_base_url == "https://rok.example/mytest/"

    def test_logs_rpm_upload_errors(self) -> None:
        pulled = PulledArtifacts()
        pulled.add_rpm("pkg.rpm", "/tmp/pkg.rpm", {"build_id": "b1", "arch": "x86_64"})
        context = PullContext(artifact_location="http://example.com/json", side_tag="mytest", build_id="b1")
        with (
            patch("pulp_tool.pull.side_tag.PulpHelper") as mock_helper_cls,
            patch(
                "pulp_tool.pull.side_tag.upload_rpms_parallel",
                return_value=([], ["upload failed"]),
            ),
        ):
            mock_helper_cls.return_value.ensure_side_tag_rpm_repository.return_value = ("/repo/", "https://side/")
            assert upload_rpms_to_side_tag_repository(
                Mock(), pulled, ArtifactData(artifact_json={}, artifacts={}), context
            ) == SideTagUploadResult(transfers=[], distribution_base_url="https://side/")

    def test_add_content_failure_raises(self) -> None:
        mock_client = Mock()
        mock_client.add_content.side_effect = httpx.HTTPError("boom")
        pulled = PulledArtifacts()
        pulled.add_rpm("pkg.rpm", "/tmp/pkg.rpm", {"build_id": "b1", "arch": "x86_64"})
        context = PullContext(artifact_location="http://example.com/json", side_tag="mytest", build_id="b1")
        with (
            patch("pulp_tool.pull.side_tag.PulpHelper") as mock_helper_cls,
            patch(
                "pulp_tool.pull.side_tag.upload_rpms_parallel",
                return_value=([("/tmp/pkg.rpm", "/pulp/new/")], []),
            ),
            patch("pulp_tool.pull.side_tag.wait_for_successful_task"),
            patch("pulp_tool.pull.side_tag.handle_generic_error") as mock_err,
        ):
            mock_helper_cls.return_value.ensure_side_tag_rpm_repository.return_value = ("/repo/", "https://side/")
            with pytest.raises(httpx.HTTPError):
                upload_rpms_to_side_tag_repository(
                    mock_client,
                    pulled,
                    ArtifactData(artifact_json={}, artifacts={}),
                    context,
                )
            mock_err.assert_called_once()

    def test_skips_unmapped_rpm_paths(self) -> None:
        mock_client = Mock()
        mock_client.add_content.return_value = Mock(pulp_href="/tasks/add/")
        pulled = PulledArtifacts()
        pulled.add_rpm("pkg.rpm", "/tmp/pkg.rpm", {"build_id": "b1", "arch": "x86_64"})
        context = PullContext(artifact_location="http://example.com/json", side_tag="mytest", build_id="b1")
        with (
            patch("pulp_tool.pull.side_tag.PulpHelper") as mock_helper_cls,
            patch(
                "pulp_tool.pull.side_tag.upload_rpms_parallel",
                return_value=([("/other/path.rpm", "/pulp/new/")], []),
            ),
            patch("pulp_tool.pull.side_tag.wait_for_successful_task"),
        ):
            mock_helper_cls.return_value.ensure_side_tag_rpm_repository.return_value = ("/repo/", "https://side/")
            assert upload_rpms_to_side_tag_repository(
                mock_client, pulled, ArtifactData(artifact_json={}, artifacts={}), context
            ) == SideTagUploadResult(transfers=[], distribution_base_url="https://side/")

    def test_skips_non_rpm_artifact_key_without_repo_create(self) -> None:
        """Side-tag repo is RPM-only: bad keys are skipped and ensure_side_tag is not called."""
        pulled = PulledArtifacts()
        pulled.add_rpm("not-an-rpm.json", "/tmp/x.json", {"build_id": "b1", "arch": "noarch"})
        context = PullContext(artifact_location="http://example.com/json", side_tag="mytest", build_id="b1")
        with patch("pulp_tool.pull.side_tag.PulpHelper") as mock_helper_cls:
            assert upload_rpms_to_side_tag_repository(
                Mock(),
                pulled,
                ArtifactData(
                    artifact_json=PulpResultsDocument(
                        artifacts={
                            "not-an-rpm.json": ArtifactMetadata(
                                href="/pulp/source/",
                                url="https://example.com/x.json",
                                pulp_labels={"build_id": "b1"},
                            )
                        }
                    ),
                    artifacts={},
                ),
                context,
            ) == SideTagUploadResult(transfers=[], distribution_base_url="")
            mock_helper_cls.return_value.ensure_side_tag_rpm_repository.assert_not_called()

    def test_skips_non_rpm_file_path_without_repo_create(self) -> None:
        pulled = PulledArtifacts()
        pulled.add_rpm("pkg.rpm", "/tmp/pkg.txt", {"build_id": "b1", "arch": "noarch"})
        context = PullContext(artifact_location="http://example.com/json", side_tag="mytest", build_id="b1")
        with patch("pulp_tool.pull.side_tag.PulpHelper") as mock_helper_cls:
            assert upload_rpms_to_side_tag_repository(
                Mock(),
                pulled,
                ArtifactData(artifact_json=PulpResultsDocument(artifacts={}), artifacts={}),
                context,
            ) == SideTagUploadResult(transfers=[], distribution_base_url="")
            mock_helper_cls.return_value.ensure_side_tag_rpm_repository.assert_not_called()
