"""
Upload-build command for Pulp Tool CLI.

Uploads RPMs, logs, and SBOM files to Pulp and ORAS-publishes ``pulp_results.json`` when configured.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import click
import httpx

from ..api import PulpClient
from ..models.context import UploadRpmContext
from ..services.upload_service import scan_results_json_for_log_and_sbom_keys
from ..utils import PulpHelper, setup_logging
from ..utils.error_handling import handle_generic_error, handle_http_error
from ..utils.oci_storage_resolve import resolve_oci_storage
from ..utils.uploads import rpm_directory_has_log_files


def _extract_build_id_namespace_from_results_json(results_json_path: Path) -> tuple[str, str]:
    """
    Extract build_id and namespace from artifact labels in pulp_results.json.

    Returns:
        Tuple of (build_id, namespace)

    Raises:
        click.ClickException: If JSON cannot be read or labels are missing
    """
    try:
        with open(results_json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise click.ClickException(f"Failed to read results JSON {results_json_path}: {e}") from e

    artifacts = data.get("artifacts", {})
    for _key, info in artifacts.items():
        if isinstance(info, dict):
            labels = info.get("labels") or {}
            bid = labels.get("build_id", "").strip()
            ns = labels.get("namespace", "").strip()
            if bid and ns:
                return (bid, ns)

    raise click.ClickException(
        "Results JSON has no artifacts with build_id and namespace in labels. "
        "Provide --build-id and --namespace explicitly."
    )


@click.command("upload-build")
@click.option(
    "--parent-package",
    required=False,
    help="Parent package name (optional, will not be added to labels if not provided)",
)
@click.option(
    "--rpm-path",
    required=False,
    type=click.Path(exists=True),
    help="Path to directory containing RPM files (defaults to current directory if not provided)",
)
@click.option(
    "--sbom-path",
    required=False,
    type=click.Path(exists=True),
    help="Path to SBOM file (optional, SBOM upload will be skipped if not provided)",
)
@click.option(
    "--artifact-results",
    help=(
        "Konflux: comma-separated paths (url_path,digest_path). "
        "Or a folder path to save pulp_results.json locally instead of uploading to Pulp."
    ),
)
@click.option(
    "--oci-storage",
    help=(
        "OCI registry for ORAS publish of pulp_results.json (Konflux pipeline param ociStorage). "
        "Overrides cli.oci_storage in --config when both are set."
    ),
)
@click.option("--sbom-results", type=click.Path(), help="Path to write SBOM results")
@click.option(
    "--results-json",
    type=click.Path(exists=True, path_type=Path),
    help=(
        "Path to pulp_results.json; upload artifacts from this file "
        "(files resolved from its directory or --files-base-path)"
    ),
)
@click.option(
    "--files-base-path",
    type=click.Path(exists=True, path_type=Path),
    help="Base path for resolving artifact keys to file paths (default: directory of --results-json)",
)
@click.option(
    "--signed-by",
    help=(
        "Add pulp_label signed_by and upload to separate signed repos/distributions. "
        "Commas become ':' and '(' / ')' become '[' / ']' so Pulp accepts the label."
    ),
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help=(
        "RPM only: before uploading, search Pulp by each local RPM's NVRA filename (and signed_by if set) "
        "and remove matching package units from the target RPM repository via remove_content_units"
    ),
)
@click.option(
    "--target-arch-repo",
    is_flag=True,
    default=False,
    help=(
        "RPM only: use each architecture as the RPM repository/distribution name "
        "(e.g. .../pulp-content/{namespace}/x86_64/Packages/...) instead of {build}/rpms; "
        "logs/SBOM/artifacts stay build-scoped. With --signed-by, same arch repo; signed_by is label-only."
    ),
)
@click.pass_context
def upload_build(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    ctx: click.Context,
    parent_package: str | None,
    rpm_path: str | None,
    sbom_path: str | None,
    artifact_results: str | None,
    oci_storage: str | None,
    sbom_results: str | None,
    results_json: Path | None,
    files_base_path: Path | None,
    signed_by: str | None,
    overwrite: bool,
    target_arch_repo: bool,
) -> None:
    """Upload RPMs, logs, and SBOM files to Pulp (and ORAS when ``--oci-storage`` or config is set)."""
    # Get shared options from context
    build_id = ctx.obj.get("build_id") or ""
    namespace = ctx.obj.get("namespace") or ""
    config = ctx.obj["config"]
    debug = ctx.obj["debug"]

    # When using --results-json, build_id and namespace can be extracted from the JSON
    if results_json:
        if not build_id or not namespace:
            build_id, namespace = _extract_build_id_namespace_from_results_json(results_json)
    else:
        # Without --results-json, build_id and namespace are required
        if not build_id:
            click.echo("Error: --build-id is required for upload-build command", err=True)
            ctx.exit(1)
        if not namespace:
            click.echo("Error: --namespace is required for upload-build command", err=True)
            ctx.exit(1)

    if files_base_path is not None and results_json is None:
        click.echo("Error: --files-base-path can only be used with --results-json", err=True)
        ctx.exit(1)

    # Set default rpm_path to current directory if not provided (ignored when --results-json used)
    if not rpm_path:
        rpm_path = os.getcwd()

    if results_json:
        json_logs, json_sbom = scan_results_json_for_log_and_sbom_keys(str(results_json))
        needs_logs = json_logs
        needs_sbom = json_sbom or bool(sbom_path and str(sbom_path).strip())
    else:
        needs_logs = rpm_directory_has_log_files(rpm_path)
        needs_sbom = bool(sbom_path and str(sbom_path).strip())
    skip_logs_repo = not needs_logs
    skip_sbom_repo = not needs_sbom

    setup_logging(debug, use_wrapping=True)

    client = None
    try:
        # Initialize client and timestamp
        # The namespace/domain will be read from the config file
        client = PulpClient.create_from_config_file(
            path=config,
            correlation_namespace=namespace or None,
            correlation_build_id=build_id or None,
        )
        date_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

        resolved_oci_storage = resolve_oci_storage(oci_storage, config)

        # Create context object with generated date_str
        args = UploadRpmContext(
            build_id=build_id,
            date_str=date_str,
            namespace=namespace,
            parent_package=parent_package,
            rpm_path=rpm_path,
            sbom_path=sbom_path,
            config=config,
            artifact_results=artifact_results,
            oci_storage=resolved_oci_storage,
            sbom_results=sbom_results,
            results_json=str(results_json) if results_json else None,
            files_base_path=str(files_base_path) if files_base_path else None,
            signed_by=signed_by.strip() if signed_by and signed_by.strip() else None,
            overwrite=overwrite,
            target_arch_repo=target_arch_repo,
            debug=debug,
            skip_logs_repo=skip_logs_repo,
            skip_sbom_repo=skip_sbom_repo,
        )

        # Setup repositories using helper
        # Namespace is automatically read from config file via client
        # Skip artifacts repo when saving results locally (folder path, no comma)
        skip_artifacts = bool(args.artifact_results and "," not in args.artifact_results.strip())
        repository_helper = PulpHelper(client, parent_package=parent_package)
        repositories = repository_helper.setup_repositories(
            build_id,
            signed_by=args.signed_by,
            skip_artifacts_repo=skip_artifacts,
            target_arch_repo=args.target_arch_repo,
            skip_logs_repo=skip_logs_repo,
            skip_sbom_repo=skip_sbom_repo,
        )
        logging.info("Repository setup completed")

        # Process uploads
        logging.info("Starting upload process")
        results_json_url = repository_helper.process_uploads(client, args, repositories, pulp_helper=repository_helper)

        # Check if results JSON URL was generated successfully
        if not results_json_url:
            logging.error("Upload completed but results JSON was not created")
            sys.exit(1)

        logging.info("All operations completed successfully")

        # Report the results JSON location (URL or local path)
        click.echo("\n" + "=" * 80)
        click.echo(f"RESULTS JSON: {results_json_url}")
        if resolved_oci_storage and artifact_results and "," in artifact_results.strip():
            url_path, digest_path = (part.strip() for part in artifact_results.split(",", 1))
            try:
                oci_image_url = Path(url_path).read_text(encoding="utf-8").strip()
                oci_digest = Path(digest_path).read_text(encoding="utf-8").strip()
                click.echo(f"KONFLUX OCI IMAGE URL: {oci_image_url}")
                click.echo(f"KONFLUX OCI IMAGE DIGEST: {oci_digest}")
            except OSError:
                logging.debug("Could not read Konflux OCI result files after upload", exc_info=True)
        elif not artifact_results:
            click.echo("NOTE: Results JSON created but not written to Konflux artifact files")
            if resolved_oci_storage:
                click.echo(
                    "      Use --artifact-results url_path,digest_path for Tekton PULP-IMAGE_URL / PULP-IMAGE_DIGEST"
                )
            else:
                click.echo("      Use --artifact-results to specify file paths for Konflux or a folder to save locally")
        click.echo("=" * 80)

        sys.exit(0)

    except httpx.HTTPError as e:
        handle_http_error(e, "upload-build operation")
        sys.exit(1)
    except Exception as e:
        handle_generic_error(e, "upload-build operation")
        sys.exit(1)
    finally:
        # Ensure client session is properly closed
        if client:
            client.close()
            logging.debug("Client session closed")


__all__ = ["upload_build"]
