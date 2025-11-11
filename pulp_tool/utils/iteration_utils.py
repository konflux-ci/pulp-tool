"""
Iteration utilities for working with artifact collections.

This module provides reusable iteration patterns for artifacts
to eliminate code duplication.
"""

from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from ..models.artifacts import PulledArtifacts, ArtifactFile


# Standard artifact types in order
ARTIFACT_TYPES = ["rpms", "sboms", "logs"]


def iterate_artifact_types(
    pulled_artifacts: PulledArtifacts, *, types: Optional[List[str]] = None
) -> Iterator[Tuple[str, Dict[str, ArtifactFile]]]:
    """
    Iterate over artifact types and their collections.

    Args:
        pulled_artifacts: PulledArtifacts model containing artifacts
        types: Optional list of types to iterate (defaults to all)

    Yields:
        Tuples of (artifact_type, artifacts_dict)

    Example:
        >>> for artifact_type, artifacts in iterate_artifact_types(pulled):
        ...     print(f"{artifact_type}: {len(artifacts)} items")
    """
    types_to_iterate = types or ARTIFACT_TYPES

    for artifact_type in types_to_iterate:
        artifacts_dict = getattr(pulled_artifacts, artifact_type, {})
        if artifacts_dict:
            yield artifact_type, artifacts_dict


def iterate_all_artifacts(
    pulled_artifacts: PulledArtifacts, *, types: Optional[List[str]] = None
) -> Iterator[Tuple[str, str, ArtifactFile]]:
    """
    Iterate over all individual artifacts across types.

    Args:
        pulled_artifacts: PulledArtifacts model containing artifacts
        types: Optional list of types to iterate (defaults to all)

    Yields:
        Tuples of (artifact_type, artifact_name, artifact_data)

    Example:
        >>> for type_, name, data in iterate_all_artifacts(pulled):
        ...     print(f"{type_}: {name} at {data.file}")
    """
    for artifact_type, artifacts_dict in iterate_artifact_types(pulled_artifacts, types=types):
        for artifact_name, artifact_data in artifacts_dict.items():
            yield artifact_type, artifact_name, artifact_data


def filter_artifacts(
    pulled_artifacts: PulledArtifacts,
    predicate: Callable[[str, str, ArtifactFile], bool],
    *,
    types: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Filter artifacts based on a predicate function.

    Args:
        pulled_artifacts: PulledArtifacts model containing artifacts
        predicate: Function that takes (type, name, data) and returns bool
        types: Optional list of types to filter (defaults to all)

    Returns:
        Dictionary mapping artifact_type to filtered artifacts

    Example:
        >>> def only_x86_64(type_, name, data):
        ...     return data.arch == "x86_64"
        >>> filtered = filter_artifacts(pulled, only_x86_64)
    """
    filtered: Dict[str, Dict[str, Any]] = {}

    for artifact_type, artifact_name, artifact_data in iterate_all_artifacts(pulled_artifacts, types=types):
        if predicate(artifact_type, artifact_name, artifact_data):
            if artifact_type not in filtered:
                filtered[artifact_type] = {}
            filtered[artifact_type][artifact_name] = artifact_data

    return filtered


def count_artifacts(pulled_artifacts: PulledArtifacts, *, types: Optional[List[str]] = None) -> Dict[str, int]:
    """
    Count artifacts by type.

    Args:
        pulled_artifacts: PulledArtifacts model containing artifacts
        types: Optional list of types to count (defaults to all)

    Returns:
        Dictionary mapping artifact_type to count

    Example:
        >>> counts = count_artifacts(pulled)
        >>> print(counts)  # {'rpms': 5, 'sboms': 1, 'logs': 3}
    """
    counts = {}

    for artifact_type, artifacts_dict in iterate_artifact_types(pulled_artifacts, types=types):
        counts[artifact_type] = len(artifacts_dict)

    return counts


def extract_unique_labels(
    pulled_artifacts: PulledArtifacts, label_key: str, *, types: Optional[List[str]] = None
) -> set:
    """
    Extract unique label values across all artifacts.

    Args:
        pulled_artifacts: PulledArtifacts model containing artifacts
        label_key: Label key to extract (e.g., "build_id", "arch")
        types: Optional list of types to check (defaults to all)

    Returns:
        Set of unique label values

    Example:
        >>> build_ids = extract_unique_labels(pulled, "build_id")
        >>> architectures = extract_unique_labels(pulled, "arch")
    """
    values = set()

    for _, _, artifact_data in iterate_all_artifacts(pulled_artifacts, types=types):
        if hasattr(artifact_data, "labels") and artifact_data.labels:
            value = artifact_data.labels.get(label_key)
            if value:
                values.add(value)

    return values


def group_artifacts_by_label(
    pulled_artifacts: PulledArtifacts, label_key: str, *, types: Optional[List[str]] = None
) -> Dict[str, List[Tuple[str, str, ArtifactFile]]]:
    """
    Group artifacts by a label value.

    Args:
        pulled_artifacts: PulledArtifacts model containing artifacts
        label_key: Label key to group by (e.g., "arch", "build_id")
        types: Optional list of types to group (defaults to all)

    Returns:
        Dictionary mapping label_value to list of (type, name, data) tuples

    Example:
        >>> by_arch = group_artifacts_by_label(pulled, "arch")
        >>> print(by_arch.keys())  # dict_keys(['x86_64', 'aarch64'])
    """
    groups: Dict[str, List[Tuple[str, str, ArtifactFile]]] = {}

    for artifact_type, artifact_name, artifact_data in iterate_all_artifacts(pulled_artifacts, types=types):
        if hasattr(artifact_data, "labels") and artifact_data.labels:
            value = artifact_data.labels.get(label_key, "unknown")
            if value not in groups:
                groups[value] = []
            groups[value].append((artifact_type, artifact_name, artifact_data))

    return groups


def map_artifacts(
    pulled_artifacts: PulledArtifacts,
    mapper: Callable[[str, str, ArtifactFile], Any],
    *,
    types: Optional[List[str]] = None,
) -> List[Any]:
    """
    Map a function over all artifacts and collect results.

    Args:
        pulled_artifacts: PulledArtifacts model containing artifacts
        mapper: Function that takes (type, name, data) and returns a value
        types: Optional list of types to map over (defaults to all)

    Returns:
        List of mapped values

    Example:
        >>> file_paths = map_artifacts(pulled, lambda t, n, d: d.file)
        >>> sizes = map_artifacts(pulled, lambda t, n, d: os.path.getsize(d.file))
    """
    results = []

    for artifact_type, artifact_name, artifact_data in iterate_all_artifacts(pulled_artifacts, types=types):
        result = mapper(artifact_type, artifact_name, artifact_data)
        results.append(result)

    return results


__all__ = [
    "ARTIFACT_TYPES",
    "iterate_artifact_types",
    "iterate_all_artifacts",
    "filter_artifacts",
    "count_artifacts",
    "extract_unique_labels",
    "group_artifacts_by_label",
    "map_artifacts",
]
