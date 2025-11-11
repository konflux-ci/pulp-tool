#!/usr/bin/env python3
"""
Unified CLI entry point for Pulp Tool operations using Click.

This module provides a single command-line interface with subcommands
for upload and transfer operations.
"""

import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found]

import click
import httpx

from .api import PulpClient, DistributionClient
from .utils import PulpHelper, setup_logging
from .transfer import (
    load_and_validate_artifacts,
    setup_repositories_if_needed,
    download_artifacts_concurrently,
    upload_downloaded_files_to_pulp,
    generate_transfer_report,
)
from .models.context import UploadContext, TransferContext
from ._version import __version__


# ============================================================================
# Common Click Options - Reusable decorators for shared options
# ============================================================================


def config_option(required=False):
    """Shared --config option for commands."""
    default_help = " (default: ~/.config/pulp/cli.toml)" if not required else ""
    return click.option(
        "--config",
        required=required,
        type=click.Path(exists=True),
        help=f"Path to Pulp CLI config file{default_help}",
    )


def debug_option():
    """Shared --debug option for verbosity control."""
    return click.option(
        "-d",
        "--debug",
        count=True,
        help="Increase verbosity (use -d for INFO, -dd for DEBUG, -ddd for DEBUG with HTTP logs)",
    )


def cert_auth_options():
    """Shared certificate authentication options."""

    def decorator(func):
        func = click.option(
            "--cert_path",
            type=click.Path(exists=True),
            help="Path to SSL certificate file for authentication (optional)",
        )(func)
        func = click.option(
            "--key_path",
            type=click.Path(exists=True),
            help="Path to SSL private key file for authentication (optional)",
        )(func)
        return func

    return decorator


# ============================================================================
# CLI Group and Commands
# ============================================================================


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="pulp-tool")
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Path to Pulp CLI config file (default: ~/.config/pulp/cli.toml)",
)
@click.option(
    "--cert-path",
    type=click.Path(exists=True),
    help="Path to SSL certificate file for authentication (optional)",
)
@click.option(
    "--key-path",
    type=click.Path(exists=True),
    help="Path to SSL private key file for authentication (optional)",
)
@click.option(
    "--build-id",
    help="Build identifier (required for some commands)",
)
@click.option(
    "--namespace",
    help="Namespace for the build (required for some commands)",
)
@click.option(
    "-d",
    "--debug",
    count=True,
    help="Increase verbosity (use -d for INFO, -dd for DEBUG, -ddd for DEBUG with HTTP logs)",
)
@click.option(
    "--max-workers",
    type=int,
    default=4,
    help="Maximum number of concurrent workers (default: 4)",
)
@click.pass_context
def cli(ctx, config, cert_path, key_path, build_id, namespace, debug, max_workers):
    """Pulp Tool - Upload and transfer artifacts to/from Pulp repositories."""
    # Store shared options in context for subcommands to access
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    ctx.obj["cert_path"] = cert_path
    ctx.obj["key_path"] = key_path
    ctx.obj["build_id"] = build_id
    ctx.obj["namespace"] = namespace
    ctx.obj["debug"] = debug
    ctx.obj["max_workers"] = max_workers


# ============================================================================
# Upload Command - Upload RPMs, logs, and SBOM files to Pulp
# ============================================================================


