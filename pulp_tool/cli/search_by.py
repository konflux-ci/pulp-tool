"""
Search-by command for Pulp Tool CLI.

This module provides the search-by command for finding RPM packages
in Pulp by checksum, filename, and/or signed_by. These options
can be used in combination or singularly. When multiple options are
used together (e.g. --filename X --signed-by "me"), results are
combined with AND semantics: only packages matching ALL criteria are returned.

Results.json format (--results-json input and --output-results output):
    Canonical pulp_results.json: document-level version, build_id, namespace, cluster;
    per-artifact pulp_labels, href, distributions.
    --results-json may be a local path or digest-pinned OCI ref (repo@sha256:…).

Artifact keys may be simple filenames (e.g. "pkg.rpm") or paths (e.g.
"namespace/build-id/sbom-merged.json"). Only entries whose key ends with
".rpm" are treated as RPMs and searched/removed. Output preserves the same
structure with found RPMs removed.
"""

import sys
from pathlib import Path

import click
import httpx

from ..models.pulp_label_values import normalize_signed_by_value_for_pulp
from ..services.search_by_service import (
    _collect_checksums_from_csv,
    _collect_filenames_from_csv,
    _run_direct_search,
    _run_results_json_mode,
)
from ..utils import setup_logging
from ..utils.error_handling import handle_generic_error, handle_http_error


@click.command("search-by")
@click.option(
    "-c",
    "--checksum",
    "use_checksum_from_file",
    is_flag=True,
    help="Use checksums extracted from results.json (requires --results-json)",
)
@click.option(
    "--checksums",
    "checksums",
    help="Comma-separated list of SHA256 checksums",
)
@click.option(
    "--filename",
    "use_filename_from_file",
    is_flag=True,
    help="Use filenames (artifact keys) extracted from results.json (requires --results-json)",
)
@click.option(
    "--filenames",
    "filenames",
    help="Comma-separated list of filenames (e.g. pkg-1.0-1.x86_64.rpm)",
)
@click.option(
    "--signed-by",
    "signed_by_key",
    help=(
        "Search for RPMs with this signed_by label value (e.g. key-id-123). "
        "Same substitution as upload: ','→':', parentheses→square brackets."
    ),
)
@click.option(
    "--results-json",
    type=str,
    help=("Path or OCI @sha256 ref to pulp_results.json to filter; extracts RPM checksums/filenames and removes found"),
)
@click.option(
    "--output-results",
    type=click.Path(path_type=Path),
    help="Path to write filtered results.json (required when --results-json is used)",
)
@click.option(
    "--keep-files",
    "keep_files",
    is_flag=True,
    default=False,
    help="Keep logs and sboms in output-results; when unset (default), only RPM artifacts are written",
)
@click.pass_context
def search_by(
    ctx: click.Context,
    use_checksum_from_file: bool,
    checksums: str | None,
    use_filename_from_file: bool,
    filenames: str | None,
    signed_by_key: str | None,
    results_json: str | None,
    output_results: Path | None,
    keep_files: bool,
) -> None:
    """Search for RPM packages in Pulp by checksum, filename, and/or signed_by."""
    config = ctx.obj["config"]
    debug = ctx.obj["debug"]
    setup_logging(debug, use_wrapping=True)

    if not config:
        click.echo("Error: --config is required for search-by", err=True)
        sys.exit(1)

    if use_checksum_from_file and results_json is None:
        click.echo("Error: --checksum requires --results-json", err=True)
        sys.exit(1)

    if use_filename_from_file and results_json is None:
        click.echo("Error: --filename requires --results-json", err=True)
        sys.exit(1)

    checksum_list = _collect_checksums_from_csv(checksums)
    filename_list = _collect_filenames_from_csv(filenames)
    signed_by_list = (
        [normalize_signed_by_value_for_pulp(signed_by_key.strip())] if signed_by_key and signed_by_key.strip() else []
    )

    if results_json is not None:
        if output_results is None:
            click.echo(
                "Error: --output-results is required when --results-json is used",
                err=True,
            )
            sys.exit(1)
        _run_results_json_mode(
            config,
            results_json,
            output_results,
            checksums=checksum_list,
            use_checksum_from_file=use_checksum_from_file,
            filenames=filename_list,
            use_filename_from_file=use_filename_from_file,
            signed_by=signed_by_list,
            keep_files=keep_files,
            correlation_namespace=ctx.obj.get("namespace") or None,
            correlation_build_id=ctx.obj.get("build_id") or None,
        )
        return

    if not checksum_list and not filename_list and not signed_by_list:
        click.echo(
            "Error: At least one of --checksum/--checksums, --filename/--filenames, or --signed-by must be provided",
            err=True,
        )
        sys.exit(1)

    try:
        _run_direct_search(
            config,
            checksums=checksum_list,
            filenames=filename_list,
            signed_by=signed_by_list,
            correlation_namespace=ctx.obj.get("namespace") or None,
            correlation_build_id=ctx.obj.get("build_id") or None,
        )
    except httpx.HTTPError as e:
        handle_http_error(e, "search by")
        sys.exit(1)
    except Exception as e:
        handle_generic_error(e, "search by")
        sys.exit(1)


__all__ = ["search_by"]
