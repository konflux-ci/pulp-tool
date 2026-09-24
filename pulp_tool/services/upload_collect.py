"""
Collect results from Pulp after uploads and publish ``pulp_results.json``.

Split from ``upload_service`` to keep gather/Konflux result handling in one module.
"""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ..models.artifacts import ContentData, ExtraArtifactRef, FileInfoMap, FileInfoModel, PulpContentRow
from ..models.context import UploadContext
from ..models.pulp_api import TaskResponse
from ..models.results import PulpResultsModel

if TYPE_CHECKING:
    from ..api.pulp_client import PulpClient  # pragma: no cover

from ..utils import PulpHelper, create_labels
from ..utils.constants import (
    RESULTS_JSON_FILENAME,
    SUPPORTED_ARCHITECTURES,
    results_json_rpm_arch_distribution_key,
)
from ..utils.pulp_results_oci_publish import sync_pulp_results_with_oci_registry
from ..utils.pulp_tasks import create_file_content_and_wait
from ..utils.response_utils import content_find_results_from_response
from .upload_common import _distribution_urls_for_context


def _serialize_results_to_json(results: dict[str, Any]) -> str:
    """Serialize results to JSON with error handling."""
    try:
        logging.debug("Results data before JSON serialization: %s", results)
        json_content = json.dumps(results, indent=2)
        logging.debug("Successfully created JSON content, length: %d", len(json_content))
        preview = json_content[:500] + "..." if len(json_content) > 500 else json_content
        logging.debug("JSON content preview: %s", preview)
        return json_content
    except (TypeError, ValueError) as e:
        logging.error("Failed to serialize results to JSON: %s", e)
        logging.error("Results data: %s", results)
        logging.error("Traceback: %s", traceback.format_exc())
        for key, value in results.items():
            try:
                json.dumps(value)
                logging.debug("Key '%s' serializes successfully", key)
            except (TypeError, ValueError) as key_error:
                logging.error("Key '%s' failed to serialize: %s", key, key_error)
        raise


def _save_results_to_folder(folder_path: str, json_content: str, context: UploadContext) -> Path | None:
    """
    Save results JSON to a local folder instead of uploading to Pulp.

    Creates the folder if it does not exist. Writes pulp_results.json to it.
    Also handles sbom_results if configured.

    Args:
        folder_path: Path to output directory
        json_content: Serialized results JSON
        context: Upload context (for sbom_results)

    Returns:
        Path to the saved file, or None on failure
    """
    try:
        output_dir = Path(folder_path).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / RESULTS_JSON_FILENAME
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json_content)
        logging.info("Results JSON saved to %s (skipped Pulp upload)", output_file)
        if context.sbom_results:
            _handle_sbom_results(None, context, json_content)  # type: ignore[arg-type]
        return output_file
    except OSError as e:
        logging.error("Failed to save results JSON to folder %s: %s", folder_path, e)
        logging.error("Traceback: %s", traceback.format_exc())
        return None


def _konflux_artifact_results_paths(context: UploadContext) -> tuple[str, str] | None:
    artifact_results = (context.artifact_results or "").strip()
    if not artifact_results or "," not in artifact_results:
        return None
    url_path, digest_path = artifact_results.split(",", 1)
    return url_path.strip(), digest_path.strip()


