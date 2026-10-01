"""Search-by orchestration (results JSON mode and direct Pulp search)."""

import copy
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import click
import httpx
from pydantic import ValidationError

from ..api import PulpClient
from ..cli.runner_helpers import PullRunnerError, resolve_results_json_local_path
from ..models.cli import FoundPackages, SearchByRequest, SearchByResultsJson
from ..models.pulp_api import RpmPackageResponse
from ..utils.error_handling import handle_generic_error, handle_http_error
from ..utils.rpm_operations import parse_rpm_filename_to_nvr, parse_rpm_filename_to_nvra
from ..utils.rpm_pulp_search import (
    search_pulp_by_filenames as _search_pulp_by_filenames,
)
from ..utils.rpm_pulp_search import (
    search_pulp_by_filenames_with_signed_by as _search_pulp_by_filenames_with_signed_by,
)
from ..utils.rpm_pulp_search import (
    search_pulp_by_signed_by as _search_pulp_by_signed_by,
)
from ..utils.rpm_pulp_search import (
    search_pulp_for_rpms as _search_pulp_for_rpms,
)
from ..utils.rpm_pulp_search import (
    search_pulp_for_rpms_with_signed_by as _search_pulp_for_rpms_with_signed_by,
)

SHA256_HEX_LENGTH = 64


def _collect_list(
    items: tuple[str, ...],
    csv: str | None,
    *,
    split_char: str = ",",
    normalize: str | None = None,
) -> list[str]:
    """Collect and deduplicate from repeated option and comma-separated string."""

    def _norm(s: str) -> str:
        s = s.strip()
        return s.lower() if normalize == "lower" else s

    result: list[str] = []
    seen: set[str] = set()
    for x in items:
        val = _norm(x)
        if val and val not in seen:
            result.append(val)
            seen.add(val)
    if csv:
        for x in csv.split(split_char):
            val = _norm(x)
            if val and val not in seen:
                result.append(val)
                seen.add(val)
    return result


def _collect_filenames_from_csv(filenames: str | None) -> list[str]:
    """Collect and deduplicate filenames from --filenames option."""
    return _collect_list((), filenames)


def _collect_checksums_from_csv(checksums: str | None) -> list[str]:
    """Collect and deduplicate checksums from --checksums option."""
    return _collect_list((), checksums, normalize="lower")


def _filenames_to_nvras_deduplicated(filenames: list[str]) -> list[tuple[str, str, str, str]]:
    """Convert filenames to NVRAs (name, version, release, arch), skip unparseable with warning, remove duplicates."""
    seen: set[tuple[str, str, str, str]] = set()
    result: list[tuple[str, str, str, str]] = []
    for fname in filenames:
        nvra = parse_rpm_filename_to_nvra(fname)
        if nvra is None:
            logging.warning("Skipping unparseable RPM filename: %s", fname)
            continue
        if nvra not in seen:
            seen.add(nvra)
            result.append(nvra)
    return result


# -----------------------------------------------------------------------------
# Pulp API (implementations in pulp_tool.utils.rpm_pulp_search)
# -----------------------------------------------------------------------------


def _log_packages_found(packages: list[RpmPackageResponse], max_log: int = 10) -> None:
    """Log packages found in Pulp at DEBUG; truncate when many to avoid log spam."""
    if not packages:
        return
    for pkg in packages[:max_log]:
        logging.debug(
            "RPM exists in Pulp: %s-%s-%s.%s (sha256:%s)",
            pkg.name,
            pkg.version,
            pkg.release,
            pkg.arch,
            pkg.pkgId,
        )
    if len(packages) > max_log:
        logging.debug("... and %d more package(s)", len(packages) - max_log)


def _filenames_to_nvrs_deduplicated(filenames: list[str]) -> list[tuple[str, str, str]]:
    """Convert filenames to NVRs (name, version, release), skip unparseable, remove duplicates."""
    seen: set[tuple[str, str, str]] = set()
    result: list[tuple[str, str, str]] = []
    for fname in filenames:
        nvr = parse_rpm_filename_to_nvr(fname)
        if nvr is None:
            continue
        if nvr not in seen:
            seen.add(nvr)
            result.append(nvr)
    return result


