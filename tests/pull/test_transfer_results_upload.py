"""Tests for transfer destination ``pulp_results.json`` upload."""

import json
from unittest.mock import MagicMock, patch

from pulp_tool.models.artifacts import ArtifactData
from pulp_tool.models.context import PullContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.pull.transfer_results_upload import upload_transfer_pulp_results_json_to_artifacts


def _repos() -> RepositoryRefs:
    return RepositoryRefs(
        rpms_href="/r/",
        rpms_prn="rp",
        logs_href="/l/",
        logs_prn="lp",
        sbom_href="/s/",
        sbom_prn="sp",
        artifacts_href="/a/",
        artifacts_prn="pulp://dom/ns/art",
    )


def test_upload_transfer_pulp_results_json_skips_non_transfer() -> None:
    doc = PulpResultsDocument(artifacts={}, distributions={})
    artifact_data = ArtifactData(artifact_json=doc, artifacts={})
    upload_info = PulpResultsDocument(build_id="b1", repositories=_repos())
    mock_client = MagicMock()
    with patch("pulp_tool.pull.transfer_results_upload.create_file_content_and_wait") as mock_create:
        upload_transfer_pulp_results_json_to_artifacts(
            mock_client,
            artifact_data,
            upload_info,
            PullContext(operation_label="pull"),
        )
        mock_create.assert_not_called()


def test_upload_transfer_pulp_results_json_skips_side_tag() -> None:
    doc = PulpResultsDocument(artifacts={}, distributions={})
    artifact_data = ArtifactData(artifact_json=doc, artifacts={})
    upload_info = PulpResultsDocument(build_id="b1", repositories=_repos())
    mock_client = MagicMock()
    with patch("pulp_tool.pull.transfer_results_upload.create_file_content_and_wait") as mock_create:
        upload_transfer_pulp_results_json_to_artifacts(
            mock_client,
            artifact_data,
            upload_info,
            PullContext(operation_label="transfer", side_tag="st"),
        )
        mock_create.assert_not_called()


def test_upload_transfer_pulp_results_json_merges_and_uploads() -> None:
    source = PulpResultsDocument.from_raw(
        {
            "version": "1.0.0",
            "build_id": "b1",
            "namespace": "ns",
            "artifacts": {
                "pkg.rpm": {
                    "url": "https://source.example/rpms/pkg.rpm",
                    "sha256": "aa" * 32,
                    "pulp_labels": {"build_id": "b1", "arch": "noarch"},
                }
            },
            "distributions": {"rpms": "https://source.example/ns/b1/rpms/"},
        }
    )
    artifact_data = ArtifactData(artifact_json=source, artifacts=dict(source.artifacts))

    upload_info = PulpResultsDocument(build_id="b1", repositories=_repos())
    upload_info.add_artifact(
        "pkg.rpm",
        "https://dest.example/ns/b1/rpms/pkg.rpm",
        "bb" * 32,
        {"build_id": "b1", "arch": "noarch"},
    )
    upload_info.artifacts["pkg.rpm"].href = "/pulp/api/v3/content/rpm/dest/"

    mock_client = MagicMock()
    with patch("pulp_tool.pull.transfer_results_upload.create_file_content_and_wait") as mock_create:
        upload_transfer_pulp_results_json_to_artifacts(
            mock_client,
            artifact_data,
            upload_info,
            PullContext(operation_label="transfer", namespace="ns"),
        )
        mock_create.assert_called_once()
        payload = json.loads(mock_create.call_args[0][2])
        row = payload["artifacts"]["pkg.rpm"]
        assert row["href"] == "/pulp/api/v3/content/rpm/dest/"
        assert row["sha256"] == "bb" * 32
        assert "href_history" in row
        assert upload_info.uploaded_counts.files >= 1
