"""
RPM operations for Pulp.

This module provides utilities for processing and uploading RPM files,
including checksum calculation, batch processing, and parallel uploads.
"""

import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from .client_limits import max_upload_workers


def calculate_sha256_checksum(file_path: str) -> str:
    """
    Calculate SHA256 checksum of a file.

    Args:
        file_path: Path to the file to calculate checksum for

    Returns:
        SHA256 checksum as hexadecimal string

    Raises:
        FileNotFoundError: If the file does not exist
        IOError: If there's an error reading the file
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    sha256_hash = hashlib.sha256()

    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
    except OSError as e:
        raise OSError(f"Error reading file {file_path}: {e}") from e

    return sha256_hash.hexdigest()


def parse_rpm_filename_to_nvr(filename: str) -> tuple[str, str, str] | None:
    """
    Parse RPM filename into name, version, and release (NVR).

    Uses the same right-to-left parsing algorithm as rpmUtils.miscutils.splitFilename
    (from Yum/DNF, used by the Pulp ecosystem). Format: [epoch:]name-version-release.arch
    See: https://github.com/rpm-software-management/yum/blob/master/rpmUtils/miscutils.py

    Handles filenames like name-version-release.arch.rpm (e.g.
    osci-internal-test-package-0.2.0-257.el10.src.rpm) and paths
    (e.g. x86_64/pkg-1.0-1.x86_64.rpm).

    Args:
        filename: RPM filename or path (e.g. pkg-1.0-1.el8.x86_64.rpm)

    Returns:
        Tuple of (name, version, release) or None if unparseable

    Example:
        >>> parse_rpm_filename_to_nvr("osci-internal-test-package-0.2.0-257.el10.src.rpm")
        ('osci-internal-test-package', '0.2.0', '257.el10')
    """
    basename = os.path.basename(filename)
    if not basename.lower().endswith(".rpm"):
        return None
    stem = basename[:-4]  # strip .rpm

    # Right-to-left parsing (rpmUtils splitFilename): find arch, then release, then version
    arch_index = stem.rfind(".")
    if arch_index >= 0:
        nvr_part = stem[:arch_index]
    else:
        nvr_part = stem

    rel_index = nvr_part.rfind("-")
    if rel_index < 0:
        return None
    release = nvr_part[rel_index + 1 :]
    part_before_rel = nvr_part[:rel_index]

    ver_index = part_before_rel.rfind("-")
    if ver_index < 0:
        return None
    version = part_before_rel[ver_index + 1 :]

    # Epoch: only "epoch:name-version-release" (epoch at start, before first '-')
    epoch_index = nvr_part.find(":")
    if epoch_index >= 0 and epoch_index < nvr_part.find("-") and nvr_part[:epoch_index].isdigit():
        name = nvr_part[epoch_index + 1 : ver_index]
    else:
        name = part_before_rel[:ver_index]

    if not name or not version or not release:
        return None
    return (name, version, release)


def parse_rpm_filename_to_nvra(filename: str) -> tuple[str, str, str, str] | None:
    """
    Parse RPM filename into name, version, release, and architecture (NVRA).

    Same algorithm as parse_rpm_filename_to_nvr but also extracts architecture
    (e.g. x86_64, aarch64, src, noarch) from the filename.

    Args:
        filename: RPM filename or path (e.g. pkg-1.0-1.el8.x86_64.rpm)

    Returns:
        Tuple of (name, version, release, arch) or None if unparseable

    Example:
        >>> parse_rpm_filename_to_nvra("pkg-1.0-1.x86_64.rpm")
        ('pkg', '1.0', '1', 'x86_64')
        >>> parse_rpm_filename_to_nvra("pkg-1.0-1.aarch64.rpm")
        ('pkg', '1.0', '1', 'aarch64')
    """
    nvr = parse_rpm_filename_to_nvr(filename)
    if nvr is None:
        return None
    name, version, release = nvr
    basename = os.path.basename(filename)
    stem = basename[:-4]  # strip .rpm
    arch_index = stem.rfind(".")
    arch = stem[arch_index + 1 :] if arch_index >= 0 else "noarch"
    return (name, version, release, arch)


def upload_rpms_parallel(
    client,
    rpms_to_upload: list[str] | list[tuple[str, dict[str, str], str]],
    labels: dict[str, str] | None = None,
    arch: str | None = None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """
    Upload RPMs in parallel and return (local_path, artifact_href) per successful upload.

    This function uploads multiple RPM files concurrently using a thread pool
    for improved performance.

    Args:
        client: PulpClient instance for API interactions
        rpms_to_upload: Either:
            - List of RPM file paths (requires labels and arch parameters)
            - List of (rpm_path, labels, arch) tuples (labels and arch params ignored)
        labels: Labels to attach to all uploaded content (ignored if rpms_to_upload contains tuples)
        arch: Architecture for all uploaded RPMs (ignored if rpms_to_upload contains tuples)

    Returns:
        Tuple of:
            - List of (local_path, pulp artifact href) for successfully uploaded RPMs
            - List of error messages for failed uploads

    Examples:
        # Old style - all RPMs share same labels and arch
        >>> pairs, errors = upload_rpms_parallel(client, ["/path/rpm1.rpm", "/path/rpm2.rpm"],
        ...                              labels={"build_id": "123"}, arch="x86_64")

        # New style - each RPM has its own labels and arch
        >>> rpm_infos = [
        ...     ("/path/rpm1.rpm", {"build_id": "123", "name": "pkg1"}, "x86_64"),
        ...     ("/path/rpm2.rpm", {"build_id": "123", "name": "pkg2"}, "noarch"),
        ... ]
        >>> pairs, errors = upload_rpms_parallel(client, rpm_infos)
    """
    if not rpms_to_upload:
        return [], []

    # Detect if we're using the new style (list of tuples) or old style (list of paths)
    # Check first element to determine the calling style
    first_item = rpms_to_upload[0]
    is_tuple_style = isinstance(first_item, (tuple, list))

    rpm_infos: list[tuple[str, dict[str, str], str]]
    if not is_tuple_style:
        # Old style - validate required parameters
        if labels is None or arch is None:
            raise ValueError("labels and arch parameters are required when rpms_to_upload is a list of paths")

        # Convert to tuple style for uniform processing
        # Type cast since we know rpms_to_upload is List[str] here
        rpm_infos = [(rpm_path, labels, arch) for rpm_path in rpms_to_upload]  # type: ignore
        logging.warning("Uploading %d RPM file(s) for %s", len(rpms_to_upload), arch)
    else:
        # New style - already in tuple format
        # Type cast since we know rpms_to_upload is List[Tuple[...]] here
        rpm_infos = rpms_to_upload  # type: ignore
        logging.warning("Uploading %d RPM file(s)", len(rpms_to_upload))

    path_href_pairs: list[tuple[str, str]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(thread_name_prefix="upload_rpms", max_workers=max_upload_workers()) as executor:
        futures = {
            executor.submit(client.upload_content, rpm_path, rpm_labels, file_type="rpm", arch=rpm_arch): rpm_path
            for rpm_path, rpm_labels, rpm_arch in rpm_infos
        }

        for future in as_completed(futures):
            rpm_path = futures[future]
            logging.warning("Uploading RPM: %s", os.path.basename(rpm_path))
            try:
                artifact_href = future.result()
                path_href_pairs.append((rpm_path, artifact_href))
            except Exception as e:  # pylint: disable=broad-except
                # Log the error but continue processing other uploads
                logging.error("Failed to upload %s: %s", rpm_path, e)
                errors.append(f"{rpm_path}: {e}")

    return path_href_pairs, errors


__all__ = [
    "calculate_sha256_checksum",
    "parse_rpm_filename_to_nvr",
    "parse_rpm_filename_to_nvra",
    "upload_rpms_parallel",
]
