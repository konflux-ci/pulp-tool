"""
Pull command for Pulp Tool CLI.

This module provides the pull command for downloading artifacts and optionally re-uploading to Pulp.
"""

import logging
import os
import sys
import tempfile
from pathlib import Path

import click
import httpx

from ..api import DistributionClient
from ..models.context import PullContext
from ..pull import (
    download_artifacts_concurrently,
    generate_pull_report,
    load_and_validate_artifacts,
    setup_repositories_if_needed,
    upload_downloaded_files_to_pulp,
)
from ..pull.publish import publish_side_tag_results
from ..pull.side_tag import upload_rpms_to_side_tag_repository
from ..utils import setup_logging
from ..utils.config_manager import ConfigManager
from ..utils.error_handling import handle_generic_error, handle_http_error
from ..utils.oci_pull import is_oci_artifact_reference, pull_pulp_results_json
from ..utils.oci_storage_resolve import resolve_oci_storage
from ..utils.oras_publish import OrasPublishError
from ..utils.validation.build_id import sanitize_build_id_for_repository, strip_namespace_from_build_id


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
        "Requires --transfer-dest and --oci-storage or cli.oci_storage."
    ),
)
@click.option(
    "--oci-storage",
    help="OCI registry for ORAS publish (Konflux ociStorage); overrides cli.oci_storage in --transfer-dest.",
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
    # Get shared options from context
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
    # Destination Pulp API config (--transfer-dest); source metadata/auth uses group-level --config.
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
                "Error: --oci-storage or cli.oci_storage in --transfer-dest config is required when using --side-tag",
                err=True,
            )
            sys.exit(1)

    # Validate mutually exclusive options
    if artifact_location and (namespace or build_id):
        click.echo("Error: Cannot use --artifact-location with --build-id and --namespace", err=True)
        sys.exit(1)

    # Generate artifact_location from build_id + namespace if needed
    if namespace or build_id:
        # Both must be provided together
        if not (namespace and build_id):
            click.echo("Error: Both --build-id and --namespace must be provided together", err=True)
            sys.exit(1)

        metadata_config_path = source_config_path or dest_config_path
        if not metadata_config_path:
            click.echo("Error: --config is required when using --build-id and --namespace", err=True)
            sys.exit(1)

        # Load source config for content base_url (see cli-reference: --config supplies base_url for auto URL)
        config_manager = ConfigManager(metadata_config_path)
        config_manager.load()
        base_url = config_manager.get("cli.base_url")

        # Construct artifact_location URL
        content_build_id = sanitize_build_id_for_repository(strip_namespace_from_build_id(build_id))
        artifact_location = f"{base_url}/api/pulp-content/{namespace}/{content_build_id}/artifacts/pulp_results.json"
        logging.info("Auto-generated artifact location: %s", artifact_location)

    elif not artifact_location:
        click.echo("Error: Either --artifact-location OR (--build-id AND --namespace) must be provided", err=True)
        sys.exit(1)

    oci_pull_temp: tempfile.TemporaryDirectory[str] | None = None
    if artifact_location and is_oci_artifact_reference(artifact_location):
        try:
            oci_pull_temp = tempfile.TemporaryDirectory(prefix="pulp-tool-oras-pull-")
            local_json = pull_pulp_results_json(artifact_location, Path(oci_pull_temp.name))
            logging.info("ORAS-pulled pulp_results.json to %s", local_json)
            artifact_location = str(local_json)
        except OrasPublishError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    # Parse comma-separated filters
    content_types_list = [ct.strip() for ct in content_types.split(",")] if content_types else None
    archs_list = [arch.strip() for arch in archs.split(",")] if archs else None

    # Auth for fetching source pulp_results (distribution); destination creds live in --transfer-dest.
    username: str | None = None
    password: str | None = None
    auth_config_path = distribution_config or source_config_path or dest_config_path
    if auth_config_path:
        try:
            config_manager = ConfigManager(auth_config_path)
            config_manager.load()
            if not cert_path:
                loaded_cert = config_manager.get("cli.cert")
                if loaded_cert and isinstance(loaded_cert, str) and loaded_cert.strip():
                    loaded_cert = loaded_cert.strip()
                    expanded_cert = os.path.expanduser(loaded_cert)
                    if os.path.exists(expanded_cert):
                        cert_path = expanded_cert
            if not key_path:
                loaded_key = config_manager.get("cli.key")
                if loaded_key and isinstance(loaded_key, str) and loaded_key.strip():
                    loaded_key = loaded_key.strip()
                    expanded_key = os.path.expanduser(loaded_key)
                    if os.path.exists(expanded_key):
                        key_path = expanded_key
            if username is None:
                username = config_manager.get("cli.username")
                username = str(username).strip() if username else None
            if password is None:
                password = config_manager.get("cli.password")
                password = str(password) if password is not None else None
        except Exception as e:
            logging.debug("Could not load auth from config: %s", e)

    # Check if artifact_location is a remote URL BEFORE creating context
    is_remote = artifact_location.startswith(("http://", "https://")) if artifact_location else False

    # Validate: for remote URLs, need (cert+key) OR (username+password)
    has_cert = cert_path and key_path
    has_basic = username is not None and password is not None
    if is_remote and not has_cert and not has_basic:
        logging.error(
            "Authentication required for remote URLs. Provide either (cert, key) or (username, password) "
            "via --distribution-config, --transfer-dest, --config, --cert-path, or --key-path."
        )
        sys.exit(1)

    # Create context object
    args = PullContext(
        artifact_location=artifact_location,
        namespace=namespace,
        key_path=key_path,
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

    try:
        # Initialize distribution client only if needed
        distribution_client = None
        if has_cert or has_basic:
            logging.info("Initializing distribution client...")
            if has_cert:
                distribution_client = DistributionClient(cert=cert_path, key=key_path)
            else:
                distribution_client = DistributionClient(username=username, password=password)

        # Load artifact metadata and validate
        artifact_data = load_and_validate_artifacts(args, distribution_client)

        # Set up repositories if configuration is provided
        destination_setup = setup_repositories_if_needed(args, artifact_data.artifact_json)
        pulp_client = destination_setup.client if destination_setup else None

        # Process artifacts by type
        distros = artifact_data.get_distributions()

        # Download artifacts concurrently
        download_result = download_artifacts_concurrently(
            artifact_data.artifacts,
            distros,
            distribution_client,
            max_workers,
            args.content_types,
            args.archs,
        )

        # Upload downloaded files to Pulp repositories if client is available
        upload_info = None
        if pulp_client:
            logging.info("Uploading downloaded files to Pulp repositories...")
            upload_info = upload_downloaded_files_to_pulp(
                pulp_client,
                download_result.pulled_artifacts,
                args,
                repositories=destination_setup.repositories if destination_setup else None,
            )
            if args.side_tag and upload_info:
                side_tag_upload = upload_rpms_to_side_tag_repository(
                    pulp_client,
                    download_result.pulled_artifacts,
                    artifact_data,
                    args,
                )
                publish_side_tag_results(
                    pulp_client,
                    artifact_data,
                    args,
                    upload_info,
                    side_tag_upload.transfers,
                    side_tag_distribution_base=side_tag_upload.distribution_base_url,
                )
        else:
            logging.info("No Pulp client available, skipping upload to repositories")

        # Generate and display pull report
        generate_pull_report(
            download_result.pulled_artifacts, download_result.completed, download_result.failed, args, upload_info
        )

        # Check for any errors and exit with error code if found
        has_errors = False
        error_messages = []

        # Check for download failures
        if download_result.failed > 0:
            has_errors = True
            error_messages.append(f"{download_result.failed} artifact download(s) failed")

        # Check for upload errors
        if upload_info and upload_info.has_errors:
            has_errors = True
            error_count = len(upload_info.upload_errors)
            error_messages.append(f"{error_count} upload error(s) occurred")

        if has_errors:
            logging.error("Pull completed with errors:")
            for msg in error_messages:
                logging.error("  - %s", msg)
            sys.exit(1)

        logging.info("All operations completed successfully")

    except httpx.HTTPError as e:
        handle_http_error(e, "pull operation")
        sys.exit(1)
    except Exception as e:
        handle_generic_error(e, "pull operation")
        sys.exit(1)
    finally:
        if oci_pull_temp is not None:
            oci_pull_temp.cleanup()
        # Ensure pulp client session is properly closed if it was created
        if "pulp_client" in locals() and pulp_client:
            pulp_client.close()
            logging.debug("PulpClient session closed")
        if distribution_client and hasattr(distribution_client, "session"):
            distribution_client.session.close()
            logging.debug("Distribution client session closed")


__all__ = ["pull"]
