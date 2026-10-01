"""Additional coverage for update-build service run path."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.services.update_build import run_update_build


def _repos() -> RepositoryRefs:
    return RepositoryRefs(
        rpms_href="/r/",
        rpms_prn="r",
        logs_href="/l/",
        logs_prn="l",
        sbom_href="/s/",
        sbom_prn="s",
        artifacts_href="/a/",
        artifacts_prn="artifacts-prn",
    )


def test_run_update_build_requires_artifact_results() -> None:
    ctx = UploadRpmContext(
        build_id="b",
        date_str="d",
        namespace="ns",
        results_json="/tmp/x.json",
        artifact_results=None,
    )
    with pytest.raises(ValueError, match="artifact-results"):
        run_update_build(MagicMock(), ctx, operation="build_sign", replace_signed_by=False, oci_temp_dir=Path("/tmp"))


def test_run_update_build_happy_path(tmp_path: Path) -> None:
    doc_path = tmp_path / "in.json"
    doc_path.write_text(
        '{"version":1,"build_id":"b1","namespace":"ns1","artifacts":{}}',
        encoding="utf-8",
    )
    ctx = UploadRpmContext(
        build_id="",
        date_str="2020-01-01",
        namespace="",
        results_json=str(doc_path),
        artifact_results=f"{tmp_path}/url,{tmp_path}/dig",
        oci_storage="quay.io/ns/r:tag",
    )
    model = PulpResultsDocument(build_id="b1", repositories=_repos())
    oci_dir = tmp_path / "oci"
    oci_dir.mkdir()
    with (
        patch(
            "pulp_tool.services.update_build.load_results_document",
            return_value=PulpResultsDocument.from_raw(
                {"version": 1, "build_id": "b1", "namespace": "ns1", "artifacts": {}}
            ),
        ),
        patch("pulp_tool.services.update_build.PulpHelper") as mock_helper,
        patch(
            "pulp_tool.services.update_build.process_uploads_from_results_json",
            return_value=model,
        ),
        patch(
            "pulp_tool.services.update_build.sync_pulp_results_with_oci_registry",
            return_value=("quay.io/r@sha256:ab", MagicMock()),
        ),
        patch("pulp_tool.services.update_build._write_konflux_oci_results"),
    ):
        mock_helper.return_value.setup_repositories.return_value = _repos()
        ref = run_update_build(
            MagicMock(),
            ctx,
            operation="build_sign",
            replace_signed_by=False,
            oci_temp_dir=oci_dir,
        )
    assert ref == "quay.io/r@sha256:ab"


def test_run_update_build_passes_attach_subject_for_oci_results_json(tmp_path: Path) -> None:
    oci_dir = tmp_path / "oci"
    oci_dir.mkdir()
    subject = "quay.io/ns/build@sha256:" + "a" * 64
    ctx = UploadRpmContext(
        build_id="",
        date_str="2020-01-01",
        namespace="",
        results_json=subject,
        artifact_results=f"{tmp_path}/url,{tmp_path}/dig",
        oci_storage="quay.io/ns/r:tag",
    )
    model = PulpResultsDocument(build_id="b1", repositories=_repos())
    with (
        patch(
            "pulp_tool.services.update_build.load_results_document",
            return_value=PulpResultsDocument.from_raw(
                {"version": 1, "build_id": "b1", "namespace": "ns1", "artifacts": {}}
            ),
        ),
        patch("pulp_tool.services.update_build.PulpHelper") as mock_helper,
        patch(
            "pulp_tool.services.update_build.process_uploads_from_results_json",
            return_value=model,
        ),
        patch(
            "pulp_tool.services.update_build.sync_pulp_results_with_oci_registry",
            return_value=("quay.io/r@sha256:attached", MagicMock()),
        ) as mock_sync,
        patch("pulp_tool.services.update_build._write_konflux_oci_results"),
    ):
        mock_helper.return_value.setup_repositories.return_value = _repos()
        run_update_build(
            MagicMock(),
            ctx,
            operation="build_sign",
            replace_signed_by=False,
            oci_temp_dir=oci_dir,
        )
    assert mock_sync.call_args.kwargs.get("attach_subject") == subject


def test_run_update_build_requires_results_json() -> None:
    ctx = UploadRpmContext(
        build_id="b",
        date_str="d",
        namespace="ns",
        results_json="",
        artifact_results="/u,/d",
        oci_storage="quay.io/r:tag",
    )
    with pytest.raises(ValueError, match="results_json"):
        run_update_build(MagicMock(), ctx, operation="build_sign", replace_signed_by=False, oci_temp_dir=Path("/tmp"))


def test_run_update_build_requires_build_id_namespace(tmp_path: Path) -> None:
    oci_dir = tmp_path / "oci"
    oci_dir.mkdir()
    ctx = UploadRpmContext(
        build_id="",
        date_str="d",
        namespace="",
        results_json=str(tmp_path / "x.json"),
        artifact_results=f"{tmp_path}/u,{tmp_path}/d",
        oci_storage="quay.io/r:tag",
    )
    with patch(
        "pulp_tool.services.update_build.load_results_document",
        return_value=PulpResultsDocument.from_raw({"version": 1, "artifacts": {}}),
    ):
        with pytest.raises(ValueError, match="build_id and namespace"):
            run_update_build(MagicMock(), ctx, operation="build_sign", replace_signed_by=False, oci_temp_dir=oci_dir)


def test_run_update_build_requires_oci_storage(tmp_path: Path) -> None:
    oci_dir = tmp_path / "oci"
    oci_dir.mkdir()
    ctx = UploadRpmContext(
        build_id="b1",
        date_str="d",
        namespace="ns1",
        results_json=str(tmp_path / "x.json"),
        artifact_results=f"{tmp_path}/u,{tmp_path}/d",
        oci_storage=None,
    )
    doc = PulpResultsDocument.from_raw(
        {
            "version": 1,
            "build_id": "b1",
            "namespace": "ns1",
            "distributions": {"rpms": "https://x/rpms/"},
            "artifacts": {"a.rpm": {"distributions": {"rpms": "https://x/rpms/"}}},
        }
    )
    model = PulpResultsDocument(build_id="b1", repositories=_repos())
    model.distributions["rpms"] = "https://new/rpms/"
    with (
        patch("pulp_tool.services.update_build.load_results_document", return_value=doc),
        patch("pulp_tool.services.update_build.PulpHelper") as mock_helper,
        patch("pulp_tool.services.update_build.process_uploads_from_results_json", return_value=model),
        patch("pulp_tool.services.update_build.resolve_correlation_id", return_value="corr-1"),
    ):
        mock_helper.return_value.setup_repositories.return_value = _repos()
        with pytest.raises(ValueError, match="--oci-storage is required"):
            run_update_build(
                MagicMock(),
                ctx,
                operation="build_sign",
                replace_signed_by=False,
                oci_temp_dir=oci_dir,
            )


def test_run_update_build_logs_correlation_id(tmp_path: Path, caplog) -> None:
    import logging

    caplog.set_level(logging.INFO)
    oci_dir = tmp_path / "oci"
    oci_dir.mkdir()
    ctx = UploadRpmContext(
        build_id="b1",
        date_str="d",
        namespace="ns1",
        results_json=str(tmp_path / "x.json"),
        artifact_results=f"{tmp_path}/u,{tmp_path}/d",
        oci_storage="quay.io/r:tag",
    )
    with (
        patch(
            "pulp_tool.services.update_build.load_results_document",
            return_value=PulpResultsDocument.from_raw(
                {"version": 1, "build_id": "b1", "namespace": "ns1", "artifacts": {}}
            ),
        ),
        patch("pulp_tool.services.update_build.PulpHelper") as mock_helper,
        patch(
            "pulp_tool.services.update_build.process_uploads_from_results_json",
            return_value=PulpResultsDocument(build_id="b1", repositories=_repos()),
        ),
        patch(
            "pulp_tool.services.update_build.sync_pulp_results_with_oci_registry",
            return_value=("quay.io/r@sha256:ab", MagicMock()),
        ),
        patch("pulp_tool.services.update_build._write_konflux_oci_results"),
        patch("pulp_tool.services.update_build.resolve_correlation_id", return_value="update-build-cid"),
    ):
        mock_helper.return_value.setup_repositories.return_value = _repos()
        run_update_build(MagicMock(), ctx, operation="build_sign", replace_signed_by=False, oci_temp_dir=oci_dir)
    assert "Correlation ID for update-build: update-build-cid" in caplog.text


def test_run_update_build_non_model_upload_outcome(tmp_path: Path) -> None:
    oci_dir = tmp_path / "oci"
    oci_dir.mkdir()
    ctx = UploadRpmContext(
        build_id="b1",
        date_str="d",
        namespace="ns1",
        results_json=str(tmp_path / "x.json"),
        artifact_results=f"{tmp_path}/u,{tmp_path}/d",
        oci_storage="quay.io/r:tag",
    )
    with (
        patch(
            "pulp_tool.services.update_build.load_results_document",
            return_value=PulpResultsDocument.from_raw(
                {"version": 1, "build_id": "b1", "namespace": "ns1", "artifacts": {}}
            ),
        ),
        patch("pulp_tool.services.update_build.PulpHelper") as mock_helper,
        patch(
            "pulp_tool.services.update_build.process_uploads_from_results_json",
            return_value=None,
        ),
        patch(
            "pulp_tool.services.update_build.sync_pulp_results_with_oci_registry",
            return_value=("quay.io/r@sha256:cd", MagicMock()),
        ),
        patch("pulp_tool.services.update_build._write_konflux_oci_results"),
        patch("pulp_tool.services.update_build.resolve_correlation_id", return_value="cid"),
    ):
        mock_helper.return_value.setup_repositories.return_value = _repos()
        ref = run_update_build(
            MagicMock(),
            ctx,
            operation="build_sign",
            replace_signed_by=False,
            oci_temp_dir=oci_dir,
        )
    assert ref == "quay.io/r@sha256:cd"