@cli.command()
@click.option("--parent-package", required=True, help="Parent package name")
@click.option("--rpm-path", required=True, type=click.Path(exists=True), help="Path to directory containing RPM files")
@click.option("--sbom-path", required=True, type=click.Path(exists=True), help="Path to SBOM file")
@click.option(
    "--cert-config",
    type=click.Path(exists=True),
    help="Path to certificate config file for base URL construction",
)
@click.option(
    "--artifact-results",
    help="Comma-separated paths for Konflux artifact results location (url_path,digest_path)",
)
@click.option("--sbom-results", type=click.Path(), help="Path to write SBOM results")
@click.pass_context
def upload(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    ctx,
    parent_package: str,
    rpm_path: str,
    sbom_path: str,
    cert_config: Optional[str],
    artifact_results: Optional[str],
    sbom_results: Optional[str],
):
    """Upload RPMs, logs, and SBOM files to Pulp repositories."""
    # Get shared options from context
    build_id = ctx.obj["build_id"]
    namespace = ctx.obj["namespace"]
    config = ctx.obj["config"]
    debug = ctx.obj["debug"]

    # Validate required options
    if not build_id:
        click.echo("Error: --build-id is required for upload command", err=True)
        ctx.exit(1)
    if not namespace:
        click.echo("Error: --namespace is required for upload command", err=True)
        ctx.exit(1)

    setup_logging(debug, use_wrapping=True)

    client = None
    try:
        # Initialize client and timestamp
        # The namespace/domain will be read from the config file
        client = PulpClient.create_from_config_file(path=config)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # Create context object with generated date_str
        args = UploadContext(
            build_id=build_id,
            date_str=date_str,
            namespace=namespace,
            parent_package=parent_package,
            rpm_path=rpm_path,
            sbom_path=sbom_path,
            config=config,
            cert_config=cert_config,
            artifact_results=artifact_results,
            sbom_results=sbom_results,
            debug=debug,
        )

        # Setup repositories using helper
        # Namespace is automatically read from config file via client
        repository_helper = PulpHelper(client, cert_config, parent_package=parent_package)
        repositories = repository_helper.setup_repositories(build_id)
        logging.info("Repository setup completed")

        # Process uploads
        logging.info("Starting upload process")
        results_json_url = repository_helper.process_uploads(client, args, repositories)

        # Check if results JSON URL was generated successfully
        if not results_json_url:
            logging.error("Upload completed but results JSON was not created")
            sys.exit(1)

        logging.info("All operations completed successfully")

        # Report the results JSON URL
        click.echo("\n" + "=" * 80)
        click.echo(f"RESULTS JSON URL: {results_json_url}")
        if not artifact_results:
            click.echo("NOTE: Results JSON created but not written to Konflux artifact files")
            click.echo("      Use --artifact_results to specify file paths for Konflux integration")
        click.echo("=" * 80)

        sys.exit(0)

    except httpx.HTTPError as e:
        logging.error("Fatal error during execution: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
        sys.exit(1)
    except Exception as e:
        logging.error("Unexpected error during upload: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
        sys.exit(1)
    finally:
        # Ensure client session is properly closed
        if client:
            client.close()
            logging.debug("Client session closed")


# ============================================================================
# Transfer Command - Download artifacts and optionally re-upload to Pulp
# ============================================================================


@cli.command()
@click.option(
    "--artifact-location",
    help="Path to local artifact metadata JSON file or HTTP URL. Mutually exclusive with --build-id + --namespace.",
)
@click.option(
    "--content-types",
    help=(
        "Comma-separated list of content types to transfer (rpm,log,sbom). "
        "If not specified, all types are transferred."
    ),
)
@click.option(
    "--archs",
    help=(
        "Comma-separated list of architectures to transfer (e.g., x86_64,aarch64,noarch). "
        "If not specified, all architectures are transferred."
    ),
)
@click.pass_context
def transfer(  # pylint: disable=too-many-positional-arguments
    ctx,
    artifact_location: Optional[str],
    content_types: Optional[str],
    archs: Optional[str],
):
    """Download artifacts and optionally re-upload to Pulp repositories."""
    # Get shared options from context
    namespace = ctx.obj["namespace"]
    cert_path = ctx.obj["cert_path"]
    key_path = ctx.obj["key_path"]
    config = ctx.obj["config"]
    build_id = ctx.obj["build_id"]
    debug = ctx.obj["debug"]
    max_workers = ctx.obj["max_workers"]

    setup_logging(debug)

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

        if not config:
            click.echo("Error: --config is required when using --build-id and --namespace", err=True)
            sys.exit(1)

        # Load config to get base_url
        config_path = Path(config).expanduser()
        with open(config_path, "rb") as fp:
            config_data = tomllib.load(fp)
        base_url = config_data["cli"]["base_url"]

        # Construct artifact_location URL
        artifact_location = f"{base_url}/api/pulp-content/{namespace}/{build_id}/artifacts/pulp_results.json"
        logging.info("Auto-generated artifact location: %s", artifact_location)

    elif not artifact_location:
        click.echo("Error: Either --artifact-location OR (--build-id AND --namespace) must be provided", err=True)
        sys.exit(1)

    # Parse comma-separated filters
    content_types_list = [ct.strip() for ct in content_types.split(",")] if content_types else None
    archs_list = [arch.strip() for arch in archs.split(",")] if archs else None

    # Create context object
    args = TransferContext(
        artifact_location=artifact_location,
        namespace=namespace,
        cert_path=cert_path,
        key_path=key_path,
        config=config,
        build_id=build_id,
        debug=debug,
        max_workers=max_workers,
        content_types=content_types_list,
        archs=archs_list,
    )

    try:
        # Check if artifact_location is a remote URL
        is_remote = artifact_location.startswith(("http://", "https://"))

        # Validate that cert_path and key_path are provided for remote URLs
        if is_remote and (not cert_path or not key_path):
            logging.error("--cert_path and --key_path are required when artifact_location is a remote URL")
            sys.exit(1)

        # Initialize distribution client only if needed
        distribution_client = None
        if cert_path and key_path:
            logging.info("Initializing distribution client...")
            distribution_client = DistributionClient(cert_path, key_path)

        # Load artifact metadata and validate
        artifact_data = load_and_validate_artifacts(args, distribution_client)

        # Set up repositories if configuration is provided
        pulp_client = setup_repositories_if_needed(args, artifact_data.artifact_json)  # type: ignore[arg-type]

        # Process artifacts by type
        distros = artifact_data.artifact_json.distributions  # pylint: disable=no-member

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
        if pulp_client:
            logging.info("Uploading downloaded files to Pulp repositories...")
            upload_info = upload_downloaded_files_to_pulp(pulp_client, download_result.pulled_artifacts, args)
        else:
            logging.info("No Pulp client available, skipping upload to repositories")
            upload_info = None

        # Generate and display transfer report
        generate_transfer_report(
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
            logging.error("Transfer completed with errors:")
            for msg in error_messages:
                logging.error("  - %s", msg)
            sys.exit(1)

        logging.info("All operations completed successfully")

    except httpx.HTTPError as e:
        logging.error("Fatal error during execution: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
        sys.exit(1)
    except Exception as e:
        logging.error("Unexpected error during transfer: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
        sys.exit(1)
    finally:
        # Ensure pulp client session is properly closed if it was created
        if "pulp_client" in locals() and pulp_client:
            pulp_client.close()
            logging.debug("PulpClient session closed")


# ============================================================================
# Get Repo Config Command - Download .repo file from Pulp distribution
# ============================================================================


@cli.command()
@click.option(
    "--base-url",
    help="Pulp base URL (e.g., https://pulp.example.com). Alternative to --config.",
)
@click.option(
    "--output",
    type=click.Path(),
    help="Output directory for .repo files (default: current directory). Files named {build_id}.repo",
)
@click.pass_context
def get_repo_md(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    ctx,
    base_url: Optional[str],
    output: Optional[str],
):
    """Download .repo configuration file(s) from Pulp RPM distributions.

    Supports downloading multiple .repo files by providing comma-separated
    build IDs with --build_id.

    Either provide --config OR both --base_url and --namespace.
    """
    # Get shared options from context
    config = ctx.obj["config"]
    namespace = ctx.obj["namespace"]
    build_id = ctx.obj["build_id"]
    cert_path = ctx.obj["cert_path"]
    key_path = ctx.obj["key_path"]
    debug = ctx.obj["debug"]

    # Validate required option
    if not build_id:
        click.echo("Error: --build-id is required for get-repo-md command", err=True)
        ctx.exit(1)

    setup_logging(debug)

    distribution_client = None
    successful_downloads = []
    failed_downloads = []

    try:
        # Validate certificate/key pair
        if (cert_path and not key_path) or (key_path and not cert_path):
            logging.error("Both --cert-path and --key-path must be provided together")
            sys.exit(1)

        # Validate that either config OR (base-url AND namespace) are provided
        has_config = config is not None
        has_direct_params = base_url is not None and namespace is not None

        if not has_config and not has_direct_params:
            # Try default config path as fallback
            default_config = Path("~/.config/pulp/cli.toml").expanduser()
            if default_config.exists():
                config = str(default_config)
                has_config = True
                logging.debug("Using default config path: %s", config)
            else:
                logging.error("Must provide either --config OR both --base_url and --namespace")
                sys.exit(1)

        if has_config and has_direct_params:
            logging.error("Cannot use both --config and --base_url/--namespace. Choose one approach.")
            sys.exit(1)

        # Parse comma-delimited build IDs
        build_ids = [bid.strip() for bid in build_id.split(",") if bid.strip()]

        if not build_ids:
            logging.error("No valid build IDs provided")
            sys.exit(1)

        # Only RPM repositories support .repo files
        repo_type = "rpms"

        logging.info("Build IDs: %s", ", ".join(build_ids))
        logging.info("Repository type: %s", repo_type)

        # Get base_url and namespace from config or command line
        if has_config:
            # Load from config file
            config_path = Path(config).expanduser()
            with open(config_path, "rb") as fp:
                config_data = tomllib.load(fp)

            base_url = config_data["cli"]["base_url"]
            namespace = config_data.get("cli", {}).get("domain", "")

            if not namespace:
                logging.error("No domain/namespace found in config file")
                sys.exit(1)

            logging.info("Loaded from config: %s", config)
        else:
            # Use command line parameters (already validated above)
            logging.info("Using command line parameters")

        logging.info("Using namespace: %s", namespace)
        logging.info("Using base URL: %s", base_url)

        # Determine output directory
        output_dir = Path(output) if output else Path.cwd()
        if output and not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
            logging.info("Created output directory: %s", output_dir)

        # Initialize distribution client if using certificates
        if cert_path and key_path:
            logging.debug("Using authenticated requests with certificates")
            distribution_client = DistributionClient(cert_path, key_path)

        # Download .repo files for all build IDs
        total_downloads = len(build_ids)
        logging.info("Downloading %d .repo file(s)", total_downloads)

        for bid in build_ids:
            # Define filename early for error handling
            filename = f"{bid}.repo"

            try:
                # Construct distribution URL for RPM repository
                # Format: {base_url}/api/pulp-content/{build_id}/rpms/
                distribution_url = f"{base_url}/api/pulp-content/{namespace}/{bid}/{repo_type}/"
                repo_file_url = f"{distribution_url}config.repo"

                logging.debug("Fetching .repo file from: %s", repo_file_url)

                # Download the .repo file
                if distribution_client:
                    response = distribution_client.pull_artifact(repo_file_url)
                else:
                    # Use basic httpx for unauthenticated requests
                    logging.debug("Using unauthenticated request")
                    response = httpx.get(repo_file_url, timeout=30.0)

                response.raise_for_status()

                # Determine output path
                output_path = output_dir / filename

                # Save the file
                with open(output_path, "wb") as f:
                    f.write(response.content)

                successful_downloads.append((bid, output_path))
                logging.info("Downloaded: %s", filename)

            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}"
                if e.response.status_code == 404:
                    error_msg += " (not found)"
                elif e.response.status_code == 403:
                    error_msg += " (access denied)"
                elif e.response.status_code == 401:
                    error_msg += " (unauthorized - authentication required)"
                failed_downloads.append((bid, error_msg))
                logging.warning("Failed to download %s: %s", filename, error_msg)

            except Exception as e:
                error_msg = str(e)
                failed_downloads.append((bid, error_msg))
                logging.warning("Failed to download %s: %s", filename, error_msg)

        # Print summary
        click.echo(f"\n{'=' * 80}")
        click.echo(f"Download Summary: {len(successful_downloads)} succeeded, {len(failed_downloads)} failed")
        click.echo(f"{'=' * 80}")

        if successful_downloads:
            click.echo("\nSuccessfully downloaded:")
            for bid, path in successful_downloads:
                click.echo(f"  ✓ {path.name} -> {path.absolute()}")

            click.echo("\nTo use these repositories, copy the files to /etc/yum.repos.d/:")
            if len(successful_downloads) == 1:
                click.echo(f"  sudo cp {successful_downloads[0][1]} /etc/yum.repos.d/")
            else:
                click.echo(f"  sudo cp {output_dir}/*.repo /etc/yum.repos.d/")

        if failed_downloads:
            click.echo("\nFailed downloads:")
            for bid, error in failed_downloads:
                click.echo(f"  ✗ {bid}.repo: {error}")

        # Exit with appropriate code
        if failed_downloads and not successful_downloads:
            sys.exit(1)  # All downloads failed
        elif failed_downloads:
            sys.exit(2)  # Partial success
        else:
            sys.exit(0)  # All succeeded

    except FileNotFoundError as e:
        logging.error("Config file not found: %s", e)
        sys.exit(1)
    except KeyError as e:
        logging.error("Missing required configuration in config file: %s", e)
        sys.exit(1)
    except IOError as e:
        logging.error("Failed to write .repo file(s): %s", e)
        sys.exit(1)
    except Exception as e:
        logging.error("Unexpected error: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
        sys.exit(1)
    finally:
        # Clean up distribution client if it was created
        if distribution_client and hasattr(distribution_client, "session"):
            distribution_client.session.close()
            logging.debug("Distribution client session closed")


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    """Main entry point for the CLI."""
    try:
        cli()  # pylint: disable=no-value-for-parameter  # Click handles parameters
    except KeyboardInterrupt:
        click.echo("\n\nOperation cancelled by user", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