def _search_pulp_by_filenames_incremental(
    client: PulpClient,
    results_data: dict,
    signed_by: str | None,
    initial_filenames: list[str] | None = None,
) -> tuple[list[RpmPackageResponse], dict]:
    """
    Search Pulp by filename incrementally: one NVR per GET, remove found from results
    after each response, stop when no RPM artifacts remain (early termination).

    Tracks searched NVRs (not NVRAs) because the Pulp API query is by
    name+version+release and returns all arches. This lets a single API call
    remove artifacts for every arch of a given NVR, reducing redundant calls.

    When artifacts are empty (e.g. explicit --filenames), use initial_filenames.
    Returns (packages, filtered_results_data).
    """
    all_packages: list[RpmPackageResponse] = []
    current_data = results_data
    searched_nvrs: set[tuple[str, str, str]] = set()
    while True:
        results = SearchByResultsJson(current_data)
        filenames = results.extract_filenames() or (initial_filenames or [])
        if not filenames:
            break
        nvrs = _filenames_to_nvrs_deduplicated(filenames)
        nvrs_to_search = [nvr for nvr in nvrs if nvr not in searched_nvrs]
        if not nvrs_to_search:
            break
        n, v, r = nvrs_to_search[0]
        searched_nvrs.add((n, v, r))
        # Use the first filename matching this NVR for the query
        first_matching = next(
            (os.path.basename(f) for f in filenames if parse_rpm_filename_to_nvr(f) == (n, v, r)), None
        )
        if not first_matching:
            continue
        if signed_by:
            batch = _search_pulp_by_filenames_with_signed_by(client, [first_matching], signed_by)
        else:
            batch = _search_pulp_by_filenames(client, [first_matching])
        all_packages.extend(batch)
        found = FoundPackages.from_packages(batch)
        # Remove ALL artifacts sharing this NVR (any arch) in one pass
        only_remove = {os.path.basename(f) for f in filenames if parse_rpm_filename_to_nvr(f) == (n, v, r)}
        current_data = results.remove_found(found, only_remove_filenames=only_remove)
        artifacts = current_data.get("artifacts", {})
        if not any(SearchByResultsJson._is_rpm(k) for k in artifacts):
            break
    return (all_packages, current_data)


# -----------------------------------------------------------------------------
# Output formatting
# -----------------------------------------------------------------------------


def _packages_to_json(packages: list[RpmPackageResponse]) -> str:
    """Convert packages to JSON output."""
    data = [
        {
            "pkgId": pkg.pkgId,
            "pulp_href": pkg.pulp_href,
            "name": pkg.name,
            "epoch": pkg.epoch,
            "version": pkg.version,
            "release": pkg.release,
            "arch": pkg.arch,
            "pulp_labels": pkg.pulp_labels,
        }
        for pkg in packages
    ]
    return json.dumps(data, indent=2)


# -----------------------------------------------------------------------------
# Mode handlers
# -----------------------------------------------------------------------------


