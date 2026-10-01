"""
Pull command for Pulp Tool CLI.

This module provides the pull command for downloading artifacts and optionally re-uploading to Pulp.
"""

import logging
import sys

import click
import httpx

from ..api import DistributionClient
from ..cli.runner_helpers import (
    DistributionAuthSettings,
    PullRunnerError,
    load_distribution_auth_from_config,
    oci_pull_tempdir,
    resolve_artifact_location_for_pull,
    resolve_pulp_api_base_url_for_remote,
    validate_remote_pull_auth,
)
from ..models.context import PullContext
from ..services.pull_service import PullService
from ..utils import setup_logging
from ..utils.config_manager import ConfigManager
from ..utils.error_handling import handle_generic_error, handle_http_error
from ..utils.oci_pull import is_oci_artifact_reference
from ..utils.oci_storage_resolve import resolve_oci_storage


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
    help="Path to SSL certificate file for authentication (optional, can come from --transfer-dest or --config)",
)
@click.option(
    "--key-path",
    type=click.Path(exists=True),
    help="Path to SSL private key file for authentication (optional, can come from --transfer-dest or --config)",
)
@click.option(
    "--transfer-dest",
    type=str,
    help=(
        "Path to Pulp config for the transfer target: destination API credentials and optional upload. "
        "When set, pull creates destination repositories/distributions (if needed) and re-uploads downloaded "
        "content. Omitted --transfer-dest with only --config downloads from distribution only."
    ),
)
@click.option(
    "--distribution-config",
    type=click.Path(exists=True),
    help=(
        "Path to config file for distribution auth (cert/key or username/password). "
        "If not set, auth is loaded from --transfer-dest or --config."
    ),
)
@click.option(
    "--side-tag",
    help=(
        "Side-tag name for an extra ROK RPM repository/distribution during transfer. "
        "Requires --transfer-dest and --oci-storage."
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
        "create-trusted-artifact step."
    ),
)
@click.pass_context
def pull(  # pylint: disable=too-many-positional-arguments
    ctx: click.Context,
    artifact_location: str | None,
    content_types: str | None,
    archs: str | None,
    cert_path: str | None,
    key_path: str | None,
    transfer_dest: str | None,
    distribution_config: str | None,
    side_tag: str | None,
    artifact_results: str | None,
    snapshot_path: str | None,
    oci_storage: str | None,
) -> None:
    """Download artifacts and optionally re-upload to Pulp repositories."""
    config = ctx.obj["config"]
    namespace = ctx.obj["namespace"]
    build_id = ctx.obj["build_id"]
    debug = ctx.obj["debug"]
    max_workers = ctx.obj["max_workers"]

    setup_logging(debug)

    side_tag_value = (side_tag or "").strip() or None
    if side_tag_value and not (transfer_dest and transfer_dest.strip()):
        click.echo("Error: --side-tag requires --transfer-dest", err=True)
        sys.exit(1)

    source_config_path = (config or "").strip() or None
    dest_config_path = (transfer_dest or "").strip() or None
    pulp_client_config_path = dest_config_path or source_config_path

    resolved_oci_storage: str | None = None
    cluster: str | None = None
    if side_tag_value and transfer_dest:
        resolved_oci_storage = resolve_oci_storage(oci_storage, transfer_dest)
        try:
            transfer_cfg = ConfigManager(transfer_dest)
            transfer_cfg.load()
            raw_cluster = transfer_cfg.get("cli.cluster")
            cluster = str(raw_cluster).strip() if raw_cluster else None
        except Exception as e:
            logging.debug("Could not load transfer-dest config for side-tag: %s", e)
        if not resolved_oci_storage:
            click.echo(
                "Error: --oci-storage in --transfer-dest is required when using --side-tag",
                err=True,
            )
            sys.exit(1)

    content_types_list = [ct.strip() for ct in content_types.split(",")] if content_types else None
    archs_list = [arch.strip() for arch in archs.split(",")] if archs else None

    auth_config_path = distribution_config or source_config_path or dest_config_path
    auth = load_distribution_auth_from_config(
        auth_config_path=auth_config_path,
        cert_path=cert_path,
        key_path=key_path,
    )

    distribution_client: DistributionClient | None = None
    run_result = None
    try:
        with oci_pull_tempdir() as oci_dir:
            try:
                resolved_location = resolve_artifact_location_for_pull(
                    artifact_location=artifact_location,
                    namespace=namespace,
                    build_id=build_id,
                    source_config_path=source_config_path,
                    dest_config_path=dest_config_path,
                    oci_dest_dir=(
                        oci_dir if artifact_location and is_oci_artifact_reference(artifact_location) else None
                    ),
                )
            except PullRunnerError as e:
                click.echo(f"Error: {e.message}", err=True)
                sys.exit(1)

            auth = resolve_pulp_api_base_url_for_remote(
                artifact_location=resolved_location,
                auth=auth,
                fallback_config_paths=(dest_config_path, source_config_path, distribution_config),
            )
            try:
                validate_remote_pull_auth(resolved_location, auth)
            except PullRunnerError as e:
                logging.error("%s", e.message)
                sys.exit(1)

            pull_context = PullContext(
                artifact_location=resolved_location,
                namespace=namespace,
                key_path=auth.key_path,
                config=pulp_client_config_path,
                transfer_dest=transfer_dest,
                build_id=build_id,
                side_tag=side_tag_value,
                artifact_results=artifact_results,
                oci_storage=resolved_oci_storage,
                snapshot_path=(snapshot_path or "").strip() or None,
                cluster=cluster,
                debug=debug,
                max_workers=max_workers,
                content_types=content_types_list,
                archs=archs_list,
            )

            distribution_client = _build_distribution_client(auth)
            try:
                run_result = PullService().run(
                    pull_context,
                    distribution_client=distribution_client,
                    max_workers=max_workers,
                )
            except httpx.HTTPError as e:
                handle_http_error(e, "pull operation")
                sys.exit(1)
            except Exception as e:
                handle_generic_error(e, "pull operation")
                sys.exit(1)
    finally:
        if run_result and run_result.pulp_client:
            run_result.pulp_client.close()
            logging.debug("PulpClient session closed")
        if distribution_client and hasattr(distribution_client, "session"):
            distribution_client.session.close()
            logging.debug("Distribution client session closed")

    if run_result and not run_result.success:
        logging.error("Pull completed with errors:")
        for msg in run_result.error_messages:
            logging.error("  - %s", msg)
        sys.exit(1)

    logging.info("All operations completed successfully")


def _build_distribution_client(auth: DistributionAuthSettings) -> DistributionClient | None:
    if not auth.has_any_auth:
        return None
    logging.info("Initializing distribution client...")
    if auth.has_cert_auth:
        return DistributionClient(
            cert=auth.cert_path,
            key=auth.key_path,
            pulp_api_base_url=auth.pulp_api_base_url,
        )
    return DistributionClient(
        username=auth.username,
        password=auth.password,
        pulp_api_base_url=auth.pulp_api_base_url,
    )


__all__ = ["pull"]
