"""
Repository management for Pulp operations.

This module handles repository creation, retrieval, and distribution management.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from ..exceptions import PulpToolHTTPError
from ..models.pulp_api import (
    DistributionRequest,
    RepositoryRequest,
    TaskResponse,
)
from ..models.repository import RepositoryRefs

if TYPE_CHECKING:
    from ..api.pulp_client import PulpClient  # pragma: no cover

from .constants import (
    API_TYPES,
    REPOSITORY_TYPES,
    SIGNED_REPOSITORY_TYPES,
    SUPPORTED_ARCHITECTURES,
)
from .validation import (
    sanitize_build_id_for_repository,
    strip_namespace_from_build_id,
    validate_build_id,
    validate_repository_setup,
)


@dataclass(frozen=True)
class RepositoryApiOps:
    """
    Bound Pulp repository/distribution operations for one API type (``rpm`` or ``file``).

    Replaces a dict of callables for clearer typing and easier testing.
    """

    client: PulpClient
    repo_type: str

    def get(self, name: str) -> httpx.Response:
        return self.client.repository_operation("get_repo", self.repo_type, name=name)

    def create(self, new_repository: RepositoryRequest) -> httpx.Response:
        return self.client.repository_operation("create_repo", self.repo_type, repository_data=new_repository)

    def distro(self, new_distribution: DistributionRequest) -> httpx.Response:
        return self.client.repository_operation("create_distro", self.repo_type, distribution_data=new_distribution)

    def get_distro(self, name: str) -> httpx.Response:
        return self.client.repository_operation("get_distro", self.repo_type, name=name)

    def update_distro(self, distribution_href: str, publication: str | None) -> httpx.Response:
        return self.client.repository_operation(
            "update_distro",
            self.repo_type,
            distribution_href=distribution_href,
            publication=publication,
        )

    def wait_for_finished_task(self, task_id: str) -> TaskResponse:
        return self.client.wait_for_finished_task(task_id)


@dataclass(frozen=True)
class ExistingDistributionInfo:
    """Existing Pulp distribution fields needed for idempotent create recovery."""

    base_path: str
    repository: str | None = None


def _repository_resource_id(repository_ref: str | None) -> str | None:
    """Extract the Pulp resource id from a PRN or pulp_href."""
    if not repository_ref:
        return None
    ref = str(repository_ref).strip().rstrip("/")
    if not ref:
        return None
    if ref.startswith("prn:"):
        return ref.rsplit(":", 1)[-1]
    return ref.rsplit("/", 1)[-1]


def _repository_identifiers_match(actual: str | None, expected: str | None) -> bool:
    """Return True when two repository references point at the same Pulp resource."""
    if not actual or not expected:
        return False
    if actual == expected:
        return True
    actual_id = _repository_resource_id(actual)
    expected_id = _repository_resource_id(expected)
    return bool(actual_id and expected_id and actual_id == expected_id)


def _resource_log_label(full_name: str) -> str:
    """
    Short label for log messages: last path segment of the Pulp repository/distribution name.

    Examples:
        test-build-1/rpms-signed -> rpms-signed
        test-build-1/rpms -> rpms
        x86_64 -> x86_64
    """
    if not full_name:
        return full_name
    return full_name.rstrip("/").rsplit("/", 1)[-1]


def _is_distribution_uniqueness_error(error_text: str) -> bool:
    """Return True when an error indicates the distribution name or base_path already exists."""
    if not error_text:
        return False
    lower = error_text.lower()
    if "unique" not in lower:
        return False
    return "base_path" in lower or "name" in lower or "must be unique" in lower


class RepositoryManager:
    """
    Manages repository and distribution operations for Pulp.

    This class handles creating, retrieving, and managing repositories
    and their distributions.
    """

    def __init__(self, pulp_client: PulpClient, parent_package: str | None = None) -> None:
        """
        Initialize the repository manager.

        Args:
            pulp_client: PulpClient instance for API interactions
            parent_package: Optional parent package name for distribution paths
        """
        self.client = pulp_client
        self.namespace = pulp_client.namespace
        self.parent_package = parent_package
        # Cache for distribution base paths: (build_id, repo_type) -> base_path
        self._distribution_cache: dict[tuple[str, str], str] = {}

    def _validate_full_name(self, full_name: str, build_name: str, repo_type: str) -> None:
        """
        Validate that full_name is not empty or whitespace-only.

        This method is extracted to allow patching in tests for coverage.

        Args:
            full_name: The full repository name to validate
            build_name: The build name (for error messages)
            repo_type: The repository type (for error messages)

        Raises:
            ValueError: If full_name is empty or whitespace-only
        """
        if not full_name or not full_name.strip():
            raise ValueError(f"Invalid full_name constructed: build_name={build_name}, repo_type={repo_type}")

    def setup_repositories(
        self,
        build_id: str,
        signed_by: str | None = None,
        skip_artifacts_repo: bool = False,
        target_arch_repo: bool = False,
        skip_logs_repo: bool = False,
        skip_sbom_repo: bool = False,
    ) -> RepositoryRefs:
        """
        Setup all required repositories and return their identifiers.

        This method orchestrates the creation of all necessary repositories
        by delegating to the PulpClient API methods.

        Args:
            build_id: Build ID for naming repositories and distributions
            signed_by: If set, also create signed repos (rpms-signed, etc.) unless target_arch_repo
            skip_artifacts_repo: If True, do not create artifacts repo (e.g. when saving locally)
            target_arch_repo: If True, skip aggregate rpms/rpms-signed; per-arch RPM repos at upload time
            skip_logs_repo: If True, do not create logs repository
            skip_sbom_repo: If True, do not create SBOM repository

        Returns:
            RepositoryRefs NamedTuple containing all repository PRNs and hrefs
        """
        # Check for empty/None build ID before sanitization
        if not build_id or not isinstance(build_id, str) or not build_id.strip():
            raise ValueError(f"Invalid build ID: {build_id}")

        # Sanitize build ID for repository naming first
        sanitized_build_id = sanitize_build_id_for_repository(build_id)

        # Validate sanitized build ID
        if not validate_build_id(sanitized_build_id):
            raise ValueError(f"Invalid build ID: {build_id} (sanitized: {sanitized_build_id})")
        if sanitized_build_id != build_id:
            logging.debug("Sanitized build ID '%s' to '%s' for repository naming", build_id, sanitized_build_id)

        logging.debug("Setting up repositories for build: %s", sanitized_build_id)

        # Create repositories directly using the helper's own methods
        repositories = self._setup_repositories_impl(
            sanitized_build_id,
            signed_by=signed_by,
            skip_artifacts_repo=skip_artifacts_repo,
            target_arch_repo=target_arch_repo,
            skip_logs_repo=skip_logs_repo,
            skip_sbom_repo=skip_sbom_repo,
        )

        # Validate the setup (only base repos; signed repos are optional)
        required = [
            r
            for r in REPOSITORY_TYPES
            if not (skip_artifacts_repo and r == "artifacts")
            and not (target_arch_repo and r == "rpms")
            and not (skip_logs_repo and r == "logs")
            and not (skip_sbom_repo and r == "sbom")
        ]
        is_valid, errors = validate_repository_setup(repositories, required_types=required)
        if not is_valid:
            raise RuntimeError(f"Repository setup validation failed: {', '.join(errors)}")

        logging.debug("Repository setup completed successfully")

        # Convert dictionary to NamedTuple for type safety
        rpms_href = "" if target_arch_repo else repositories.get("rpms_href", "")
        rpms_prn = "" if target_arch_repo else repositories.get("rpms_prn", "")
        return RepositoryRefs(
            rpms_href=rpms_href,
            rpms_prn=rpms_prn,
            logs_href=repositories.get("logs_href", ""),
            logs_prn=repositories.get("logs_prn", ""),
            sbom_href=repositories.get("sbom_href", ""),
            sbom_prn=repositories.get("sbom_prn", ""),
            artifacts_href=repositories.get("artifacts_href", ""),
            artifacts_prn=repositories.get("artifacts_prn", ""),
            rpms_signed_href=repositories.get("rpms_signed_href", ""),
            rpms_signed_prn=repositories.get("rpms_signed_prn", ""),
            logs_signed_href=repositories.get("logs_signed_href", ""),
            logs_signed_prn=repositories.get("logs_signed_prn", ""),
            sbom_signed_href=repositories.get("sbom_signed_href", ""),
            sbom_signed_prn=repositories.get("sbom_signed_prn", ""),
            artifacts_signed_href=repositories.get("artifacts_signed_href", ""),
            artifacts_signed_prn=repositories.get("artifacts_signed_prn", ""),
        )

    def ensure_rpm_repository_for_arch(self, build_id: str, arch: str) -> str:
        """
        Create or get the RPM repository whose distribution uses the architecture as base_path.

        Used with ``target_arch_repo`` so RPM URLs are
        ``/api/pulp-content/{namespace}/{arch}/Packages/...`` instead of ``.../{build}/rpms/...``.
        """
        if arch not in SUPPORTED_ARCHITECTURES:
            raise ValueError(f"Unsupported architecture for RPM repository: {arch}")
        if not build_id or not isinstance(build_id, str) or not build_id.strip():
            raise ValueError(f"Invalid build ID: {build_id}")

        sanitized_build_id = sanitize_build_id_for_repository(build_id)
        if not validate_build_id(sanitized_build_id):
            raise ValueError(f"Invalid build ID: {build_id} (sanitized: {sanitized_build_id})")

        full_name = arch.strip()
        self._validate_full_name(full_name, full_name, "rpm")
        new_repository = RepositoryRequest(name=full_name, autopublish=True)
        new_distribution = DistributionRequest(name=full_name, base_path=full_name)
        if not new_distribution.base_path or not new_distribution.base_path.strip():
            raise ValueError(f"Invalid distribution base_path for arch repository {arch}")

        cache_type = f"rpm_arch:{arch}"
        _prn, repository_href = self._create_or_get_repository_impl(
            new_repository,
            new_distribution,
            "rpm",
            build_id=sanitized_build_id,
            distribution_cache_type=cache_type,
        )
        if not repository_href:
            raise RuntimeError(f"No repository href for architecture RPM repository {arch}")
        return repository_href

    def create_or_get_repository(
        self,
        build_id: str | None,
        repo_api_type: str,
        new_repository: RepositoryRequest | None = None,
        new_distribution: DistributionRequest | None = None,
    ) -> tuple[str, str | None]:
        """
        Create or get a repository and distribution of the specified type.

        This method orchestrates the creation/retrieval of repositories
        by delegating to the PulpClient API methods.

        Args:
            build_id: Build ID for naming repositories and distributions
            repo_api_type: Type of repository or API ('rpms', 'logs', 'sbom', 'artifacts', 'rpm','file')
            new_repository: RepositoryRequest model for the repository to create
            new_distribution: DistributionRequest model for the distribution to create

        Returns:
            Tuple of (repository_prn, repository_href) where href is None for file repos
        """
        # Validate repository type
        if repo_api_type not in REPOSITORY_TYPES + API_TYPES:
            raise ValueError(f"Invalid repository or API type: {repo_api_type}")

        if new_repository is not None and new_distribution is not None:
            logging.debug("Creating or getting defined repository: %s", new_repository.name)
            # Create or get repository directly using the helper's own methods
            repository_prn, repository_href = self._create_or_get_repository_impl(
                new_repository, new_distribution, repo_api_type
            )
            logging.debug("Repository operation completed: %s", new_repository.name)

        else:
            # Check for empty/None build ID before sanitization
            if not build_id or not isinstance(build_id, str) or not build_id.strip():
                raise ValueError(f"Invalid build ID: {build_id}")

            # Sanitize build ID for repository naming first
            sanitized_build_id = sanitize_build_id_for_repository(build_id)

            # Validate sanitized build ID
            if not validate_build_id(sanitized_build_id):
                raise ValueError(f"Invalid build ID: {build_id} (sanitized: {sanitized_build_id})")
            if sanitized_build_id != build_id:
                logging.debug("Sanitized build ID '%s' to '%s' for repository naming", build_id, sanitized_build_id)

            logging.debug("Creating or getting repository: %s/%s", sanitized_build_id, repo_api_type)

            build_name = strip_namespace_from_build_id(build_id)
            if not build_name or not build_name.strip():
                raise ValueError(f"Empty build_name after stripping namespace from build_id: {build_id}")
            full_name = f"{build_name}/{repo_api_type}"
            self._validate_full_name(full_name, build_name, repo_api_type)
            new_repo = RepositoryRequest(name=full_name, autopublish=True)
            new_distro = DistributionRequest(name=full_name, base_path=full_name)
            # Validate that base_path was set correctly
            if not new_distro.base_path or not new_distro.base_path.strip():
                raise ValueError(
                    f"DistributionRequest base_path is empty after creation: "
                    f"name={full_name}, base_path={new_distro.base_path}"
                )

            # Create or get repository directly using the helper's own methods
            repository_prn, repository_href = self._create_or_get_repository_impl(
                new_repo, new_distro, repo_api_type, build_id=build_id
            )

            logging.debug("Repository operation completed: %s/%s", sanitized_build_id, repo_api_type)

        return repository_prn, repository_href

    def get_repository_methods(self, repo_type: str) -> RepositoryApiOps:
        """
        Get bound repository/distribution operations for the repository type.

        Args:
            repo_type: Type of repository ('rpm' or 'file')

        Returns:
            :class:`RepositoryApiOps` for this client and API type
        """
        return RepositoryApiOps(self.client, repo_type)

    def _parse_repository_response(self, response: httpx.Response, repo_type: str, operation: str) -> dict[str, Any]:
        """Parse repository response JSON with error handling."""
        try:
            return response.json()
        except ValueError as e:
            logging.error("Failed to parse JSON response for %s repository %s: %s", repo_type, operation, e)
            logging.error("Response content: %s", response.text[:500])
            logging.error("Traceback: %s", traceback.format_exc())
            raise ValueError(f"Invalid JSON response from Pulp API: {e}") from e

    def _get_existing_repository(
        self, methods: RepositoryApiOps, full_name: str, repo_type: str
    ) -> tuple[str, str | None] | None:
        """Check if repository exists and return its details.

        Returns None if repository doesn't exist (404), allowing the caller to create it.
        """
        repository_response = methods.get(full_name)

        # Handle 404 gracefully - repository doesn't exist, return None to allow creation
        if repository_response.status_code == 404:
            logging.debug("Repository %s not found (404), will create it", full_name)
            return None

        # For other errors, check_response will raise an exception
        self.client.check_response(repository_response, f"check {repo_type} repository")

        response_data = self._parse_repository_response(repository_response, repo_type, "check")

        results = response_data.get("results", [])
        if results:
            logging.warning("Found existing repository %s: %s", _resource_log_label(full_name), full_name)
            result = results[0]
            return result["prn"], result.get("pulp_href")

        return None

    def _create_new_repository(
        self, methods: RepositoryApiOps, new_repository: RepositoryRequest, repo_type: str
    ) -> tuple[str, str | None]:
        """Create a new repository and return its details."""
        logging.warning(
            "Creating new repository %s: %s",
            _resource_log_label(new_repository.name),
            new_repository.name,
        )
        try:
            repository_response = methods.create(new_repository)
            self.client.check_response(repository_response, f"create {repo_type} repository")
        except PulpToolHTTPError as exc:
            if exc.response is not None and exc.response.status_code == 400:
                if _is_distribution_uniqueness_error(exc.response.text):
                    existing = self._get_existing_repository(methods, new_repository.name, repo_type)
                    if existing:
                        logging.warning(
                            "Repository %s already exists (HTTP 400); using existing",
                            new_repository.name,
                        )
                        return existing
            raise

        # The create response contains the repository details directly
        response_data = self._parse_repository_response(repository_response, repo_type, "create")

        # Create returns the object directly, not wrapped in results
        if "prn" in response_data:
            # Direct repository object
            return response_data["prn"], response_data.get("pulp_href")
        elif "results" in response_data:
            # Wrapped in results (fallback)
            results = response_data["results"]
            if not results:
                raise ValueError(f"No {repo_type} repository found after creation: {new_repository.name}")
            result = results[0]
            return result["prn"], result.get("pulp_href")
        else:
            raise ValueError(f"Unexpected response format for {repo_type} repository creation: {new_repository.name}")

    def _get_existing_distribution(
        self, methods: RepositoryApiOps, full_name: str, repo_type: str
    ) -> ExistingDistributionInfo | None:
        """Return base_path and repository for an existing distribution, or None if not found."""
        try:
            distro_response = methods.get_distro(full_name)
            if distro_response.status_code == 404:
                return None
            self.client.check_response(distro_response, f"get {repo_type} distribution")
            response_data = self._parse_repository_response(distro_response, repo_type, "distribution lookup")
            results = response_data.get("results", [])
            if not results:
                return None
            row = results[0]
            base_path = row.get("base_path")
            if not base_path:
                return None
            return ExistingDistributionInfo(base_path=str(base_path), repository=row.get("repository"))
        except (httpx.HTTPError, ValueError, KeyError) as e:
            logging.warning("Could not look up existing distribution %s: %s", full_name, e)
            return None

    def _get_existing_distribution_base_path(
        self, methods: RepositoryApiOps, full_name: str, repo_type: str
    ) -> str | None:
        """Return the base_path of an existing distribution, or None if not found."""
        existing = self._get_existing_distribution(methods, full_name, repo_type)
        return existing.base_path if existing else None

    def _resolve_existing_distribution_base_path(
        self,
        methods: RepositoryApiOps,
        distribution_name: str,
        repo_type: str,
        expected_repository: str | None,
    ) -> str:
        """Load an existing distribution and verify it belongs to the expected repository."""
        existing = self._get_existing_distribution(methods, distribution_name, repo_type)
        if existing is None or not existing.base_path:
            raise ValueError(
                f"Distribution {distribution_name!r} reported as existing but could not be loaded from Pulp"
            )
        if not expected_repository:
            raise ValueError(
                f"Cannot verify existing distribution {distribution_name!r}: expected repository is unknown"
            )
        if not existing.repository:
            raise ValueError(
                f"Existing distribution {distribution_name!r} has no repository; expected {expected_repository!r}"
            )
        if existing.repository != expected_repository:
            if not _repository_identifiers_match(existing.repository, expected_repository):
                raise ValueError(
                    f"Existing distribution {distribution_name!r} is attached to repository "
                    f"{existing.repository!r}, expected {expected_repository!r}"
                )
        return existing.base_path

    def _cache_distribution_base_path(
        self,
        build_id: str | None,
        repo_type: str,
        distribution_name: str,
        methods: RepositoryApiOps,
        *,
        distribution_cache_type: str | None = None,
        fallback_base_path: str | None = None,
        expected_repository: str | None = None,
    ) -> None:
        """Store distribution base_path in the in-memory cache when build_id is known."""
        if not build_id:
            return
        cache_key = (build_id, distribution_cache_type or repo_type)
        resolved_base_path: str | None
        if expected_repository:
            resolved_base_path = self._resolve_existing_distribution_base_path(
                methods, distribution_name, repo_type, expected_repository
            )
        else:
            resolved_base_path = self._get_existing_distribution_base_path(methods, distribution_name, repo_type)
        self._distribution_cache[cache_key] = resolved_base_path or fallback_base_path or distribution_name

    def _wait_for_distribution_task(
        self,
        methods: RepositoryApiOps,
        task_id: str,
        repo_type: str,
        build_id: str,
        *,
        distribution_name: str | None = None,
        expected_repository: str | None = None,
    ) -> str | None:
        """
        Wait for distribution creation task to complete and return the base_path.

        Returns:
            The base_path of the created distribution, or None if not found
        """
        task_response = methods.wait_for_finished_task(task_id)

        # task_response is now a TaskResponse model
        if not task_response.is_successful:
            error_msg = (
                task_response.error.get("description", "Unknown error") if task_response.error else "Unknown error"
            )
            lookup_name = distribution_name or build_id
            if lookup_name and _is_distribution_uniqueness_error(str(error_msg)):
                existing_base_path = self._resolve_existing_distribution_base_path(
                    methods, lookup_name, repo_type, expected_repository
                )
                logging.warning(
                    "Distribution creation task failed with uniqueness conflict for %s (%s); "
                    "using existing distribution base_path=%s",
                    repo_type,
                    lookup_name,
                    existing_base_path,
                )
                return existing_base_path
            logging.error("Task failed for %s distribution (build_id=%s): %s", repo_type, build_id, error_msg)
            raise ValueError(f"Distribution creation task failed: {error_msg}")

        # Extract the distribution base_path from created resources
        base_path: str | None = None
        if task_response.created_resources:
            logging.debug("Distribution creation completed. Created resources:")
            for resource_href in task_response.created_resources:
                logging.debug("  - %s", resource_href)
                # Fetch the distribution details to get the base_path
                try:
                    # resource_href from created_resources is a path; build full URL
                    base_url = str(self.client.config["base_url"]).rstrip("/")
                    full_url = f"{base_url}{resource_href}" if resource_href.startswith("/") else resource_href
                    distro_response = self.client.session.get(
                        full_url, timeout=self.client.timeout, **self.client.request_params
                    )
                    self.client.check_response(distro_response, "get distribution from task resource")
                    distro_data = distro_response.json()
                    base_path = distro_data.get("base_path")
                    if base_path:
                        logging.info(
                            "Retrieved base_path from distribution task: %s (build_id=%s, repo_type=%s)",
                            base_path,
                            build_id,
                            repo_type,
                        )
                        break
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    logging.warning("Could not fetch distribution details from %s: %s", resource_href, e)
        else:
            logging.debug("Distribution creation completed for %s %s", repo_type, build_id)

        return base_path

    async def _setup_repositories_impl_async(
        self,
        build_id: str,
        signed_by: str | None = None,
        skip_artifacts_repo: bool = False,
        target_arch_repo: bool = False,
        skip_logs_repo: bool = False,
        skip_sbom_repo: bool = False,
    ) -> dict[str, str]:
        """
        Async version: Setup all required repositories using asyncio.gather for concurrency.

        This method creates or retrieves all necessary repositories (rpms, logs, sbom, artifacts)
        and their distributions concurrently using asyncio.gather for better performance.
        When signed_by is set, also creates rpms-signed (unless target_arch_repo). When
        skip_artifacts_repo is True, skips the artifacts repository (e.g. when saving locally).

        Args:
            build_id: Base name for the repositories
            signed_by: If set, also create signed repos (ignored for RPM when target_arch_repo)
            skip_artifacts_repo: If True, do not create artifacts repo
            target_arch_repo: If True, skip aggregate ``rpms`` and ``rpms-signed`` repositories
            skip_logs_repo: If True, skip ``logs`` repository
            skip_sbom_repo: If True, skip ``sbom`` repository

        Returns:
            Dictionary mapping repository types to their PRNs and hrefs
        """
        logging.debug("Setting up repositories async for: %s", build_id)

        repo_types = [r for r in REPOSITORY_TYPES if not (skip_artifacts_repo and r == "artifacts")]
        if skip_logs_repo:
            repo_types = [r for r in repo_types if r != "logs"]
        if skip_sbom_repo:
            repo_types = [r for r in repo_types if r != "sbom"]
        if target_arch_repo:
            repo_types = [r for r in repo_types if r not in ("rpms", "rpms-signed")]
        elif signed_by:
            repo_types.extend(SIGNED_REPOSITORY_TYPES)

        # Use asyncio.gather to run all repository setups concurrently
        # Each operation runs in the event loop without blocking
        async def create_repo(repo_type: str) -> tuple[str, tuple[str, str | None]]:
            """Helper to create repository and return type with result."""
            loop = asyncio.get_event_loop()
            build_name = strip_namespace_from_build_id(build_id)
            if not build_name or not build_name.strip():
                raise ValueError(f"Empty build_name after stripping namespace from build_id: {build_id}")
            full_name = f"{build_name}/{repo_type}"
            base_repo_type = repo_type.split("-")[0] if "-" in repo_type else repo_type
            self._validate_full_name(full_name, build_name, base_repo_type)
            new_repository = RepositoryRequest(name=full_name, autopublish=True)
            new_distribution = DistributionRequest(name=full_name, base_path=full_name)
            # Validate that base_path was set correctly
            if not new_distribution.base_path or not new_distribution.base_path.strip():
                raise ValueError(
                    f"DistributionRequest base_path is empty after creation: "
                    f"name={full_name}, base_path={new_distribution.base_path}"
                )
            # Map repo_type to API type: rpms-signed -> rpms, logs-signed -> logs, etc.
            api_repo_type = base_repo_type

            # Run sync method in executor to avoid blocking
            def _run_create(r=new_repository, d=new_distribution, t=api_repo_type):
                return self._create_or_get_repository_impl(r, d, t, build_id)

            prn, href = await loop.run_in_executor(None, _run_create)
            return repo_type, (prn, href)

        try:
            # Gather all repository creation tasks concurrently
            results = await asyncio.gather(*[create_repo(rt) for rt in repo_types])

            # Build result dictionary; map rpms-signed -> rpms_signed for key names
            repositories = {}
            for repo_type, (prn, href) in results:
                key_suffix = repo_type.replace("-", "_")
                repositories[f"{key_suffix}_prn"] = prn
                if href:  # RPM repositories have href, file repositories don't
                    repositories[f"{key_suffix}_href"] = href
                logging.debug("Completed setup for %s repository", repo_type)

            return repositories

        except httpx.HTTPError as e:
            # HTTP errors are already formatted nicely, just re-raise
            error_msg = str(e)
            if "403" in error_msg:
                logging.error(
                    "Authentication failed: You don't have permission to access this Pulp instance. "
                    "Please check your credentials in the Pulp config file."
                )
            elif "401" in error_msg:
                logging.error(
                    "Authentication failed: Invalid credentials. "
                    "Please check your OAuth2 settings in the Pulp config file."
                )
            logging.debug("Failed to setup repositories: %s", error_msg)
            logging.debug("Traceback: %s", traceback.format_exc())
            raise
        except Exception as e:
            logging.error("Failed to setup repositories: %s", e)
            logging.debug("Traceback: %s", traceback.format_exc())
            raise

    def _create_or_get_repository_impl(
        self,
        new_repository: RepositoryRequest,
        new_distribution: DistributionRequest,
        repo_type: str,
        build_id: str | None = None,
        *,
        distribution_cache_type: str | None = None,
    ) -> tuple[str, str | None]:
        """
        Create or get a repository and distribution of the specified type.

        Args:
            new_repository: RepositoryRequest model for the repository to create
            new_distribution: DistributionRequest model for the distribution to create
            repo_type: Type of repository ('rpms', 'logs', 'sbom', 'artifacts', 'rpm', 'file')
            build_id: Base name for the repository (may include namespace prefix)

        Returns:
            Tuple of (repository_prn, repository_href) where href is None for file repos
        """
        if repo_type not in API_TYPES:
            api_type = "rpm" if repo_type == "rpms" else "file"
            methods = self.get_repository_methods(api_type)
        else:
            methods = self.get_repository_methods(repo_type)

        # Check if repository already exists
        existing_repo = self._get_existing_repository(methods, new_repository.name, repo_type)
        if existing_repo:
            repository_prn, repository_href = existing_repo
            is_new_repository = False
        else:
            repository_prn, repository_href = self._create_new_repository(methods, new_repository, repo_type)
            is_new_repository = True

        # Create distribution (always create new distribution for new repositories)
        new_distribution.repository = repository_prn
        # Validate base_path is still valid after setting repository
        if not new_distribution.base_path or not new_distribution.base_path.strip():
            raise ValueError(
                f"DistributionRequest base_path is empty before creating {repo_type} distribution: "
                f"name={new_distribution.name}, repository={repository_prn}"
            )
        task_id = self._create_distribution_task(
            methods,
            new_distribution,
            repo_type,
            is_new_repository,
            build_id=build_id,
            distribution_cache_type=distribution_cache_type,
        )

        # If distribution was created, wait for it to complete and cache the base_path
        cache_key_type = distribution_cache_type or repo_type
        if task_id:
            base_path = self._wait_for_distribution_task(
                methods,
                task_id,
                repo_type,
                build_id or new_repository.name,
                distribution_name=new_distribution.name,
                expected_repository=repository_prn,
            )
            if build_id and base_path:
                # Cache the base_path so we don't need to query it later
                self._distribution_cache[(build_id, cache_key_type)] = base_path
                logging.debug("Cached distribution base_path for %s/%s: %s", build_id, cache_key_type, base_path)

        return repository_prn, repository_href

    def _check_existing_distribution(self, methods: RepositoryApiOps, full_name: str, repo_type: str) -> bool:
        """Check if distribution already exists by name.

        Returns False if distribution doesn't exist (404), allowing the caller to create it.
        """
        try:
            logging.debug("Checking for existing %s distribution: %s", repo_type, full_name)
            distro_response = methods.get_distro(full_name)
            logging.debug("Distribution check response status: %s", distro_response.status_code)

            # Handle 404 gracefully - distribution doesn't exist, return False to allow creation
            if distro_response.status_code == 404:
                logging.debug("Distribution %s not found (404), will create it", full_name)
                return False

            # For other errors, check_response will raise an exception
            self.client.check_response(distro_response, f"check {repo_type} distribution")

            response_data = self._parse_repository_response(distro_response, repo_type, "distribution check")
            logging.debug("Distribution check response data: %s", response_data)

            if response_data.get("results"):
                logging.warning("Found existing distribution %s: %s", _resource_log_label(full_name), full_name)
                return True

            logging.debug("No existing %s distribution found for: %s", repo_type, full_name)
            return False
        except AttributeError:
            logging.debug("Distribution check method not available for %s, will create", repo_type)
            return False  # Create distribution if check method doesn't exist
        except (httpx.HTTPError, ValueError, KeyError) as e:
            logging.warning("Error checking for existing distribution: %s", e)
            logging.error("Traceback: %s", traceback.format_exc())
            return False  # Continue with creation if check fails

    def _new_distribution_task(
        self, methods: RepositoryApiOps, new_distribution: DistributionRequest, repo_type: str
    ) -> str:
        """Create a distribution for a repository and return the task ID.

         Args:
            methods: Dictionary of repository methods
            new_distribution: DistributionRequest model for the distribution to create
            repo_type: Type of repository ('rpms', 'logs', 'sbom', 'artifacts', 'rpm', 'file')

        Returns:
            Task ID for the new distribution, or empty string if it already exists
        """
        # Logging is handled by the caller (_create_distribution_task) to avoid duplicate messages
        distro_response = methods.distro(new_distribution)
        try:
            self.client.check_response(distro_response, f"create {repo_type} distribution")
        except PulpToolHTTPError as exc:
            if exc.response is not None and exc.response.status_code == 400:
                if _is_distribution_uniqueness_error(exc.response.text):
                    self._resolve_existing_distribution_base_path(
                        methods,
                        new_distribution.name,
                        repo_type,
                        new_distribution.repository,
                    )
                    logging.warning(
                        "Distribution %s already exists (HTTP 400); skipping create",
                        new_distribution.name,
                    )
                    return ""
            raise

        response_data = self._parse_repository_response(distro_response, repo_type, "distribution creation")

        return response_data["task"]

    def _create_distribution_task(
        self,
        methods: RepositoryApiOps,
        new_distribution: DistributionRequest,
        repo_type: str,
        is_new_repository: bool = False,
        build_id: str | None = None,
        *,
        distribution_cache_type: str | None = None,
    ) -> str:
        """Create a distribution for a repository and return the task ID.

        Args:
            methods: Dictionary of repository methods
            new_distribution: DistributionRequest model for the distribution to create
            repo_type: Type of repository ('rpms', 'logs', 'sbom', 'artifacts', 'rpm', 'file')
            is_new_repository: Retained for call-site compatibility; existence is always checked
            build_id: Base name for the repository (may include namespace prefix)

        Returns:
            Task ID if distribution was created, empty string if it already exists
        """
        # Always check for an existing distribution (covers re-runs and 504 retries where
        # the first POST succeeded server-side but the client retried).
        if self._check_existing_distribution(methods, new_distribution.name, repo_type):
            self._cache_distribution_base_path(
                build_id,
                repo_type,
                new_distribution.name,
                methods,
                distribution_cache_type=distribution_cache_type,
                fallback_base_path=new_distribution.base_path,
                expected_repository=new_distribution.repository,
            )
            return ""

        # Validate base_path before creating distribution
        base_path_value = getattr(new_distribution, "base_path", None)
        if not base_path_value or not str(base_path_value).strip():
            error_msg = (
                f"Invalid base_path for {repo_type} distribution: "
                f"name={new_distribution.name}, base_path={base_path_value}, "
                f"type={type(base_path_value)}"
            )
            logging.error(error_msg)
            raise ValueError(error_msg)
        # Distribution name and base_path are kept identical to the repository name (see _create_or_get_repository_impl)
        logging.warning(
            "Creating new distribution %s — name=%r base_path=%r (same as repository)",
            _resource_log_label(str(new_distribution.name)),
            new_distribution.name,
            base_path_value,
        )
        distro_task = self._new_distribution_task(methods, new_distribution, repo_type)
        if not distro_task:
            self._cache_distribution_base_path(
                build_id,
                repo_type,
                new_distribution.name,
                methods,
                distribution_cache_type=distribution_cache_type,
                fallback_base_path=new_distribution.base_path,
                expected_repository=new_distribution.repository,
            )
            return ""

        # Cache the base_path for future URL construction
        if build_id:
            cache_key = (build_id, distribution_cache_type or repo_type)
            self._distribution_cache[cache_key] = new_distribution.base_path

        return distro_task

    def _setup_repositories_impl(
        self,
        build_id: str,
        signed_by: str | None = None,
        skip_artifacts_repo: bool = False,
        target_arch_repo: bool = False,
        skip_logs_repo: bool = False,
        skip_sbom_repo: bool = False,
    ) -> dict[str, str]:
        """
        Setup all required repositories and return their identifiers.

        This method creates or retrieves all necessary repositories (rpms, logs, sbom, artifacts)
        and their distributions concurrently using async/await for better performance than threads.
        When signed_by is set, also creates signed repos (unless target_arch_repo).

        Args:
            build_id: Base name for the repositories
            signed_by: If set, also create signed repos
            target_arch_repo: If True, skip aggregate RPM repositories

        Returns:
            Dictionary mapping repository types to their PRNs and hrefs:
                - {repo_type}_prn: Repository PRN for each type
                - {repo_type}_href: Repository href for RPM repositories (None for file repos)
        """
        # Run the async version and return results
        return asyncio.run(
            self._setup_repositories_impl_async(
                build_id,
                signed_by=signed_by,
                skip_artifacts_repo=skip_artifacts_repo,
                target_arch_repo=target_arch_repo,
                skip_logs_repo=skip_logs_repo,
                skip_sbom_repo=skip_sbom_repo,
            )
        )

    def get_distribution_cache(self) -> dict[tuple[str, str], str]:
        """Get the distribution cache for sharing with DistributionManager."""
        return self._distribution_cache


__all__ = ["RepositoryApiOps", "RepositoryManager"]
