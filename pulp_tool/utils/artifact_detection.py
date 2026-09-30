"""
Artifact type detection utilities.

This module provides functions for detecting artifact types from filenames
and organizing artifacts by their content type.
"""

import logging
import os
import re
from typing import Any

from ..models.artifacts import ArtifactMetadata
from .constants import ARCH_DETECT_WARNING_MSG, SUPPORTED_ARCHITECTURES


def rpm_packages_letter_and_basename(path_or_filename: str) -> tuple[str, str]:
    """
    Basename and createrepo-style Packages subdirectory letter for an RPM.

    The letter is always the lowercase first character of the RPM filename (basename),
    not the first character of a longer path (e.g. ``Packages/w/`` or ``x86_64/``).

    Args:
        path_or_filename: RPM filename or path (POSIX-style slashes).

    Returns:
        Tuple of (rpm basename, single lowercase letter for ``Packages/<letter>/``).

    Example:
        >>> rpm_packages_letter_and_basename("Packages/W/whale.rpm")
        ('whale.rpm', 'w')
        >>> rpm_packages_letter_and_basename("x86_64/libecpg.rpm")
        ('libecpg.rpm', 'l')
    """
    if not path_or_filename or not str(path_or_filename).strip():
        return "", "a"
    normalized = str(path_or_filename).strip().replace("\\", "/").rstrip("/")
    basename = normalized.split("/")[-1]
    if not basename:
        return "", "a"
    return basename, basename[0].lower()


def detect_artifact_type(artifact_name: str) -> str | None:
    """
    Detect artifact type from artifact name.

    Args:
        artifact_name: Name of the artifact (filename)

    Returns:
        Artifact type ('rpm', 'log', 'sbom') or None if type cannot be determined

    Example:
        >>> detect_artifact_type("package.rpm")
        'rpm'
        >>> detect_artifact_type("build.log")
        'log'
        >>> detect_artifact_type("sbom.json")
        'sbom'
        >>> detect_artifact_type("liblastlog2-1.0-1.x86_64.rpm")
        'rpm'
    """
    artifact_name_lower = artifact_name.lower()

    # Check file extensions first to avoid false positives from substring matching
    # (e.g., "liblastlog2-1.0.rpm" contains "log" but is an RPM)
    if artifact_name_lower.endswith(".rpm"):
        return "rpm"
    if artifact_name_lower.endswith(".log"):
        return "log"

    # Fall back to substring matching for SBOMs (e.g., "sbom.json", "cyclonedx.json")
    if "sbom" in artifact_name_lower:
        return "sbom"

    return None


def build_artifact_url(artifact_name: str, artifact_type: str, distros: dict[str, str]) -> str | None:
    """
    Build the download URL for an artifact based on its type.

    Args:
        artifact_name: Name of the artifact
        artifact_type: Type of artifact ('rpm', 'log', 'sbom')
        distros: Dictionary mapping artifact types to distribution base URLs

    Returns:
        Full URL for downloading the artifact, or None if type is invalid

    Example:
        >>> distros = {"rpms": "https://example.com/rpms/", "logs": "https://example.com/logs/"}
        >>> build_artifact_url("package.rpm", "rpm", distros)
        'https://example.com/rpms/Packages/p/package.rpm'
    """
    if artifact_type == "sbom":
        return f"{distros.get('sbom', '')}{artifact_name}"
    if artifact_type == "log":
        return f"{distros.get('logs', '')}{artifact_name}"
    if artifact_type == "rpm":
        rpm_basename, first_letter = rpm_packages_letter_and_basename(artifact_name)
        if not rpm_basename:
            return None
        return f"{distros.get('rpms', '')}Packages/{first_letter}/{rpm_basename}"

    return None


