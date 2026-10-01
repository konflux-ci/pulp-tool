"""Update-build CLI: mutate and ORAS-publish versioned ``pulp_results.json``."""

from __future__ import annotations

import logging
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import click
import httpx

from ..api import PulpClient
from ..models.context import UploadRpmContext
from ..models.pulp_results import (
    BTS_UPDATE_OPERATION,
    BUILD_SIGN_OPERATION,
    RELEASE_SIGN_OPERATION,
)
from ..services.update_build import run_update_build
from ..utils import setup_logging
from ..utils.correlation import resolve_correlation_id
from ..utils.error_handling import handle_generic_error, handle_http_error
from ..utils.oci_storage_resolve import resolve_oci_storage


@click.command("update-build")
@click.option(
    "--results-json",
    required=True,
    type=str,
    help="Path or OCI manifest ref (@sha256:…) to existing pulp_results.json",
)
@click.option(
    "--artifact-results",
    required=True,
    type=str,
    help="Required Konflux url_path,digest_path Tekton result files after ORAS publish",
)
@click.option(
    "--files-base-path",
    type=click.Path(path_type=Path),
    help="Base path for artifact keys (default: workspace beside resolved JSON)",
)
@click.option(
    "--oci-storage",
    help="OCI registry for ORAS publish (Konflux ociStorage).",
)
@click.option(
    "--operation",
    default=BUILD_SIGN_OPERATION,
    show_default=True,
    type=click.Choice(
        [BUILD_SIGN_OPERATION, RELEASE_SIGN_OPERATION, BTS_UPDATE_OPERATION],
        case_sensitive=False,
    ),
    help="History operation label for this mutation",
)
@click.option(
    "--signed-by",
    help="Signer identity merged into pulp_labels.signed_by on uploaded RPMs",
)
@click.option(
    "--replace-signed-by",
    is_flag=True,
    help="Replace signed_by instead of semicolon merge",
)
@click.pass_context
def update_build(
    ctx: click.Context,
    results_json: str,
    artifact_results: str,
    files_base_path: Path | None,
    oci_storage: str | None,
    operation: str,
    signed_by: str | None,
    replace_signed_by: bool,
) -> None:
    """Upload signed RPMs / BTS outputs and publish an updated ``pulp_results.json`` OCI target."""
    config = ctx.obj.get("config")
    build_id = ctx.obj.get("build_id") or ""
    namespace = ctx.obj.get("namespace") or ""
    debug = ctx.obj.get("debug", 0)

    if not artifact_results.strip() or "," not in artifact_results:
        click.echo("Error: --artifact-results url_path,digest_path is required", err=True)
        sys.exit(1)

    setup_logging(debug, use_wrapping=True)

    cluster: str | None = None
    if config:
        try:
            from ..utils.config_manager import ConfigManager  # pylint: disable=import-outside-toplevel

            cm = ConfigManager(config)
            cm.load()
            raw = cm.get("cli.cluster")
            cluster = str(raw).strip() if raw else None
        except Exception as e:
            logging.debug("Could not read cli.cluster: %s", e)

    cid = resolve_correlation_id(namespace=namespace or None, build_id=build_id or None)
    if cid:
        logging.info("X-Correlation-ID: %s", cid)

    client = None
    oci_temp = tempfile.TemporaryDirectory(prefix="pulp-tool-update-build-")
    try:
        client = PulpClient.create_from_config_file(
            path=config,
            correlation_namespace=namespace or None,
            correlation_build_id=build_id or None,
        )
        date_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        resolved_oci = resolve_oci_storage(oci_storage, config)
        args = UploadRpmContext(
            build_id=build_id,
            date_str=date_str,
            namespace=namespace,
            config=config,
            artifact_results=artifact_results,
            oci_storage=resolved_oci,
            results_json=results_json.strip(),
            files_base_path=str(files_base_path) if files_base_path else None,
            signed_by=signed_by.strip() if signed_by and signed_by.strip() else None,
            debug=debug,
            cluster=cluster,
        )
        oci_ref = run_update_build(
            client,
            args,
            operation=operation,
            replace_signed_by=replace_signed_by,
            oci_temp_dir=Path(oci_temp.name),
        )
        if oci_ref:
            click.echo(f"OCI manifest: {oci_ref}")
    except httpx.HTTPError as e:
        handle_http_error(e, "update-build")
    except Exception as e:
        handle_generic_error(e, "update-build")
    finally:
        oci_temp.cleanup()
        if client is not None:
            client.close()


__all__ = ["update_build"]