def _run_direct_search(
    config: str,
    checksums: list[str],
    filenames: list[str],
    signed_by: list[str],
    *,
    correlation_namespace: str | None = None,
    correlation_build_id: str | None = None,
) -> None:
    """Search by checksum, filename, and/or signed_by from CLI options and print JSON results."""
    try:
        req = SearchByRequest(
            checksums=checksums,
            filenames=filenames,
            signed_by=signed_by,
        )
    except ValidationError as e:
        _handle_validation_error(e, results_json_context=False)

    client = PulpClient.create_from_config_file(
        path=config,
        correlation_namespace=correlation_namespace,
        correlation_build_id=correlation_build_id,
    )
    signed_by_val = req.signed_by[0] if req.signed_by else None

    if req.checksums:
        if signed_by_val:
            packages = _search_pulp_for_rpms_with_signed_by(client, req.checksums, signed_by_val)
            if packages:
                logging.info("Found %d RPM(s) in Pulp by checksum and signed_by", len(packages))
            else:
                logging.info("No RPMs found in Pulp for checksums and signed_by")
        else:
            packages = _search_pulp_for_rpms(client, req.checksums)
            if packages:
                logging.info("Found %d RPM(s) in Pulp by checksum", len(packages))
            else:
                logging.info("No RPMs found in Pulp for %d checksum(s)", len(req.checksums))
    elif req.filenames:
        nvras = _filenames_to_nvras_deduplicated(req.filenames)
        filenames_for_api = [f"{n}-{v}-{r}.{arch}.rpm" for n, v, r, arch in nvras]
        if signed_by_val:
            packages = _search_pulp_by_filenames_with_signed_by(client, filenames_for_api, signed_by_val)
            if packages:
                logging.info("Found %d RPM(s) in Pulp by filename and signed_by", len(packages))
            else:
                logging.info("No RPMs found in Pulp for filenames and signed_by")
        else:
            packages = _search_pulp_by_filenames(client, filenames_for_api)
            if packages:
                logging.info("Found %d RPM(s) in Pulp by filename", len(packages))
            else:
                logging.info("No RPMs found in Pulp for %d filename(s)", len(filenames_for_api))
    else:
        packages = _search_pulp_by_signed_by(client, signed_by_val) if signed_by_val else []
        if packages:
            logging.info("Found %d RPM(s) in Pulp by signed_by", len(packages))
        else:
            logging.info("No RPMs found in Pulp for signed_by")
    _log_packages_found(packages)

    click.echo(_packages_to_json(packages))


def _filter_artifacts_to_rpms_only(data: dict) -> dict:
    """Return a copy of data with only RPM artifacts (remove logs, sboms, etc.)."""
    out = copy.deepcopy(data)
    artifacts = out.get("artifacts", {})
    to_drop = [k for k in artifacts if not SearchByResultsJson._is_rpm(k)]
    for k in to_drop:
        del artifacts[k]
    return out


def _handle_validation_error(e: ValidationError, results_json_context: bool = False) -> None:
    """Echo validation error and exit."""
    err = e.errors()[0]
    msg = str(err.get("msg", ""))
    if "checksums" in str(err.get("loc", [])) and "Invalid checksum" in msg:
        if results_json_context:
            click.echo(f"Error: Invalid checksum in results.json: {msg}", err=True)
        else:
            invalid = msg.split(": ")[-1] if ": " in msg else "?"
            click.echo(
                f"Error: Invalid checksum format (expected 64 hex chars): {invalid}",
                err=True,
            )
    else:
        loc = ".".join(str(x) for x in err.get("loc", []))
        click.echo(f"Error: {loc}: {err.get('msg', '')}", err=True)
    sys.exit(1)


