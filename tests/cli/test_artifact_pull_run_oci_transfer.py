"""OCI transfer resolution wiring in ``run_artifact_pull_flow``."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulp_tool.cli.artifact_pull_run import run_artifact_pull_flow
from pulp_tool.models.artifact_pull_run import ArtifactPullRunOptions
from pulp_tool.models.artifacts import PulledArtifacts
from pulp_tool.models.distribution_auth import DistributionAuthSettings
from pulp_tool.models.oci_transfer import OciTransferResolution
from pulp_tool.models.pull_workflow import PullRunResult
from pulp_tool.utils.oras_publish import OrasPublishError


def _auth_settings() -> DistributionAuthSettings:
    return DistributionAuthSettings(
        username=None,
        password=None,
        cert_path=None,
        key_path=None,
        pulp_api_base_url=None,
    )


def _transfer_options(**overrides: object) -> ArtifactPullRunOptions:
    base = {
        "operation_label": "transfer",
        "artifact_location": "quay.io/ns/repo@sha256:abc",
        "dest_config_path": "/dest.toml",
    }
    base.update(overrides)
    return ArtifactPullRunOptions(**base)  # type: ignore[arg-type]


@patch("pulp_tool.cli.artifact_pull_run.PullService")
@patch("pulp_tool.cli.artifact_pull_run.validate_remote_pull_auth")
@patch(
    "pulp_tool.cli.artifact_pull_run.resolve_pulp_api_base_url_for_remote",
    side_effect=lambda **_kwargs: _auth_settings(),
)
@patch("pulp_tool.cli.artifact_pull_run.load_distribution_auth_from_config", return_value=_auth_settings())
@patch("pulp_tool.cli.artifact_pull_run.resolve_oci_transfer_artifact")
def test_transfer_oci_bundle_sets_intermediate_dir(
    mock_resolve: MagicMock,
    _mock_auth: MagicMock,
    _mock_api: MagicMock,
    _mock_validate: MagicMock,
    mock_svc: MagicMock,
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    mock_resolve.return_value = OciTransferResolution(kind="oci_bundle", bundle_dir=bundle)
    mock_svc.return_value.run.return_value = PullRunResult(
        pulled_artifacts=PulledArtifacts(),
        completed=0,
        failed=0,
    )
    run_artifact_pull_flow(_transfer_options())
    context = mock_svc.return_value.run.call_args.args[0]
    assert context.oci_intermediate_bundle_dir == str(bundle)
    assert context.delete_local_sources_after_upload is True


@patch("pulp_tool.cli.artifact_pull_run.PullService")
@patch("pulp_tool.cli.artifact_pull_run.validate_remote_pull_auth")
@patch(
    "pulp_tool.cli.artifact_pull_run.resolve_pulp_api_base_url_for_remote",
    side_effect=lambda **_kwargs: _auth_settings(),
)
@patch("pulp_tool.cli.artifact_pull_run.load_distribution_auth_from_config", return_value=_auth_settings())
@patch("pulp_tool.cli.artifact_pull_run.resolve_oci_transfer_artifact")
def test_transfer_oci_pulp_results_resolves_json_path(
    mock_resolve: MagicMock,
    _mock_auth: MagicMock,
    _mock_api: MagicMock,
    mock_validate: MagicMock,
    mock_svc: MagicMock,
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "pulp_results.json"
    json_path.write_text("{}", encoding="utf-8")
    mock_resolve.return_value = OciTransferResolution(kind="pulp_results", pulp_results_path=json_path)
    mock_svc.return_value.run.return_value = PullRunResult(
        pulled_artifacts=PulledArtifacts(),
        completed=0,
        failed=0,
    )
    run_artifact_pull_flow(_transfer_options())
    mock_validate.assert_called_once()
    assert mock_validate.call_args.args[0] == str(json_path)
    context = mock_svc.return_value.run.call_args.args[0]
    assert context.oci_intermediate_bundle_dir is None


@patch("pulp_tool.cli.artifact_pull_run.sys.exit", side_effect=SystemExit(1))
@patch("pulp_tool.cli.artifact_pull_run.load_distribution_auth_from_config", return_value=_auth_settings())
@patch("pulp_tool.cli.artifact_pull_run.resolve_oci_transfer_artifact")
def test_transfer_oci_resolution_failure_exits(
    mock_resolve: MagicMock,
    _mock_auth: MagicMock,
    _mock_exit: MagicMock,
) -> None:
    mock_resolve.return_value = OciTransferResolution(kind="pulp_results", pulp_results_path=None)
    with pytest.raises(SystemExit):
        run_artifact_pull_flow(_transfer_options())


@patch("pulp_tool.cli.artifact_pull_run.sys.exit", side_effect=SystemExit(1))
@patch("pulp_tool.cli.artifact_pull_run.load_distribution_auth_from_config", return_value=_auth_settings())
@patch(
    "pulp_tool.cli.artifact_pull_run.resolve_oci_transfer_artifact",
    side_effect=OrasPublishError("oras failed"),
)
def test_transfer_oci_oras_error_exits(
    _mock_resolve: MagicMock,
    _mock_auth: MagicMock,
    _mock_exit: MagicMock,
) -> None:
    with pytest.raises(SystemExit):
        run_artifact_pull_flow(_transfer_options())