def extract_architecture_from_metadata(metadata: dict[str, Any] | ArtifactMetadata) -> str:
    """
    Extract architecture from artifact metadata.

    Args:
        metadata: Artifact metadata (ArtifactMetadata model or dict)

    Returns:
        Architecture string, defaulting to 'noarch' if not found

    Example:
        >>> from pulp_tool.models.artifacts import ArtifactMetadata
        >>> metadata = ArtifactMetadata(labels={"arch": "x86_64"})
        >>> extract_architecture_from_metadata(metadata)
        'x86_64'
    """
    if isinstance(metadata, ArtifactMetadata):
        return metadata.arch or "noarch"

    return metadata.get("pulp_labels", {}).get("arch", "noarch")


def _embedded_artifact_sha256(metadata: Any) -> str | None:
    """Return normalized sha256 from artifact metadata when set."""
    if isinstance(metadata, ArtifactMetadata):
        raw = metadata.sha256
    elif isinstance(metadata, dict):
        raw = metadata.get("sha256")
    else:
        raw = getattr(metadata, "sha256", None)
    if raw is None:
        return None
    stripped = str(raw).strip()
    return stripped if stripped else None


def _embedded_artifact_url(metadata: Any) -> str | None:
    """
    Return the download URL from pulp_results.json-style artifact metadata if set.

    When present and non-empty, pull uses this URL as-is instead of synthesizing
    one from distribution base URLs.
    """
    if isinstance(metadata, ArtifactMetadata):
        raw = metadata.url
    elif isinstance(metadata, dict):
        raw = metadata.get("url")
    else:
        raw = getattr(metadata, "url", None)
    if raw is None:
        return None
    stripped = str(raw).strip()
    return stripped if stripped else None


def categorize_artifacts_by_type(
    artifacts: dict[str, Any],
    distros: dict[str, str],
    content_types: list[str] | None = None,
    archs: list[str] | None = None,
    *,
    embedded_urls_only: bool = False,
) -> list[tuple[str, str, str, str, str | None]]:
    """
    Categorize artifacts and prepare download information.

    Args:
        artifacts: Dictionary of artifacts (can be ArtifactMetadata or dict)
        distros: Dictionary of distribution URLs (used when an artifact has no ``url`` and
            ``embedded_urls_only`` is False)
        content_types: Optional list of content types to filter (rpm, log, sbom)
        archs: Optional list of architectures to filter
        embedded_urls_only: If True, only include artifacts with a non-empty ``url`` in metadata
            (``pulp pull`` / artifact results JSON); distribution base URLs are not used.

    Returns:
        List of tuples: (artifact_name, file_url, arch, artifact_type, expected_sha256)
    """
    download_tasks = []

    for artifact_name, metadata in artifacts.items():
        # Extract architecture from metadata
        arch = extract_architecture_from_metadata(metadata)

        # Detect artifact type
        artifact_type = detect_artifact_type(artifact_name)
        if not artifact_type:
            logging.debug("Skipping %s: could not determine artifact type", artifact_name)
            continue

        embedded_url = _embedded_artifact_url(metadata)
        if embedded_urls_only:
            file_url = embedded_url
        else:
            file_url = embedded_url or build_artifact_url(artifact_name, artifact_type, distros)

        if not file_url:
            if embedded_urls_only:
                logging.debug(
                    "Skipping %s: artifact metadata has no url (pull uses only URLs from artifact results)",
                    artifact_name,
                )
            else:
                logging.debug("Skipping %s: could not build download URL", artifact_name)
            continue

        # Apply content type filter
        if content_types and artifact_type not in content_types:
            logging.debug("Skipping %s: content type %s not in filter %s", artifact_name, artifact_type, content_types)
            continue

        # Apply architecture filter
        if archs and arch not in archs:
            logging.debug("Skipping %s: architecture %s not in filter %s", artifact_name, arch, archs)
            continue

        download_tasks.append((artifact_name, file_url, arch, artifact_type, _embedded_artifact_sha256(metadata)))

    return download_tasks


