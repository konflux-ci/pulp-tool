"""
Transfer command for Pulp Tool CLI.

Downloads artifacts from a source (build Pulp or OCI ``pulp_results``) and promotes them to
release Pulp (Konflux artifact storage target), including optional side-tag test promotion and ORAS publish.
"""

import sys

import click

from ..models.artifact_pull_run import ArtifactPullRunOptions
from ..utils import setup_logging
from .artifact_pull_run import run_artifact_pull_flow


@click.command()
@click.option(
    "--artifact-location",
    help=(
        "Path to pulp_results.json, Pulp content HTTPS URL, or OCI manifest ref (repo@sha256:… or oci:…). "
        "Mutually exclusive with --build-id + --namespace."
    ),
)
@click.option(
    "--content-types",
    help=("Comma-separated list of content types to pull (rpm,log,sbom). If not specified, all types are pulled."),
)
@click.option(
    "--archs",
    help=(
        "Comma-separated list of architectures to pull (e.g., x86_64,aarch64,noarch). "
        "If not specified, all architectures are pulled."
    ),
)
@click.option(
    "--cert-path",
    type=click.Path(exists=True),
    help="Path to SSL certificate file for source distribution auth (optional)",
)
@click.option(
    "--key-path",
    type=click.Path(exists=True),
    help="Path to SSL private key file for source distribution auth (optional)",
)
@click.option(
    "--source-config",
    type=click.Path(exists=True),
    help=(
        "Pulp config for the build/source domain (download auth and auto-generated pulp_results URL). "
        "When omitted, global --config is used for source metadata if it differs from the destination."
    ),
)
@click.option(
    "--distribution-config",
    type=click.Path(exists=True),
    help=(
        "Path to config file for distribution download auth (cert/key or username/password). "
        "Overrides --source-config and destination --config for download auth only."
    ),
)
@click.option(
    "--side-tag",
    help=(
        "Side-tag name for an extra release-Pulp RPM repository/distribution during transfer. "
        "Requires destination --config and --oci-storage."
    ),
)
@click.option(
    "--oci-storage",
    help="OCI registry for ORAS publish (Konflux ociStorage).",
)
@click.option(
    "--artifact-results",
    help=(
        "Konflux comma-separated paths (url_path,digest_path) for OCI manifest Tekton results after side-tag transfer."
    ),
)
@click.option(
    "--snapshot-path",
    type=click.Path(),
    help=(
        "Path to Konflux release snapshot JSON in the trusted-artifact workspace. "
        "After ORAS publish, sets pulpResultsOciManifest for a following "
        "create-trusted-artifact step; required with --oras-cp-target or --pulp-oras-cp-target."
    ),
)
@click.option(
    "--oras-cp-target",
    help=(
        "After a successful transfer, oras cp the source OCI artifact to this target "
        "(Konflux ociStorage or repo:tag). Updates matching components[].containerImage "
        "in --snapshot-path (same trusted-artifact pattern as upload-src-rpm-sbom-attestation)."
    ),
)
@click.option(
    "--pulp-oras-cp-target",
    is_flag=True,
    help=(
        "After a successful transfer, create (if missing) or reuse a Pulp container distribution "
        "(registry path namespace/oci/build-id), oras cp the source bundle, and update matching "
        "components[].containerImage in --snapshot-path (mutually exclusive with --oras-cp-target)."
    ),
)
@click.option(
    "--oras-cp-source",
    help=(
        "Digest-pinned source ref for oras cp. Defaults to --artifact-location when it is an OCI manifest@sha256 ref."
    ),
)
@click.option(
    "--verify-rpm-gpg",
    is_flag=True,
    help=(
        "After download, verify RPM GPG signatures with rpm --checksig before destination upload. "
        "Also enabled when cli.verify_rpm_gpg is true in destination --config."
    ),
)
@click.option(
    "--gpg-keyring",
    type=click.Path(exists=True),
    help=(
        "GnuPG homedir with signing public keys (exported via gpg for rpm --checksig; mount from a Tekton Secret). "
        "Defaults to cli.gpg_keyring in destination --config when set."
    ),
)
@click.pass_context
def transfer(  # pylint: disable=too-many-positional-arguments
    ctx: click.Context,
    artifact_location: str | None,
    content_types: str | None,
    archs: str | None,
    cert_path: str | None,
    key_path: str | None,
    source_config: str | None,
    distribution_config: str | None,
    side_tag: str | None,
    artifact_results: str | None,
    snapshot_path: str | None,
    oras_cp_target: str | None,
    pulp_oras_cp_target: bool,
    oras_cp_source: str | None,
    oci_storage: str | None,
    verify_rpm_gpg: bool,
    gpg_keyring: str | None,
) -> None:
    """Download build artifacts and promote them to release Pulp (artifact storage target)."""
    dest_config = ctx.obj["config"]
    namespace = ctx.obj["namespace"]
    build_id = ctx.obj["build_id"]
    debug = ctx.obj["debug"]
    max_workers = ctx.obj["max_workers"]

    setup_logging(debug)

    dest_config_path = (dest_config or "").strip() or None
    if not dest_config_path:
        click.echo("Error: --config is required for transfer (release Pulp / rok-access credentials)", err=True)
        sys.exit(1)

    source_config_path = (source_config or "").strip() or dest_config_path

    run_artifact_pull_flow(
        ArtifactPullRunOptions(
            artifact_location=artifact_location,
            content_types=content_types,
            archs=archs,
            cert_path=cert_path,
            key_path=key_path,
            source_config_path=source_config_path,
            dest_config_path=dest_config_path,
            distribution_config=distribution_config,
            side_tag=side_tag,
            artifact_results=artifact_results,
            snapshot_path=snapshot_path,
            oras_cp_target=oras_cp_target,
            pulp_oras_cp_target=pulp_oras_cp_target,
            oras_cp_source=oras_cp_source,
            oci_storage=oci_storage,
            verify_rpm_gpg=verify_rpm_gpg,
            gpg_keyring=gpg_keyring,
            namespace=namespace,
            build_id=build_id,
            debug=debug,
            max_workers=max_workers,
            operation_label="transfer",
        )
    )


__all__ = ["transfer"]
