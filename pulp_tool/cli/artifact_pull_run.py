"""Shared download (pull) and promote-to-destination (transfer) CLI execution."""

from __future__ import annotations

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
from ..models.artifact_pull_run import ArtifactPullRunOptions
from ..services.pull_service import PullService
from ..utils.error_handling import handle_generic_error, handle_http_error
from ..utils.oci_pull import is_oci_artifact_reference, resolve_oci_transfer_artifact
from ..utils.oras_publish import OrasPublishError


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


def run_artifact_pull_flow(options: ArtifactPullRunOptions) -> None:
    """Run load → download → optional destination upload; exits the process on failure."""
    side_tag = options.resolve_side_tag()
    if not side_tag.ok:
        click.echo(side_tag.error_message, err=True)
        sys.exit(1)

    gpg = options.resolve_gpg()

    auth = load_distribution_auth_from_config(
        auth_config_path=options.distribution_auth_config_path(),
        cert_path=options.cert_path,
        key_path=options.key_path,
    )

    distribution_client: DistributionClient | None = None
    run_result = None
    try:
        with oci_pull_tempdir() as oci_dir:
            oci_bundle_dir: str | None = None
            try:
                loc = options.artifact_location
                if loc and is_oci_artifact_reference(loc) and options.operation_label == "transfer":
                    try:
                        resolution = resolve_oci_transfer_artifact(loc, oci_dir)
                    except OrasPublishError as e:
                        raise PullRunnerError(str(e)) from e
                    if resolution.kind == "oci_bundle" and resolution.bundle_dir is not None:
                        oci_bundle_dir = str(resolution.bundle_dir)
                        resolved_location = None
                    elif resolution.pulp_results_path is not None:
                        resolved_location = str(resolution.pulp_results_path)
                    else:
                        raise PullRunnerError(f"OCI transfer resolution failed for {loc!r}")
                else:
                    resolved_location = resolve_artifact_location_for_pull(
                        artifact_location=options.artifact_location,
                        namespace=options.namespace,
                        build_id=options.build_id,
                        source_config_path=options.source_config_path,
                        dest_config_path=options.dest_config_path,
                        oci_dest_dir=(
                            oci_dir
                            if options.artifact_location and is_oci_artifact_reference(options.artifact_location)
                            else None
                        ),
                    )
            except PullRunnerError as e:
                click.echo(f"Error: {e.message}", err=True)
                sys.exit(1)

            auth = resolve_pulp_api_base_url_for_remote(
                artifact_location=resolved_location or oci_bundle_dir or "",
                auth=auth,
                fallback_config_paths=(
                    options.dest_config_path,
                    options.source_config_path,
                    options.distribution_config,
                ),
            )
            if resolved_location:
                try:
                    validate_remote_pull_auth(resolved_location, auth)
                except PullRunnerError as e:
                    logging.error("%s", e.message)
                    sys.exit(1)

            oras_cp_source = (options.oras_cp_source or "").strip() or None
            if not oras_cp_source and loc and is_oci_artifact_reference(loc):
                oras_cp_source = loc.strip()

            pull_context = options.to_pull_context(
                resolved_artifact_location=resolved_location,
                auth_key_path=auth.key_path,
                side_tag=side_tag,
                gpg=gpg,
                oci_intermediate_bundle_dir=oci_bundle_dir,
                delete_local_sources_after_upload=bool(oci_bundle_dir),
                oras_cp_source=oras_cp_source,
            )

            distribution_client = _build_distribution_client(auth)
            try:
                run_result = PullService().run(
                    pull_context,
                    distribution_client=distribution_client,
                    max_workers=options.max_workers,
                )
            except httpx.HTTPError as e:
                handle_http_error(e, f"{options.operation_label} operation")
                sys.exit(1)
            except Exception as e:
                handle_generic_error(e, f"{options.operation_label} operation")
                sys.exit(1)
    finally:
        if run_result and run_result.pulp_client:
            run_result.pulp_client.close()
            logging.debug("PulpClient session closed")
        if distribution_client and hasattr(distribution_client, "session"):
            distribution_client.session.close()
            logging.debug("Distribution client session closed")

    if run_result and not run_result.success:
        logging.error("%s completed with errors:", options.operation_label.capitalize())
        for msg in run_result.error_messages:
            logging.error("  - %s", msg)
        sys.exit(1)

    logging.info("All operations completed successfully")


__all__ = ["ArtifactPullRunOptions", "run_artifact_pull_flow"]
