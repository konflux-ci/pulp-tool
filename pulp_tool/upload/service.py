"""Programmatic upload service (thin delegator to PulpHelper)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..models.context import UploadRpmContext
from ..models.repository import RepositoryRefs
from ..utils.pulp_helper import PulpHelper

if TYPE_CHECKING:
    from ..api.pulp_client import PulpClient


class UploadService:
    """Thin delegator for programmatic upload (same path as CLI)."""

    def __init__(self, pulp_client: PulpClient, parent_package: str | None = None) -> None:
        self.client = pulp_client
        self.helper = PulpHelper(pulp_client, parent_package=parent_package)

    def setup_repositories(self, build_id: str) -> RepositoryRefs:
        logging.info("Setting up repositories for build: %s", build_id)
        repositories = self.helper.setup_repositories(build_id)
        logging.info("Repository setup completed")
        return repositories

    def upload_artifacts(self, context: UploadRpmContext, repositories: RepositoryRefs) -> str | None:
        logging.info("Starting upload process for build: %s", context.build_id)
        results_json_url = self.helper.process_uploads(self.client, context, repositories, pulp_helper=self.helper)
        if not results_json_url:
            logging.error("Upload completed but results JSON was not created")
            return None
        logging.info("Upload completed successfully. Results JSON URL: %s", results_json_url)
        return results_json_url

    def get_distribution_urls(self, build_id: str) -> dict[str, str]:
        return self.helper.get_distribution_urls(build_id)
