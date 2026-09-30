"""
Build ID validation, sanitization, and extraction utilities.

This module provides functions for validating, sanitizing, and extracting build IDs
from various sources including command line arguments, artifact metadata, and
downloaded artifacts.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from ...models.artifacts import ArtifactMetadata
from ...models.pulp_results import PulpResultsDocument

if TYPE_CHECKING:
    from ...models.artifacts import PulledArtifacts


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

    # Remove leading/trailing hyphens and convert to lowercase
    sanitized = sanitized.strip("-").lower()

    return sanitized if sanitized else "default-build"


def validate_build_id(build_id: str) -> bool:
    """
    Validate that a build ID is valid.

    Args:
        build_id: Build ID to validate

    Returns:
        True if valid, False otherwise

    Example:
        >>> validate_build_id("my-build-123")
        True
        >>> validate_build_id("build with spaces")
        False
    """
    if not build_id or not isinstance(build_id, str):
        return False

    # Check for invalid characters
    invalid_chars = [" ", "/"]
    for char in invalid_chars:
        if char in build_id:
            return False

    return True


def _extract_field_from_artifact(artifact_info: ArtifactMetadata | dict[str, Any], field_name: str) -> str | None:
    """
    Extract a field from artifact labels (helper function).

    Args:
        artifact_info: Artifact metadata (ArtifactMetadata or dict)
        field_name: Field name to extract

    Returns:
        Field value or None
    """
    if isinstance(artifact_info, ArtifactMetadata):
        return (artifact_info.pulp_labels or {}).get(field_name)

    if isinstance(artifact_info, dict):
        raw = artifact_info.get("pulp_labels")
        if isinstance(raw, dict):
            return raw.get(field_name)
        return None

    return None


def extract_metadata_from_artifact_json(
    artifact_json: dict[str, Any] | PulpResultsDocument,
    field_name: str,
    fallback: str | None = None,
) -> str | None:
    """
    Extract any metadata field from artifact JSON.

    Args:
        artifact_json: Artifact metadata from distribution client (Dict or PulpResultsDocument)
        field_name: Field to extract from labels (e.g., 'build_id', 'namespace', 'parent_package')
        fallback: Value to return if field not found

    Returns:
        Field value extracted from artifact metadata, or fallback if not found

    Example:
        >>> metadata = {"artifacts": {"rpm1": {"labels": {"build_id": "build-123"}}}}
        >>> extract_metadata_from_artifact_json(metadata, "build_id", fallback="rok-storage")
        'build-123'
    """
    # Handle both Dict and PulpResultsDocument types
    if isinstance(artifact_json, PulpResultsDocument):
        artifacts = artifact_json.artifacts
    else:
        # Handle raw dictionary
        artifacts_raw = artifact_json.get("artifacts", {})
        artifacts = {}
        for name, metadata in artifacts_raw.items():
            if isinstance(metadata, dict):
                # Ensure labels is a dict, not None
                metadata_dict = dict(metadata)
                if metadata_dict.get("pulp_labels") is None:
                    metadata_dict["pulp_labels"] = {}
                artifacts[name] = ArtifactMetadata(**metadata_dict)
            else:
                artifacts[name] = metadata

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


def extract_metadata_from_artifacts(
    pulled_artifacts: "PulledArtifacts", field_name: str, fallback: str | None = None
) -> str | None:
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


def extract_build_id_from_artifact_json(artifact_json: dict[str, Any] | PulpResultsDocument) -> str:
    """
    Extract build_id from artifact_json metadata.

    Convenience wrapper around extract_metadata_from_artifact_json for build_id extraction.

    Args:
        artifact_json: Artifact metadata from distribution client

    Returns:
        Build ID string, or "rok-storage" as default if not found
    """
    return extract_metadata_from_artifact_json(artifact_json, "build_id", fallback="rok-storage") or "rok-storage"


def extract_build_id_from_artifacts(pulled_artifacts: "PulledArtifacts") -> str:
    """
    Extract build_id from the first available artifact's labels.

    Convenience wrapper around extract_metadata_from_artifacts for build_id extraction.

    Args:
        pulled_artifacts: PulledArtifacts model containing downloaded artifacts

    Returns:
        Build ID string, or "rok-storage" as default if not found
    """
    return extract_metadata_from_artifacts(pulled_artifacts, "build_id", fallback="rok-storage") or "rok-storage"


def determine_build_id(
    args: Any,
    artifact_json: dict[str, Any] | PulpResultsDocument | None = None,
    pulled_artifacts: Optional["PulledArtifacts"] = None,
) -> str:
    """
    Determine build ID from command line arguments, artifact metadata, or pulled artifacts.

    Priority: command line argument > artifact_json > pulled_artifacts > default

    Args:
        args: Command line arguments
        artifact_json: Optional artifact metadata (Dict or PulpResultsDocument)
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


__all__ = [
    "strip_namespace_from_build_id",
    "sanitize_build_id_for_repository",
    "validate_build_id",
    "_extract_field_from_artifact",
    "extract_metadata_from_artifact_json",
    "extract_metadata_from_artifacts",
    "extract_build_id_from_artifact_json",
    "extract_build_id_from_artifacts",
    "determine_build_id",
]
