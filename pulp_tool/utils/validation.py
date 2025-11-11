"""
Validation utilities for Pulp operations.

This module provides comprehensive validation functions for build IDs, file paths,
and repository configurations. It uses guard clauses for early validation failures
and includes helpers for extracting metadata from artifacts.

Key Functions:
    - validate_build_id(): Check if build ID is valid
    - validate_file_path(): Validate file exists, is readable, and not empty
    - validate_repository_setup(): Validate repository configuration completeness
    - extract_metadata_from_artifact_json(): Extract metadata fields from artifacts
    - determine_build_id(): Determine build ID from multiple sources
    - sanitize_build_id_for_repository(): Clean build IDs for repository naming

Organization:
    - Build ID Utilities
    - Metadata Extraction Functions
    - File Validation Functions
    - Repository Validation Functions

All functions follow clean code principles with guard clauses and early returns.
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

from ..models.artifacts import ArtifactJsonResponse, ArtifactMetadata

# ============================================================================
# Validation Constants
# ============================================================================

# Minimum allowed file size (bytes) - 0 means file must not be empty
MIN_FILE_SIZE = 0

# Supported repository types in Pulp
REPOSITORY_TYPES = ["rpms", "logs", "sbom", "artifacts"]


# ============================================================================
# Build ID Utilities
# ============================================================================


def strip_namespace_from_build_id(build_id: str) -> str:
    """
    Strip namespace prefix from build_id to get just the build name.

    Args:
        build_id: Build ID that may contain namespace prefix (e.g., "namespace/build-name")

    Returns:
        Build name without namespace prefix

    Example:
        >>> strip_namespace_from_build_id("jreidy-tenant/build-123")
        'build-123'
        >>> strip_namespace_from_build_id("build-456")
        'build-456'
    """
    if not build_id:
        return ""

    # If build_id contains a slash, split and take everything after the first slash
    if "/" in build_id:
        return build_id.split("/", 1)[1]

    return build_id


def sanitize_build_id_for_repository(build_id: str) -> str:
    """
    Sanitize a build ID for use in repository naming by replacing invalid characters.

    Args:
        build_id: Build ID to sanitize

    Returns:
        Sanitized build ID safe for repository naming

    Example:
        >>> sanitize_build_id_for_repository("test/build:123")
        'test-build-123'
    """
    if not build_id or not isinstance(build_id, str):
        return "default-build"

    # Replace invalid characters with hyphens
    invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
    sanitized = build_id

    for char in invalid_chars:
        sanitized = sanitized.replace(char, "-")

    # Remove multiple consecutive hyphens
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")

    # Remove leading/trailing hyphens
    sanitized = sanitized.strip("-")

    # Ensure it's not empty after sanitization
    if not sanitized:
        return "default-build"

    return sanitized


def validate_build_id(build_id: str) -> bool:
    """
    Validate that a build ID is not empty or None.

    Args:
        build_id: Build ID to validate

    Returns:
        True if valid, False otherwise

    Example:
        >>> validate_build_id("my-build")
        True
        >>> validate_build_id("")
        False
    """
    return bool(build_id and isinstance(build_id, str))


# ============================================================================
# Metadata Extraction Functions
# ============================================================================


def extract_metadata_from_artifact_json(
    artifact_json, field_name: str, fallback: Optional[str] = None
) -> Optional[str]:
    """
    Extract any metadata field from artifact JSON.

    Args:
        artifact_json: Artifact metadata from distribution client (Dict or ArtifactJsonResponse)
        field_name: Field to extract from labels (e.g., 'build_id', 'namespace', 'parent_package')
        fallback: Value to return if field not found

    Returns:
        Field value extracted from artifact metadata, or fallback if not found

    Example:
        >>> metadata = {"artifacts": {"rpm1": {"labels": {"build_id": "build-123"}}}}
        >>> extract_metadata_from_artifact_json(metadata, "build_id", fallback="rok-storage")
        'build-123'
    """
    # Handle both Dict and ArtifactJsonResponse types
    if isinstance(artifact_json, ArtifactJsonResponse):
        artifacts = artifact_json.artifacts
    else:
        # Handle raw dictionary
        artifacts_raw = artifact_json.get("artifacts", {})
        artifacts = {
            name: ArtifactMetadata(**metadata) if isinstance(metadata, dict) else metadata
            for name, metadata in artifacts_raw.items()
        }

    # Try to find field in any of the artifacts
    for artifact_info in artifacts.values():
        field_value = _extract_field_from_artifact(artifact_info, field_name)

        # Early return on success
        if field_value:
            logging.debug("Extracted %s '%s' from artifact JSON", field_name, field_value)
            return field_value

    # Return fallback if no field found
    if fallback:
        logging.warning("No %s found in artifact metadata, using fallback: %s", field_name, fallback)
    else:
        logging.debug("No %s found in artifact metadata", field_name)
    return fallback


def _extract_field_from_artifact(artifact_info, field_name: str) -> Optional[str]:
    """
    Extract field value from a single artifact.

    Args:
        artifact_info: Artifact info (ArtifactMetadata or dict)
        field_name: Field name to extract

    Returns:
        Field value or None
    """
    if isinstance(artifact_info, ArtifactMetadata):
        return artifact_info.labels.get(field_name) if artifact_info.labels else None

    # Fallback for dict access
    if isinstance(artifact_info, dict):
        labels = artifact_info.get("labels", {})
        return labels.get(field_name)

    return None


def extract_metadata_from_artifacts(pulled_artifacts, field_name: str, fallback: Optional[str] = None) -> Optional[str]:
    """
    Extract any metadata field from artifact labels.

    Args:
        pulled_artifacts: PulledArtifacts model containing downloaded artifacts organized by type
        field_name: Field to extract from labels (e.g., 'build_id', 'namespace', 'parent_package')
        fallback: Value to return if field not found

    Returns:
        Field value extracted from artifact labels, or fallback if not found

    Example:
        >>> from pulp_tool.models.artifacts import PulledArtifacts
        >>> artifacts = PulledArtifacts()
        >>> artifacts.add_rpm("test.rpm", "/tmp/test.rpm", {"build_id": "build-456"})
        >>> extract_metadata_from_artifacts(artifacts, "build_id", fallback="rok-storage")
        'build-456'
    """
    # Check each artifact type for the field
    for artifact_type in ["rpms", "sboms", "logs"]:
        artifacts = getattr(pulled_artifacts, artifact_type)
        if artifacts:
            # Get the first artifact's labels (ArtifactFile object)
            first_artifact = next(iter(artifacts.values()))
            field_value = first_artifact.labels.get(field_name)
            if field_value:
                logging.debug("Extracted %s '%s' from %s artifacts", field_name, field_value, artifact_type)
                return field_value

    # Return fallback if no field found
    if fallback:
        logging.warning("No %s found in artifact labels, using fallback: %s", field_name, fallback)
    else:
        logging.debug("No %s found in artifact labels", field_name)
    return fallback


def extract_build_id_from_artifact_json(artifact_json) -> str:
    """
    Extract build_id from artifact_json metadata.

    Deprecated: Use extract_metadata_from_artifact_json(artifact_json, "build_id", fallback="rok-storage") instead.
    This is a compatibility wrapper.
    """
    return extract_metadata_from_artifact_json(artifact_json, "build_id", fallback="rok-storage") or "rok-storage"


def extract_build_id_from_artifacts(pulled_artifacts) -> str:
    """
    Extract build_id from the first available artifact's labels.

    Deprecated: Use extract_metadata_from_artifacts(pulled_artifacts, "build_id", fallback="rok-storage") instead.
    This is a compatibility wrapper.
    """
    return extract_metadata_from_artifacts(pulled_artifacts, "build_id", fallback="rok-storage") or "rok-storage"


def determine_build_id(args, artifact_json=None, pulled_artifacts=None) -> str:
    """
    Determine build ID from command line arguments, artifact metadata, or pulled artifacts.

    Priority: command line argument > artifact_json > pulled_artifacts > default

    Args:
        args: Command line arguments
        artifact_json: Optional artifact metadata (Dict or ArtifactJsonResponse)
        pulled_artifacts: Optional pulled artifacts (PulledArtifacts model or dict)

    Returns:
        Build ID string

    Example:
        >>> from types import SimpleNamespace
        >>> args = SimpleNamespace(build_id="my-build")
        >>> determine_build_id(args)
        'my-build'
    """
    # Priority 1: Command line argument
    if hasattr(args, "build_id") and args.build_id:
        build_id = args.build_id
        logging.info("Using build_id from command line argument: %s", build_id)
        return build_id

    # Priority 2: Extract from artifact_json
    if artifact_json:
        build_id = extract_build_id_from_artifact_json(artifact_json)
        logging.info("Using build_id from artifact metadata: %s", build_id)
        return build_id

    # Priority 3: Extract from pulled_artifacts
    if pulled_artifacts:
        build_id = extract_build_id_from_artifacts(pulled_artifacts)
        logging.info("Using build_id from pulled artifacts: %s", build_id)
        return build_id

    # Priority 4: Default fallback
    build_id = "rok-storage"
    logging.info("Using default build_id: %s", build_id)
    return build_id


# ============================================================================
# File Validation Functions
# ============================================================================


def validate_file_path(file_path: str, file_type: str) -> None:
    """
    Validate file exists, is readable, and not empty.

    Uses guard clauses for early validation failure.

    Args:
        file_path: Path to the file to validate
        file_type: Type of file for error messages (e.g., 'RPM', 'SBOM')

    Raises:
        FileNotFoundError: If the file does not exist
        PermissionError: If the file cannot be read
        ValueError: If the file is empty

    Example:
        >>> validate_file_path("/path/to/file.rpm", "RPM")  # doctest: +SKIP
    """
    # Guard clause: file must exist
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"{file_type} file not found: {file_path}")

    # Guard clause: file must be readable
    if not os.access(file_path, os.R_OK):
        raise PermissionError(f"Cannot read {file_type} file: {file_path}")

    # Guard clause: file must not be empty
    file_size = os.path.getsize(file_path)
    if file_size == MIN_FILE_SIZE:
        raise ValueError(f"{file_type} file is empty: {file_path}")

    logging.debug("%s file size: %d bytes", file_type, file_size)


# ============================================================================
# Repository Validation Functions
# ============================================================================


def validate_repository_setup(repositories: Dict[str, str]) -> Tuple[bool, List[str]]:
    """
    Validate that repository setup is complete.

    Args:
        repositories: Dictionary mapping repository identifiers to repository references
                     Expected keys: rpms_prn, rpms_href, logs_prn, logs_href,
                                   sbom_prn, sbom_href, artifacts_prn, artifacts_href

    Returns:
        Tuple of (is_valid, list_of_errors)

    Example:
        >>> repos = {
        ...     "rpms_prn": "/pulp/api/v3/repositories/rpm/rpm/123/",
        ...     "rpms_href": "/pulp/api/v3/repositories/rpm/rpm/123/"
        ... }
        >>> is_valid, errors = validate_repository_setup(repos)
        >>> is_valid
        False
        >>> "logs" in str(errors)
        True
    """
    errors = []

    # Check that all required repository PRNs are present
    for repo_type in REPOSITORY_TYPES:
        prn_key = f"{repo_type}_prn"
        if prn_key not in repositories or not repositories.get(prn_key):
            errors.append(f"Missing {repo_type} repository PRN")

    # For RPM repositories, also check that href is present
    if "rpms_href" not in repositories or not repositories.get("rpms_href"):
        errors.append("Missing rpms repository href")

    # Check that repository references are valid (non-empty strings)
    for repo_key, repo_ref in repositories.items():
        if repo_ref and (not isinstance(repo_ref, str) or not repo_ref.strip()):
            errors.append(f"Invalid repository reference for {repo_key}")

    is_valid = len(errors) == 0
    return is_valid, errors


__all__ = [
    "strip_namespace_from_build_id",
    "sanitize_build_id_for_repository",
    "validate_build_id",
    "extract_metadata_from_artifact_json",
    "extract_metadata_from_artifacts",
    "extract_build_id_from_artifact_json",  # Deprecated wrapper
    "extract_build_id_from_artifacts",  # Deprecated wrapper
    "determine_build_id",
    "validate_file_path",
    "validate_repository_setup",
]
