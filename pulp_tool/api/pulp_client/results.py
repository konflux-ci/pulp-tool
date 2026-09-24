"""Gather content results and build upload results models for ``PulpClient``."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from ...models.artifacts import ContentData, ExtraArtifactRef, FileInfoMap, PulpContentRow
from ...utils.response_utils import content_find_results_from_response
from ...utils.rpm_operations import calculate_sha256_checksum


class PulpClientResultsMixin:
    """Mixin: ``gather_content_data`` and ``build_results_structure`` for upload results."""

    def gather_content_data(self, build_id: str, extra_artifacts: list[ExtraArtifactRef] | None = None) -> ContentData:
        """
        Gather content data and artifacts for a build ID.

        Args:
            build_id: Build identifier
            extra_artifacts: Optional extra artifacts to include (from created_resources)

        Returns:
            ContentData containing content results and artifacts
        """
        raw_results: list[dict[str, Any]] = []
        artifacts: list[dict[str, str]] = []

        # Always use bulk query by build_id for efficiency
        # This gets all content in a single API call instead of N individual calls
        if extra_artifacts:
            logging.info("Found %d created resources, querying all content by build_id", len(extra_artifacts))
        else:
            logging.debug("Searching for content by build_id")

        try:
            resp = self.find_content("build_id", build_id)
            raw_results = content_find_results_from_response(resp, "find content by build_id")
        except Exception:
            logging.error("Failed to get content by build ID", exc_info=True)
            raise

        # If no results from build_id query and we have extra_artifacts, try querying by href
        # This handles the case where content hasn't been indexed yet
        if not raw_results and extra_artifacts:
            href_list = [href for a in extra_artifacts if (href := (a.pulp_href or "").strip()) and "/content/" in href]
            logging.warning(
                "No content found by build_id, trying direct href query for %d content href(s) (%d extra ref(s))",
                len(href_list),
                len(extra_artifacts),
            )
            try:
                if href_list:
                    href_query = ",".join(href_list)
                    resp = self.find_content("href", href_query)
                    raw_results = content_find_results_from_response(resp, "find content by href")
                    logging.info("Found %d content items by href query", len(raw_results))
            except Exception:
                logging.error("Failed to get content by href", exc_info=True)
                # Don't raise, just continue with empty results

        if not raw_results:
            logging.warning("No content found for build ID: %s", build_id)
            return ContentData()

        content_results = [PulpContentRow.model_validate(r) for r in raw_results]

        logging.info("Found %d content items for build_id: %s", len(content_results), build_id)

        # Log details about what content was found
        if content_results:
            logging.info("Content types found:")
            for idx, result in enumerate(content_results):
                pulp_href = result.pulp_href
                content_type = self._get_content_type_from_href(pulp_href)

                # Get relative paths from artifacts dict
                artifacts_dict = result.artifacts or {}
                if artifacts_dict:
                    relative_paths = list(artifacts_dict.keys())
                    logging.info("  - %s: %s", content_type, ", ".join(relative_paths))
                else:
                    logging.info("  - %s: no artifacts", content_type)

                # Log full structure for first item to help with debugging
                if idx == 0:
                    logging.debug(
                        "First content item full structure: %s",
                        json.dumps(result.model_dump(), indent=2, default=str),
                    )

        # Extract artifacts from content results
        # Content structure has "artifacts" (plural) field which is a dict: {relative_path: artifact_href}
        artifacts = [
            {"artifact": artifact_href}
            for result in content_results
            for artifact_href in (result.artifacts or {}).values()
            if artifact_href
        ]

        logging.info("Extracted %d artifact hrefs from content results", len(artifacts))
        return ContentData(content_results=content_results, artifacts=artifacts)

    def add_uploaded_artifact_to_results_model(
        self,
        results_model: Any,
        *,
        local_path: str,
        labels: dict[str, str],
        is_rpm: bool,
        distribution_urls: dict[str, str],
        target_arch_repo: bool = False,
        file_relative_path: str | None = None,
    ) -> None:
        """
        Add one uploaded artifact to PulpResultsModel using the same keys and URLs as gather/build.

        Called after upload tasks succeed so results JSON can be built incrementally.
        """
        relative_path = os.path.basename(local_path) if is_rpm else (file_relative_path or os.path.basename(local_path))
        build_id = labels.get("build_id", "")
        if is_rpm:
            artifact_key = relative_path
        else:
            artifact_key = f"{build_id}/{relative_path}" if build_id else relative_path

        sha256_hex = calculate_sha256_checksum(local_path)
        artifact_url = self._build_artifact_distribution_url(
            relative_path,
            is_rpm,
            labels,
            distribution_urls,
            target_arch_repo=target_arch_repo,
        )
        results_model.add_artifact(key=artifact_key, url=artifact_url, sha256=sha256_hex, labels=labels)

    def build_results_structure(
        self,
        results_model: Any,
        content_results: list[PulpContentRow],
        file_info_map: FileInfoMap,
        distribution_urls: dict[str, str] | None = None,
        *,
        target_arch_repo: bool = False,
        merge: bool = False,
    ) -> Any:
        """
        Build the results structure from content and file info using optimized single-pass processing.

        Args:
            results_model: PulpResultsModel to populate with artifacts
            content_results: Content data from Pulp
            file_info_map: Mapping of artifact hrefs to file info models
            distribution_urls: Optional dictionary mapping repo_type to distribution base URL
            target_arch_repo: When True, RPM URLs use per-arch distribution paths from labels
            merge: When True, skip artifact keys already present (incremental upload + reconcile)

        Returns:
            Populated PulpResultsModel
        """
        logging.info("Building results structure:")
        logging.info("  - Content items: %d", len(content_results))
        logging.info("  - File info entries: %d", len(file_info_map))

        # Track statistics for logging
        missing_artifacts = 0
        missing_file_info = 0

        for idx, content in enumerate(content_results):
            labels = dict(content.pulp_labels or {})
            build_id = labels.get("build_id", "")
            pulp_href = content.pulp_href or "unknown"

            # Content structure has "artifacts" (plural) field which is a dict: {relative_path: artifact_href}
            artifacts_dict = content.artifacts or {}

            if not artifacts_dict:
                missing_artifacts += 1
                # Only log details for the first few items to avoid spam
                if idx < 3:
                    logging.warning(
                        "Content item %d structure (no artifacts field). Available fields: %s",
                        idx,
                        list(content.model_dump(exclude_none=True).keys()),
                    )
                    logging.debug("Full content: %s", json.dumps(content.model_dump(), indent=2, default=str))
                continue

            # Determine content type once per content item (cached via lru_cache)
            pulp_type = self._get_content_type_from_href(pulp_href)
            is_rpm = "rpm" in pulp_type.lower()

            # Process all artifacts in a single pass
            for relative_path, artifact_href in artifacts_dict.items():
                # Skip invalid artifact hrefs
                if not artifact_href or "/artifacts/" not in artifact_href:
                    continue

                # Get file info
                file_info = file_info_map.get(artifact_href)
                if not file_info:
                    missing_file_info += 1
                    if missing_file_info <= 3:  # Only log first few
                        logging.warning("No file info found for artifact href: %s", artifact_href)
                    continue

                # Construct artifact key based on content type (optimized logic)
                if is_rpm:
                    # RPM content - use just the filename as the key
                    artifact_key = relative_path
                else:
                    # File content (logs, SBOM, etc.) - use build_id/relative_path
                    artifact_key = f"{build_id}/{relative_path}" if build_id else relative_path
                    if not build_id and missing_file_info <= 1:
                        logging.warning(
                            "No build_id in labels for file content, using relative_path only: %s", relative_path
                        )

                # Construct distribution URL instead of using file_info.file (which is an API href)
                artifact_url = self._build_artifact_distribution_url(
                    relative_path,
                    is_rpm,
                    labels,
                    distribution_urls or {},
                    target_arch_repo=target_arch_repo,
                )

                if merge and artifact_key in results_model.artifacts:
                    existing = results_model.artifacts[artifact_key]
                    gi_sha = file_info.sha256 or ""
                    if existing.url != artifact_url or (existing.sha256 or "") != gi_sha:
                        logging.warning(
                            "Gathered artifact %s differs from incremental entry (keeping incremental)",
                            artifact_key,
                        )
                    continue

                # Add artifact to results model
                results_model.add_artifact(
                    key=artifact_key, url=artifact_url, sha256=file_info.sha256 or "", labels=labels
                )

        # Log summary statistics
        logging.info("Final results: %d artifacts processed", results_model.artifact_count)
        if missing_artifacts > 0:
            logging.warning("Content items without artifacts field: %d", missing_artifacts)
        if missing_file_info > 3:
            logging.warning("Missing file info for %d artifacts", missing_file_info)

        return results_model
