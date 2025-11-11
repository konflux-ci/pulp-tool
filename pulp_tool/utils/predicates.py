"""
Boolean predicates and helper functions for clean conditional logic.

This module provides reusable boolean predicates to extract complex
conditional logic into named functions.
"""

from typing import Optional


def is_remote_url(url: str) -> bool:
    """
    Check if a URL is a remote HTTP/HTTPS URL.

    Args:
        url: URL string to check

    Returns:
        True if URL starts with http:// or https://

    Example:
        >>> is_remote_url("https://example.com/file")
        True
        >>> is_remote_url("/local/path/file")
        False
    """
    return url.startswith(("http://", "https://"))


def has_required_certificates(cert_path: Optional[str], key_path: Optional[str]) -> bool:
    """
    Check if both certificate paths are provided.

    Args:
        cert_path: Path to certificate file
        key_path: Path to key file

    Returns:
        True if both paths are provided (not None)

    Example:
        >>> has_required_certificates("/path/cert", "/path/key")
        True
        >>> has_required_certificates("/path/cert", None)
        False
    """
    return cert_path is not None and key_path is not None


def is_artifact_type(artifact_name: str, artifact_type: str) -> bool:
    """
    Check if artifact name matches a specific type.

    Args:
        artifact_name: Name of the artifact
        artifact_type: Type to check ('rpm', 'log', 'sbom')

    Returns:
        True if artifact name contains the type indicator

    Example:
        >>> is_artifact_type("package.rpm", "rpm")
        True
        >>> is_artifact_type("build.log", "log")
        True
    """
    type_indicators = {
        "rpm": "rpm",
        "log": "log",
        "sbom": "sbom",
    }

    indicator = type_indicators.get(artifact_type)
    if not indicator:
        return False

    return indicator in artifact_name.lower()


def file_exists_and_readable(file_path: str) -> bool:
    """
    Check if file exists and is readable.

    Args:
        file_path: Path to file

    Returns:
        True if file exists and is readable

    Example:
        >>> file_exists_and_readable("/etc/passwd")  # doctest: +SKIP
        True
    """
    import os

    return os.path.exists(file_path) and os.access(file_path, os.R_OK)


def is_empty_file(file_path: str) -> bool:
    """
    Check if file is empty (0 bytes).

    Args:
        file_path: Path to file

    Returns:
        True if file size is 0

    Example:
        >>> is_empty_file("/tmp/empty.txt")  # doctest: +SKIP
        False
    """
    import os

    try:
        return os.path.getsize(file_path) == 0
    except OSError:
        return True  # Treat inaccessible files as empty


def is_valid_build_id(build_id: Optional[str]) -> bool:
    """
    Check if build ID is valid (not None or empty).

    Args:
        build_id: Build ID to validate

    Returns:
        True if build_id is a non-empty string

    Example:
        >>> is_valid_build_id("my-build")
        True
        >>> is_valid_build_id("")
        False
        >>> is_valid_build_id(None)
        False
    """
    return bool(build_id and isinstance(build_id, str) and build_id.strip())


def should_use_config(config: Optional[str]) -> bool:
    """
    Check if config path is provided.

    Args:
        config: Config file path

    Returns:
        True if config is not None

    Example:
        >>> should_use_config("/path/to/config.toml")
        True
        >>> should_use_config(None)
        False
    """
    return config is not None


def is_successful_response(status_code: int) -> bool:
    """
    Check if HTTP status code indicates success (2xx).

    Args:
        status_code: HTTP status code

    Returns:
        True if status code is in 200-299 range

    Example:
        >>> is_successful_response(200)
        True
        >>> is_successful_response(404)
        False
    """
    return 200 <= status_code < 300


def is_client_error(status_code: int) -> bool:
    """
    Check if HTTP status code indicates client error (4xx).

    Args:
        status_code: HTTP status code

    Returns:
        True if status code is in 400-499 range

    Example:
        >>> is_client_error(404)
        True
        >>> is_client_error(500)
        False
    """
    return 400 <= status_code < 500


def is_server_error(status_code: int) -> bool:
    """
    Check if HTTP status code indicates server error (5xx).

    Args:
        status_code: HTTP status code

    Returns:
        True if status code is in 500-599 range

    Example:
        >>> is_server_error(500)
        True
        >>> is_server_error(404)
        False
    """
    return 500 <= status_code < 600


__all__ = [
    "is_remote_url",
    "has_required_certificates",
    "is_artifact_type",
    "file_exists_and_readable",
    "is_empty_file",
    "is_valid_build_id",
    "should_use_config",
    "is_successful_response",
    "is_client_error",
    "is_server_error",
]