def _run_results_json_mode(
    config: str,
    results_json: str,
    output_results: Path,
    checksums: list[str],
    use_checksum_from_file: bool,
    filenames: list[str],
    use_filename_from_file: bool,
    signed_by: list[str],
    keep_files: bool = False,
    *,
    correlation_namespace: str | None = None,
    correlation_build_id: str | None = None,
) -> None:
    """Load results.json, remove RPMs found in Pulp, write filtered output."""
    oci_temp: tempfile.TemporaryDirectory[str] | None = None
    try:
        local_path_str, oci_temp = resolve_results_json_local_path(
            results_json.strip(),
            oci_dest_dir=None,
            prefix="pulp-tool-search-json-",
        )
        with open(local_path_str, encoding="utf-8") as f:
            results_data = json.load(f)
    except PullRunnerError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)
    except (OSError, json.JSONDecodeError) as e:
        click.echo(f"Error: Failed to read results.json: {e}", err=True)
        sys.exit(1)
    finally:
        if oci_temp is not None:
            oci_temp.cleanup()

    results = SearchByResultsJson(results_data)
    # Checksums and filenames are mutually exclusive. Extract only one.
    if checksums:
        # Explicit checksums: use them, no filenames
        checksums = list(checksums)
        filenames = []
    elif filenames:
        # Explicit filenames: use them, no checksums
        filenames = list(filenames)
        checksums = []
    elif use_checksum_from_file:
        # Flag only: extract checksums
        checksums = results.extract_rpm_checksums()
        filenames = []
    elif use_filename_from_file:
        # Flag only: extract filenames
        filenames = results.extract_filenames()
        checksums = []
    elif not signed_by:
        # No explicit, no flags, no signed_by: default to checksums from file
        checksums = results.extract_rpm_checksums()
        filenames = []
    else:
        # signed_by only: no extraction, use signed_by alone
        checksums = []
        filenames = []

    if not checksums and not filenames and not signed_by:
        to_write = results_data if keep_files else _filter_artifacts_to_rpms_only(results_data)
        output_results.parent.mkdir(parents=True, exist_ok=True)
        with open(output_results, "w", encoding="utf-8") as f:
            json.dump(to_write, f, indent=2)
        click.echo(f"Wrote results to {output_results} (no RPM artifacts to filter)")
        return

    try:
        req = SearchByRequest(
            checksums=checksums,
            filenames=filenames,
            signed_by=signed_by,
        )
    except ValidationError as e:
        _handle_validation_error(e, results_json_context=True)

    try:
        client = PulpClient.create_from_config_file(
            path=config,
            correlation_namespace=correlation_namespace,
            correlation_build_id=correlation_build_id,
        )
        signed_by_val = req.signed_by[0] if req.signed_by else None

        if req.checksums:
            if signed_by_val:
                packages = _search_pulp_for_rpms_with_signed_by(client, req.checksums, signed_by_val)
            else:
                packages = _search_pulp_for_rpms(client, req.checksums)
            found = FoundPackages.from_packages(packages)
            filtered_results = results.remove_found(found)
        elif req.filenames:
            # Incremental: search one NVR at a time, remove from results after each response,
            # re-extract remaining filenames, stop when no RPM artifacts left (early termination)
            packages, filtered_results = _search_pulp_by_filenames_incremental(
                client, results_data, signed_by_val, initial_filenames=req.filenames
            )
            found = FoundPackages.from_packages(packages)
        else:
            packages = _search_pulp_by_signed_by(client, signed_by_val) if signed_by_val else []
            found = FoundPackages.from_packages(packages)
            filtered_results = results.remove_found(found)

        if packages:
            logging.info("Found %d RPM(s) in Pulp (will remove from results)", len(packages))
            _log_packages_found(packages)
        else:
            logging.info("No RPMs found in Pulp for search criteria from results.json")

        to_write = filtered_results if keep_files else _filter_artifacts_to_rpms_only(filtered_results)
        output_results.parent.mkdir(parents=True, exist_ok=True)
        with open(output_results, "w", encoding="utf-8") as f:
            json.dump(to_write, f, indent=2)

        removed = len(results_data.get("artifacts", {})) - len(filtered_results.get("artifacts", {}))
        msg = f"Wrote results to {output_results} (removed {removed} found RPM(s))"
        if packages and len(packages) <= 10:
            pkg_list = "\n  ".join(f"{pkg.name}-{pkg.version}-{pkg.release}.{pkg.arch}" for pkg in packages)
            msg += f":\n  {pkg_list}"
        elif packages:
            msg += f" ({len(packages)} packages)"
        click.echo(msg)
    except httpx.HTTPError as e:
        handle_http_error(e, "search by")
        sys.exit(1)
    except Exception as e:
        handle_generic_error(e, "search by")
        sys.exit(1)


# -----------------------------------------------------------------------------
# CLI command
# -----------------------------------------------------------------------------
