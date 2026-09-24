"""Tests for pull side-tag transfer orchestration."""

from unittest.mock import Mock, patch

from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata
from pulp_tool.models.context import PullContext
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.results import PulpResultsModel
from pulp_tool.pull.publish import publish_side_tag_results
from pulp_tool.utils.pulp_results_document import SideTagRpmTransfer


class TestPublishSideTagResults:
    def test_publish_side_tag_results_orchestration(self) -> None:
        mock_client = Mock()
        artifact_data = ArtifactData(
            artifact_json=ArtifactJsonResponse(
                version=1,
                artifacts={
                    "pkg.rpm": ArtifactMetadata(
                        href="/pulp/src/",
                        url="https://example.com/pkg.rpm",
                        sha256="aa",
                        labels={"build_id": "b1", "namespace": "ns"},
                    )
                },
                distributions={"rpms": "https://example.com/rpms/"},  # type: ignore[dict-item]
            ),
            artifacts={
                "pkg.rpm": ArtifactMetadata(
                    href="/pulp/src/",
                    url="https://example.com/pkg.rpm",
                    sha256="aa",
                    labels={"build_id": "b1", "namespace": "ns"},
                )
            },
        )
        context = PullContext(
            artifact_location="http://example.com/pulp_results.json",
            transfer_dest="/cfg",
            side_tag="mytest",
            artifact_results="/tmp/url,/tmp/digest",
            oci_storage="quay.io/ns/repo:latest",
            namespace="ns",
            build_id="b1",
            cluster="cluster-a",
        )
        repos = RepositoryRefs(
            rpms_prn="rpm",
            logs_prn="log",
            sbom_prn="sbom",
            artifacts_prn="artifacts",
            rpms_href="/rpms/",
            logs_href="/logs/",
            sbom_href="/sbom/",
            artifacts_href="/artifacts/",
        )
        upload_info = PulpResultsModel(build_id="b1", repositories=repos)
        transfers = [
            SideTagRpmTransfer(
                artifact_key="pkg.rpm",
                pulp_href="/pulp/new/",
                sha256="bb",
                distribution_url="https://rok/side-tag-mytest/Packages/p/pkg.rpm",
            )
        ]
        with (
            patch("pulp_tool.pull.publish.PulpHelper") as mock_helper_cls,
            patch(
                "pulp_tool.pull.publish.sync_pulp_results_with_oci_registry",
                return_value=("quay.io/ns/repo@sha256:final", Mock()),
            ),
            patch("pulp_tool.pull.publish._write_konflux_oci_results") as mock_write,
            patch("pulp_tool.pull.publish.update_snapshot_pulp_results_manifest") as mock_snapshot,
        ):
            mock_helper = mock_helper_cls.return_value
            mock_helper.ensure_side_tag_rpm_repository.return_value = ("/rpms/side/", "https://rok/side-tag-mytest/")
            publish_side_tag_results(mock_client, artifact_data, context, upload_info, transfers)
            mock_write.assert_called_once()
            mock_snapshot.assert_not_called()

    def test_publish_updates_snapshot_when_configured(self) -> None:
        mock_client = Mock()
        artifact_data = ArtifactData(
            artifact_json=ArtifactJsonResponse(
                version=1,
                artifacts={
                    "pkg.rpm": ArtifactMetadata(
                        href="/pulp/src/",
                        url="https://example.com/pkg.rpm",
                        sha256="aa",
                        labels={"build_id": "b1"},
                    )
                },
            ),
            artifacts={
                "pkg.rpm": ArtifactMetadata(
                    href="/pulp/src/",
                    url="https://example.com/pkg.rpm",
                    sha256="aa",
                    labels={"build_id": "b1"},
                )
            },
        )
        context = PullContext(
            artifact_location="http://example.com/pulp_results.json",
            transfer_dest="/cfg",
            side_tag="mytest",
            artifact_results="/tmp/url,/tmp/digest",
            oci_storage="quay.io/ns/repo:latest",
            snapshot_path="/data/snapshot.json",
            build_id="b1",
        )
        repos = RepositoryRefs(
            rpms_prn="rpm",
            logs_prn="log",
            sbom_prn="sbom",
            artifacts_prn="artifacts",
            rpms_href="/rpms/",
            logs_href="/logs/",
            sbom_href="/sbom/",
            artifacts_href="/artifacts/",
        )
        upload_info = PulpResultsModel(build_id="b1", repositories=repos)
        transfers = [
            SideTagRpmTransfer(
                artifact_key="pkg.rpm",
                pulp_href="/pulp/new/",
                sha256="bb",
                distribution_url="https://rok/side-tag-mytest/Packages/p/pkg.rpm",
            )
        ]
        with (
            patch("pulp_tool.pull.publish.PulpHelper") as mock_helper_cls,
            patch(
                "pulp_tool.pull.publish.sync_pulp_results_with_oci_registry",
                return_value=("quay.io/ns/repo@sha256:final", Mock()),
            ),
            patch("pulp_tool.pull.publish._write_konflux_oci_results"),
            patch("pulp_tool.pull.publish.update_snapshot_pulp_results_manifest") as mock_snapshot,
        ):
            mock_helper = mock_helper_cls.return_value
            mock_helper.ensure_side_tag_rpm_repository.return_value = ("/rpms/side/", "https://rok/side/")
            publish_side_tag_results(mock_client, artifact_data, context, upload_info, transfers)
            mock_snapshot.assert_called_once_with("/data/snapshot.json", "quay.io/ns/repo@sha256:final")
