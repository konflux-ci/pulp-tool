"""Tests for PullService intermediate ORAS bundle transfer path."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.models.artifacts import PulledArtifacts
from pulp_tool.models.context import PullContext
from pulp_tool.models.pull_workflow import PullRunResult
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.services.pull_service import PullService
from pulp_tool.utils.rpm_gpg_verify import RpmGpgVerifyError


@pytest.fixture
def bundle_dir(tmp_path: Path) -> Path:
    rpm = tmp_path / "pkg.noarch.rpm"
    rpm.write_bytes(b"rpm")
    return tmp_path


class TestPullServiceIntermediateOrasBundle:
    def test_run_delegates_to_intermediate_bundle(self, bundle_dir: Path) -> None:
        context = PullContext(
            operation_label="transfer",
            oci_intermediate_bundle_dir=str(bundle_dir),
            config="/cfg.toml",
            transfer_dest="/cfg.toml",
        )
        expected = PullRunResult(
            pulled_artifacts=PulledArtifacts(),
            completed=1,
            failed=0,
            upload_info=None,
        )
        with patch.object(PullService, "_run_intermediate_oras_bundle", return_value=expected) as mock_bundle:
            result = PullService().run(context, distribution_client=None, max_workers=2)
        mock_bundle.assert_called_once()
        assert result is expected

    def test_missing_bundle_dir(self) -> None:
        context = PullContext(operation_label="transfer", oci_intermediate_bundle_dir="  ")
        result = PullService()._run_intermediate_oras_bundle(context, distribution_client=None)
        assert result.error_messages
        assert "missing" in result.error_messages[0].lower()

    def test_collect_failure(self, tmp_path: Path) -> None:
        context = PullContext(
            operation_label="transfer",
            oci_intermediate_bundle_dir=str(tmp_path),
        )
        result = PullService()._run_intermediate_oras_bundle(context, distribution_client=None)
        assert "No RPM files" in result.error_messages[0]

    @patch("pulp_tool.services.pull_service.setup_repositories_if_needed", return_value=None)
    def test_no_pulp_client_skips_upload(self, _mock_setup: MagicMock, bundle_dir: Path) -> None:
        context = PullContext(
            operation_label="transfer",
            oci_intermediate_bundle_dir=str(bundle_dir),
            config="/cfg.toml",
            transfer_dest="/cfg.toml",
            build_id="b1",
        )
        with patch("pulp_tool.services.pull_service.generate_pull_report"):
            result = PullService()._run_intermediate_oras_bundle(context, distribution_client=None)
        assert result.completed == 1
        assert result.upload_info is None
        assert not result.error_messages

    @patch("pulp_tool.services.pull_service.verify_pulled_rpms_gpg", side_effect=RpmGpgVerifyError("bad sig"))
    @patch("pulp_tool.services.pull_service.setup_repositories_if_needed")
    def test_gpg_verify_failure(
        self,
        mock_setup: MagicMock,
        _mock_gpg: MagicMock,
        bundle_dir: Path,
    ) -> None:
        mock_setup.return_value = MagicMock(client=MagicMock(), repositories=None)
        context = PullContext(
            operation_label="transfer",
            oci_intermediate_bundle_dir=str(bundle_dir),
            verify_rpm_gpg=True,
            config="/cfg.toml",
            transfer_dest="/cfg.toml",
            build_id="b1",
        )
        result = PullService()._run_intermediate_oras_bundle(context, distribution_client=None)
        assert "bad sig" in result.error_messages[0]

    @patch("pulp_tool.services.pull_service.finalize_transfer_oci_post_copy")
    @patch("pulp_tool.services.pull_service.upload_transfer_pulp_results_json_to_artifacts")
    @patch("pulp_tool.services.pull_service.upload_downloaded_files_to_pulp")
    @patch("pulp_tool.services.pull_service.setup_repositories_if_needed")
    @patch("pulp_tool.services.pull_service.generate_pull_report")
    def test_upload_and_finalize_oras_copy(
        self,
        _mock_report: MagicMock,
        mock_setup: MagicMock,
        mock_upload: MagicMock,
        mock_results_upload: MagicMock,
        mock_finalize: MagicMock,
        bundle_dir: Path,
    ) -> None:
        pulp_client = MagicMock()
        mock_setup.return_value = MagicMock(client=pulp_client, repositories=MagicMock())
        doc = PulpResultsDocument(build_id="b1", artifacts={})
        doc.upload_errors = []
        mock_upload.return_value = doc
        context = PullContext(
            operation_label="transfer",
            oci_intermediate_bundle_dir=str(bundle_dir),
            config="/cfg.toml",
            transfer_dest="/cfg.toml",
            build_id="b1",
            pulp_oras_cp_target=True,
            snapshot_path="/snap.json",
        )
        PullService()._run_intermediate_oras_bundle(context, distribution_client=None)
        mock_upload.assert_called_once()
        mock_results_upload.assert_called_once()
        mock_finalize.assert_called_once()

    @patch("pulp_tool.services.pull_service.upload_rpms_to_side_tag_repository")
    @patch("pulp_tool.services.pull_service.publish_side_tag_results")
    @patch("pulp_tool.services.pull_service.upload_downloaded_files_to_pulp")
    @patch("pulp_tool.services.pull_service.setup_repositories_if_needed")
    @patch("pulp_tool.services.pull_service.generate_pull_report")
    def test_side_tag_upload_branch(
        self,
        _mock_report: MagicMock,
        mock_setup: MagicMock,
        mock_upload: MagicMock,
        mock_publish: MagicMock,
        mock_side: MagicMock,
        bundle_dir: Path,
    ) -> None:
        mock_setup.return_value = MagicMock(client=MagicMock(), repositories=MagicMock())
        doc = PulpResultsDocument(build_id="b1", artifacts={})
        mock_upload.return_value = doc
        mock_side.return_value = MagicMock(transfers=[], distribution_base_url="https://pulp/side")
        context = PullContext(
            operation_label="transfer",
            oci_intermediate_bundle_dir=str(bundle_dir),
            config="/cfg.toml",
            transfer_dest="/cfg.toml",
            build_id="b1",
            side_tag="st",
        )
        PullService()._run_intermediate_oras_bundle(context, distribution_client=None)
        mock_side.assert_called_once()
        mock_publish.assert_called_once()

    @patch("pulp_tool.services.pull_service.upload_downloaded_files_to_pulp")
    @patch("pulp_tool.services.pull_service.setup_repositories_if_needed")
    @patch("pulp_tool.services.pull_service.generate_pull_report")
    def test_upload_errors_surface_in_result(
        self,
        _mock_report: MagicMock,
        mock_setup: MagicMock,
        mock_upload: MagicMock,
        bundle_dir: Path,
    ) -> None:
        mock_setup.return_value = MagicMock(client=MagicMock(), repositories=MagicMock())
        doc = PulpResultsDocument(build_id="b1", artifacts={})
        doc.add_error("rpm x: failed")
        mock_upload.return_value = doc
        context = PullContext(
            operation_label="transfer",
            oci_intermediate_bundle_dir=str(bundle_dir),
            config="/cfg.toml",
            transfer_dest="/cfg.toml",
            build_id="b1",
        )
        result = PullService()._run_intermediate_oras_bundle(context, distribution_client=None)
        assert any("upload error" in msg for msg in result.error_messages)

    @patch("pulp_tool.services.pull_service.finalize_transfer_oci_post_copy")
    def test_maybe_finalize_runs_post_copy(self, mock_finalize: MagicMock) -> None:
        context = PullContext(
            operation_label="transfer",
            oras_cp_target="quay.io/t:tag",
            snapshot_path="/s.json",
        )
        PullService._maybe_finalize_oras_copy(context, [])
        mock_finalize.assert_called_once_with(context)

    def test_maybe_finalize_appends_value_error(self) -> None:
        context = PullContext(
            operation_label="transfer",
            oras_cp_target="quay.io/t:tag",
            snapshot_path="/s.json",
        )
        errors: list[str] = []
        with patch(
            "pulp_tool.services.pull_service.finalize_transfer_oci_post_copy",
            side_effect=ValueError("snapshot-path"),
        ):
            PullService._maybe_finalize_oras_copy(context, errors)
        assert errors == ["snapshot-path"]


class TestPullServiceFinalizeGuards:
    def test_finalize_skips_on_errors_or_non_transfer(self) -> None:
        context = PullContext(operation_label="pull", oras_cp_target="quay.io/t:tag")
        errors: list[str] = []
        with patch("pulp_tool.services.pull_service.finalize_transfer_oci_post_copy") as mock_fin:
            PullService._maybe_finalize_oras_copy(context, ["already failed"])
            PullService._maybe_finalize_oras_copy(context, errors)
        mock_fin.assert_not_called()

    def test_finalize_skips_without_copy_flags(self) -> None:
        context = PullContext(operation_label="transfer")
        with patch("pulp_tool.services.pull_service.finalize_transfer_oci_post_copy") as mock_fin:
            PullService._maybe_finalize_oras_copy(context, [])
        mock_fin.assert_not_called()