def _upload_and_get_results_url(
    client: PulpClient, context: UploadContext, artifact_repository_prn: str, json_content: str, date: str
) -> str | None:
    """Upload results JSON and return the distribution URL."""
    labels = create_labels(context.build_id, "", context.namespace, context.parent_package, date)
    konflux_paths = _konflux_artifact_results_paths(context)
    oci_storage = (getattr(context, "oci_storage", None) or "").strip()

    try:
        if oci_storage:
            document = cast(dict[str, Any], json.loads(json_content))
            oci_ref, task_response = sync_pulp_results_with_oci_registry(
                client,
                artifact_repository_prn,
                document,
                oci_storage,
                labels,
                build_id=context.build_id,
                record_manifest_history=False,
            )
            logging.info("Results JSON uploaded to Pulp and ORAS")
            results_json_url = _extract_results_url(client, context, task_response)
            if konflux_paths:
                _write_konflux_oci_results(oci_ref, konflux_paths[0], konflux_paths[1])
        else:
            task_response = create_file_content_and_wait(
                client,
                artifact_repository_prn,
                json_content,
                build_id=context.build_id,
                pulp_label=labels,
                filename=RESULTS_JSON_FILENAME,
                operation="upload results JSON",
            )
            logging.info("Results JSON uploaded successfully")
            results_json_url = _extract_results_url(client, context, task_response)
            if konflux_paths:
                _handle_artifact_results(client, context, task_response)
            else:
                logging.info("Results JSON available at: %s", results_json_url)

        if context.sbom_results:
            _handle_sbom_results(client, context, json_content)

        return results_json_url

    except Exception as e:
        logging.error("Failed to upload results JSON: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
        raise


def _extract_results_url(client: PulpClient, context: UploadContext, task_response: TaskResponse) -> str:
    """Extract results JSON URL from task response."""
    logging.debug("Task response for results JSON: state=%s", task_response.state)

    repository_helper = PulpHelper(client, parent_package=context.parent_package)
    distribution_urls = repository_helper.get_distribution_urls(context.build_id)

    logging.debug("Available distribution URLs: %s", list(distribution_urls.keys()))
    for repo_type, url in distribution_urls.items():
        logging.debug("  %s: %s", repo_type, url)

    if "artifacts" not in distribution_urls:
        raise ValueError(f"No distribution URL found for artifacts repository (build_id: {context.build_id})")

    artifacts_dist_url = distribution_urls["artifacts"]
    logging.info("Using artifacts distribution URL: %s", artifacts_dist_url)

    relative_path = task_response.result.get("relative_path") if task_response.result else None
    if not relative_path:
        raise ValueError("Task response does not contain relative_path in result")

    logging.info("Task response relative_path: %s", relative_path)

    final_url = f"{artifacts_dist_url}{relative_path}"
    logging.info("Final results JSON URL: %s", final_url)

    return final_url


def _gather_and_validate_content(
    client: PulpClient, context: UploadContext, extra_artifacts: list[ExtraArtifactRef] | None
) -> ContentData | None:
    """Gather content data and validate it's not empty."""
    logging.info("Collecting results for build ID: %s", context.build_id)
    logging.info("Extra artifacts provided: %d", len(extra_artifacts) if extra_artifacts else 0)

    content_data = client.gather_content_data(context.build_id, extra_artifacts)

    if not content_data.content_results:
        logging.error("No content found for build ID: %s", context.build_id)
        logging.error("This usually means content hasn't been indexed yet or build_id label is missing")
        return None

    logging.info("Successfully gathered %d content items", len(content_data.content_results))
    return content_data


def _build_artifact_map(client: PulpClient, content_results: list[PulpContentRow]) -> FileInfoMap:
    """Build map of artifact hrefs to file information."""
    logging.info("Building results structure from %d content items", len(content_results))

    artifact_hrefs = [
        {"pulp_href": artifact_href}
        for content in content_results
        for artifact_href in (content.artifacts or {}).values()
        if artifact_href and "/artifacts/" in artifact_href
    ]

    logging.info("Extracted %d artifact hrefs to query for file locations", len(artifact_hrefs))

    file_info_map: FileInfoMap = {}
    if artifact_hrefs:
        logging.debug("Querying file locations for artifact hrefs: %s", [a["pulp_href"] for a in artifact_hrefs[:3]])
        file_locations_json = client.get_file_locations(artifact_hrefs).json()["results"]
        file_info_map = {
            file_info["pulp_href"]: FileInfoModel(
                pulp_href=file_info["pulp_href"],
                file=file_info["file"],
                sha256=file_info.get("sha256"),
                size=file_info.get("size"),
            )
            for file_info in file_locations_json
        }
        logging.info("Retrieved file locations for %d artifacts", len(file_info_map))
    else:
        logging.warning("No artifact hrefs found to query for file locations")

    return file_info_map


def _populate_results_model(
    client: PulpClient,
    results_model: PulpResultsModel,
    content_results: list[PulpContentRow],
    file_info_map: FileInfoMap,
    context: UploadContext,
) -> None:
    """Populate results model with artifacts from content results."""
    repository_helper = PulpHelper(client, parent_package=context.parent_package)
    distribution_urls = _distribution_urls_for_context(repository_helper, context.build_id, context)
    target_arch_repo = bool(getattr(context, "target_arch_repo", False))

    client.build_results_structure(
        results_model,
        content_results,
        file_info_map,
        distribution_urls,
        target_arch_repo=target_arch_repo,
        merge=True,
    )


def _add_distributions_to_results(client: PulpClient, context: UploadContext, results_model: PulpResultsModel) -> None:
    """Add distribution URLs to results model."""
    repository_helper = PulpHelper(client, parent_package=context.parent_package)
    distribution_urls = _distribution_urls_for_context(repository_helper, context.build_id, context)

    if distribution_urls:
        for repo_type, url in distribution_urls.items():
            results_model.add_distribution(repo_type, url)
            logging.debug("Distribution URL for %s: %s", repo_type, url)
        logging.info("Added distribution URLs for %d repository types", len(distribution_urls))
    else:
        logging.warning("No distribution URLs found")

    if bool(getattr(context, "target_arch_repo", False)) and results_model.artifacts:
        arch_urls: dict[str, str] = {}
        for info in results_model.artifacts.values():
            arch = (info.labels.get("arch") or "").strip()
            if arch in SUPPORTED_ARCHITECTURES:
                arch_urls[arch] = repository_helper.distribution_url_for_base_path(arch)
        for arch in sorted(arch_urls.keys()):
            dist_key = results_json_rpm_arch_distribution_key(arch)
            results_model.add_distribution(dist_key, arch_urls[arch])
            logging.debug("Per-arch distribution URL for %s (%s): %s", dist_key, arch, arch_urls[arch])
        if arch_urls:
            logging.info("Added %d per-arch RPM distribution URL(s)", len(arch_urls))


def collect_results(
    client: PulpClient,
    context: UploadContext,
    date: str,
    results_model: PulpResultsModel,
    extra_artifacts: list[ExtraArtifactRef] | None = None,
) -> str | None:
    """
    Collect results and upload JSON directly from memory.

    This function orchestrates gathering content, building results structure,
    and uploading the results JSON to the artifacts repository.
    """
    content_data = _gather_and_validate_content(client, context, extra_artifacts)

    if context.artifact_results and "," not in context.artifact_results.strip():
        if content_data:
            file_info_map = _build_artifact_map(client, content_data.content_results)
            _populate_results_model(client, results_model, content_data.content_results, file_info_map, context)
        _add_distributions_to_results(client, context, results_model)
        json_content = _serialize_results_to_json(results_model.to_json_dict())
        output_path = _save_results_to_folder(context.artifact_results.strip(), json_content, context)
        return str(output_path) if output_path else None

    if not content_data:
        if results_model.artifact_count or results_model.distributions:
            logging.info("No gathered content; using incrementally populated results model only")
            _add_distributions_to_results(client, context, results_model)
            json_content = _serialize_results_to_json(results_model.to_json_dict())
            return _upload_and_get_results_url(
                client, context, results_model.repositories.artifacts_prn, json_content, date
            )
        return None

    file_info_map = _build_artifact_map(client, content_data.content_results)
    _populate_results_model(client, results_model, content_data.content_results, file_info_map, context)
    _add_distributions_to_results(client, context, results_model)
    json_content = _serialize_results_to_json(results_model.to_json_dict())

    return _upload_and_get_results_url(client, context, results_model.repositories.artifacts_prn, json_content, date)


def _find_artifact_content(client: PulpClient, task_response: TaskResponse) -> tuple[str, str] | None:
    """Find artifact content from task response and get file and sha256 from artifacts API."""
    logging.debug("Task response: state=%s, created_resources=%s", task_response.state, task_response.created_resources)

    artifact_href = next((a for a in task_response.created_resources if "content" in a), None)
    if not artifact_href:
        logging.error("No content artifact found in task response")
        return None

    content_resp = content_find_results_from_response(
        client.find_content("href", artifact_href), "find content by href (task artifact)"
    )
    if not content_resp:
        logging.error("No content found for href: %s", artifact_href)
        return None

    artifacts_dict = content_resp[0]["artifacts"]

    if isinstance(artifacts_dict, dict):
        artifact_hrefs = [href for href in artifacts_dict.values() if href and "/artifacts/" in str(href)]
    else:
        artifact_hrefs = [artifacts_dict] if artifacts_dict else []

    if not artifact_hrefs:
        logging.error("No artifact hrefs found in content response")
        return None

    artifact_hrefs_formatted = [{"pulp_href": href} for href in artifact_hrefs]
    artifact_response = client.get_file_locations(artifact_hrefs_formatted).json()["results"][0]
    file_value = artifact_response.get("file", "")
    sha256_value = artifact_response.get("sha256", "")

    if not file_value:
        logging.error("No file value found in artifact response")
        return None

    if not sha256_value:
        logging.error("No sha256 value found in artifact response")
        return None

    return (file_value, sha256_value)


def _parse_oci_reference(oci_reference: str) -> tuple[str, str]:
    """Parse OCI reference into URL and digest parts."""
    if "@" in oci_reference:
        image_url, digest = oci_reference.rsplit("@", 1)
        logging.debug("Parsed OCI reference: URL=%s, digest=%s", image_url, digest)
        return image_url, digest
    logging.debug("OCI reference has no digest: %s", oci_reference)
    return oci_reference, ""


def _write_konflux_results(image_url: str, digest: str, url_path: str, digest_path: str) -> None:
    """Write Konflux result files."""
    with open(url_path, "w", encoding="utf-8") as f:
        f.write(image_url)

    with open(digest_path, "w", encoding="utf-8") as f:
        f.write(digest)

    logging.info("Artifact results written to %s and %s", url_path, digest_path)
    logging.debug("Image URL: %s", image_url)
    logging.debug("Image digest: %s", digest)


def _konflux_results_from_oci_ref(oci_ref: str) -> tuple[str, str]:
    """Split ``image@sha256:…`` into Tekton-style URL and digest (matches import-to-quay IMAGE_URL + digest)."""
    image_url, digest = _parse_oci_reference(oci_ref.strip())
    if not digest:
        raise ValueError(f"OCI reference has no digest: {oci_ref}")
    return image_url, _format_sha256_digest(digest)


def _write_konflux_oci_results(oci_ref: str, url_path: str, digest_path: str) -> tuple[str, str]:
    """Write Konflux ``PULP-IMAGE_URL`` / ``PULP-IMAGE_DIGEST`` files from an ORAS-published manifest ref."""
    image_url, digest = _konflux_results_from_oci_ref(oci_ref)
    _write_konflux_results(image_url, digest, url_path.strip(), digest_path.strip())
    return image_url, digest


def _format_sha256_digest(sha256_hex: str) -> str:
    """Format a SHA256 hex digest for Konflux artifact result files."""
    if sha256_hex.startswith("sha256:"):
        return sha256_hex
    return f"sha256:{sha256_hex}"


def _handle_artifact_results(client: PulpClient, context: UploadContext, task_response: TaskResponse) -> None:
    """Handle artifact results for Konflux integration."""
    repository_helper = PulpHelper(client, parent_package=context.parent_package)
    distribution_urls = repository_helper.get_distribution_urls(context.build_id)

    if "artifacts" not in distribution_urls:
        logging.error("No distribution URL found for artifacts repository (build_id: %s)", context.build_id)
        return

    artifacts_dist_url = distribution_urls["artifacts"]

    relative_path = task_response.result.get("relative_path") if task_response.result else None
    if not relative_path:
        logging.error("Task response does not contain relative_path in result")
        return

    distribution_file_url = f"{artifacts_dist_url}{relative_path}"

    if not context.artifact_results:
        logging.debug("No artifact_results path configured, skipping artifact results handling")
        return

    try:
        image_url_path, image_digest_path = context.artifact_results.split(",")
    except ValueError as e:
        logging.error("Invalid artifact_results format: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
        return

    artifact_info = _find_artifact_content(client, task_response)
    if not artifact_info:
        logging.error("Could not resolve artifact digest for Konflux artifact results")
        return

    _file_ref, sha256_hex = artifact_info
    image_url = distribution_file_url
    digest = _format_sha256_digest(sha256_hex)

    _write_konflux_results(image_url, digest, image_url_path, image_digest_path)


def _resolve_sbom_results_url(results: dict[str, Any], context: UploadContext) -> tuple[str | None, str | None]:
    """Return SBOM artifact key and distribution URL from serialized results JSON."""
    artifacts = results.get("artifacts") or {}

    for artifact_name, artifact_info in artifacts.items():
        if "sbom" not in artifact_name.lower():
            continue
        labels = artifact_info.get("labels") or {}
        if labels.get("arch"):
            continue
        url = (artifact_info.get("url") or "").strip()
        if url:
            return artifact_name, url

    for artifact_name, artifact_info in artifacts.items():
        if not any(artifact_name.endswith(ext) for ext in (".json", ".spdx", ".spdx.json")):
            continue
        labels = artifact_info.get("labels") or {}
        if labels.get("arch"):
            continue
        url = (artifact_info.get("url") or "").strip()
        if url:
            return artifact_name, url

    sbom_dist = (results.get("distributions") or {}).get("sbom")
    if not sbom_dist:
        return None, None

    sbom_path = getattr(context, "sbom_path", None)
    basename = Path(sbom_path).name if sbom_path else "sbom.json"
    dist_base = str(sbom_dist).rstrip("/")
    return basename, f"{dist_base}/{basename}"


def _handle_sbom_results(client: PulpClient, context: UploadContext, json_content: str) -> None:  # pylint: disable=unused-argument
    """Handle SBOM results for Konflux integration."""
    try:
        results = json.loads(json_content)

        sbom_file, sbom_url = _resolve_sbom_results_url(results, context)

        if not sbom_url:
            logging.info("No SBOM file found in results JSON (this is normal if no SBOM was uploaded)")
            return

        if not context.sbom_results:
            logging.debug("No sbom_results path configured, skipping SBOM results file write")
            return

        sbom_results_path = Path(context.sbom_results)
        sbom_results_path.parent.mkdir(parents=True, exist_ok=True)
        sbom_results_path.write_text(sbom_url, encoding="utf-8")

        logging.info("SBOM results written to %s: %s", context.sbom_results, sbom_file)
        logging.debug("SBOM URL: %s", sbom_url)

    except (ValueError, KeyError) as e:
        logging.error("Failed to process SBOM results: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())
    except OSError as e:
        logging.error("Failed to write SBOM results file: %s", e)
        logging.error("Traceback: %s", traceback.format_exc())


__all__ = [
    "collect_results",
    "_serialize_results_to_json",
    "_save_results_to_folder",
    "_upload_and_get_results_url",
    "_extract_results_url",
    "_gather_and_validate_content",
    "_build_artifact_map",
    "_populate_results_model",
    "_add_distributions_to_results",
    "_find_artifact_content",
    "_parse_oci_reference",
    "_write_konflux_oci_results",
    "_konflux_results_from_oci_ref",
    "_handle_artifact_results",
    "_handle_sbom_results",
]