def detect_arch_from_filepath(filepath: str) -> str | None:
    """
    Try to detect architecture from file path.

    This function checks if any supported architecture appears in the file path
    as a directory segment (e.g., /path/to/x86_64/package.rpm).

    Args:
        filepath: Path to file

    Returns:
        Architecture string if detected, None otherwise

    Example:
        >>> detect_arch_from_filepath("/path/to/x86_64/package.rpm")
        'x86_64'
        >>> detect_arch_from_filepath("/path/to/aarch64/package.rpm")
        'aarch64'
        >>> detect_arch_from_filepath("/path/to/package.rpm")
        None
    """
    # This handles cases like /path/to/x86_64/package.rpm or /path/to/aarch64/package.rpm
    path_lower = filepath.lower()
    for arch in SUPPORTED_ARCHITECTURES:
        # Check if architecture appears in the path as a directory segment
        # Pattern ensures there's at least one character before and after the /arch/ segment
        arch_pattern = rf"[^/\\][/\\]{re.escape(arch)}[/\\][^/\\]"
        if re.search(arch_pattern, path_lower, re.IGNORECASE):
            return arch

    return None


def detect_arch_from_rpm_filename(rpm_path: str) -> str | None:
    """
    Try to detect architecture from RPM filename.

    This function checks the RPM filename pattern (name-version-release.arch.rpm)
    to extract the architecture.

    Args:
        rpm_path: Path to RPM file (filename will be extracted)

    Returns:
        Architecture string if detected, None otherwise

    Example:
        >>> detect_arch_from_rpm_filename("/path/to/package-1.0.0-1.x86_64.rpm")
        'x86_64'
        >>> detect_arch_from_rpm_filename("/path/to/package-1.0.0-1.aarch64.rpm")
        'aarch64'
        >>> detect_arch_from_rpm_filename("/path/to/package.rpm")
        None
    """
    # This handles cases like package-1.0.0-1.x86_64.rpm or package-1.0.0-1.aarch64.rpm
    filename = os.path.basename(rpm_path)
    match = re.search(r"\.([a-z0-9_]+)\.rpm$", filename, re.IGNORECASE)
    if match:
        arch = match.group(1)
        # Check if the detected arch from filename is in supported architectures
        if arch in SUPPORTED_ARCHITECTURES:
            return arch

    return None


def group_rpm_paths_by_arch(
    rpm_paths: list[str],
    *,
    explicit_arch: str | None = None,
) -> dict[str, list[str]]:
    """
    Group RPM file paths by detected or explicit architecture.

    Paths that cannot be assigned an architecture are skipped with a warning.

    Args:
        rpm_paths: List of paths to RPM files.
        explicit_arch: If set, use this architecture for all paths; otherwise detect per path.

    Returns:
        Dictionary mapping architecture name to list of RPM paths.

    Example:
        >>> group_rpm_paths_by_arch(["/path/pkg.x86_64.rpm", "/path/pkg.noarch.rpm"])
        {'x86_64': ['/path/pkg.x86_64.rpm'], 'noarch': ['/path/pkg.noarch.rpm']}
    """
    rpms_by_arch: dict[str, list[str]] = {}
    for fp in rpm_paths:
        if explicit_arch:
            arch = explicit_arch
        else:
            detected = detect_arch_from_filepath(fp) or detect_arch_from_rpm_filename(fp)
            if not detected:
                logging.warning(ARCH_DETECT_WARNING_MSG, os.path.basename(fp))
                continue
            arch = detected
        if arch not in rpms_by_arch:
            rpms_by_arch[arch] = []
        rpms_by_arch[arch].append(fp)
    return rpms_by_arch


__all__ = [
    "detect_artifact_type",
    "rpm_packages_letter_and_basename",
    "build_artifact_url",
    "extract_architecture_from_metadata",
    "categorize_artifacts_by_type",
    "detect_arch_from_filepath",
    "detect_arch_from_rpm_filename",
    "group_rpm_paths_by_arch",
]
