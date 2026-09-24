"""Tests for side-tag RPM upload during pull."""

from unittest.mock import Mock, patch

from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata, PulledArtifacts
from pulp_tool.models.context import PullContext
from pulp_tool.pull.side_tag import upload_rpms_to_side_tag_repository


class TestUploadRpmsToSideTagRepository:
    def test_upload_rpms_to_side_tag_returns_transfers(self) -> None:
        mock_client = Mock()
        mock_client.add_content.return_value = Mock(pulp_href="/tasks/add/")
        pulled = PulledArtifacts()
        pulled.add_rpm("pkg.rpm", "/tmp/pkg.rpm", {"build_id": "b1", "namespace": "ns", "arch": "x86_64"})
        artifact_data = ArtifactData(
            artifact_json=ArtifactJsonResponse(
                artifacts={
                    "pkg.rpm": ArtifactMetadata(
                        href="/pulp/source/",
                        url="https://example.com/pkg.rpm",
                        labels={"build_id": "b1", "namespace": "ns"},
                    )
                }
            ),
            artifacts={
                "pkg.rpm": ArtifactMetadata(
                    href="/pulp/source/",
                    url="https://example.com/pkg.rpm",
                    labels={"build_id": "b1", "namespace": "ns"},
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
                "https://rok.example/side-tag-mytest/",
            )
            mock_client._build_artifact_distribution_url.return_value = (
                "https://rok.example/side-tag-mytest/Packages/p/pkg.rpm"
            )
            transfers = upload_rpms_to_side_tag_repository(mock_client, pulled, artifact_data, context)
        assert len(transfers) == 1
        assert transfers[0].pulp_href == "/pulp/new/"
        assert transfers[0].artifact_key == "pkg.rpm"
