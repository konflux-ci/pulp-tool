"""
PulpHelper class for managing Pulp repositories and distributions.

This module provides the PulpHelper class which acts as a facade,
delegating to specialized manager classes for repository, distribution,
and upload operations.
"""

from typing import TYPE_CHECKING, Optional

from pulp_tool.models.pulp_api import DistributionRequest, RepositoryRequest

from ..models.context import UploadContext, UploadFilesContext, UploadRpmContext
from ..models.repository import RepositoryRefs
from ..models.results import PulpResultsModel, RpmUploadResult

if TYPE_CHECKING:
    from ..api.pulp_client import PulpClient

from .distribution_manager import DistributionManager
from .repository_manager import RepositoryManager
from .upload_orchestrator import UploadOrchestrator
from .validation.build_id import sanitize_build_id_for_repository, strip_namespace_from_build_id
from .validation.side_tag import side_tag_distribution_base_path


class PulpHelper:
    """
    Helper class for Pulp operations including repositories, distributions, and other functionality.

    This class provides high-level methods for managing Pulp operations,
    delegating to specialized manager classes.
    """

    def __init__(self, pulp_client: "PulpClient", parent_package: str | None = None) -> None:
        """
        Initialize the helper with a PulpClient instance.

        Args:
            pulp_client: PulpClient instance for API interactions
            parent_package: Optional parent package name for distribution paths
        """
        self.client = pulp_client
        self.namespace = pulp_client.namespace
        self.parent_package = parent_package

        # Initialize specialized managers
        self._repository_manager = RepositoryManager(pulp_client, parent_package)
        # Ensure namespace is a string (default to empty string if None)
        namespace_str = self.namespace if isinstance(self.namespace, str) else ""
        self._distribution_manager = DistributionManager(
            pulp_client, namespace_str, self._repository_manager.get_distribution_cache()
        )
        self._upload_orchestrator = UploadOrchestrator()

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
        by delegating to the RepositoryManager.

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
        return self._repository_manager.setup_repositories(
            build_id,
            signed_by=signed_by,
            skip_artifacts_repo=skip_artifacts_repo,
            target_arch_repo=target_arch_repo,
            skip_logs_repo=skip_logs_repo,
            skip_sbom_repo=skip_sbom_repo,
        )

    def distribution_url_for_base_path(self, base_path: str) -> str:
        """Pulp-content base URL for a distribution ``base_path`` (e.g. architecture name)."""
        return self._distribution_manager.distribution_url_for_base_path(base_path)

    def get_distribution_urls(
        self,
        build_id: str,
        *,
        target_arch_repo: bool = False,
        include_signed_rpm_distro: bool = False,
        skip_logs_repo: bool = False,
        skip_sbom_repo: bool = False,
        skip_artifacts_repo: bool = False,
    ) -> dict[str, str]:
        """
        Get distribution URLs for all repository types.

        This method orchestrates the retrieval of distribution URLs
        by delegating to the DistributionManager.

        Args:
            build_id: Build ID for naming repositories and distributions
            target_arch_repo: If True, omit aggregate ``rpms`` distribution URL
            include_signed_rpm_distro: If True, include ``rpms_signed`` URL
            skip_logs_repo: If True, omit ``logs`` URL
            skip_sbom_repo: If True, omit ``sbom`` URL
            skip_artifacts_repo: If True, omit ``artifacts`` URL

        Returns:
            Dictionary mapping repo_type to distribution URL
        """
        return self._distribution_manager.get_distribution_urls(
            build_id,
            target_arch_repo=target_arch_repo,
            include_signed_rpm_distro=include_signed_rpm_distro,
            skip_logs_repo=skip_logs_repo,
            skip_sbom_repo=skip_sbom_repo,
            skip_artifacts_repo=skip_artifacts_repo,
        )

    def get_distribution_urls_for_upload_context(self, build_id: str, context: UploadContext) -> dict[str, str]:
        """Distribution URL map for results JSON (per-arch vs signed aggregate RPM base)."""
        target_arch = bool(getattr(context, "target_arch_repo", False))
        signed_by = getattr(context, "signed_by", None)
        skip_logs = bool(getattr(context, "skip_logs_repo", False))
        skip_sbom = bool(getattr(context, "skip_sbom_repo", False))
        ar = (getattr(context, "artifact_results", None) or "").strip()
        # Local folder mode: --artifact-results /path/to/dir (no comma); no artifacts repo or distribution
        skip_artifacts = bool(ar and "," not in ar)
        if target_arch:
            return self.get_distribution_urls(
                build_id,
                target_arch_repo=True,
                skip_logs_repo=skip_logs,
                skip_sbom_repo=skip_sbom,
                skip_artifacts_repo=skip_artifacts,
            )
        if signed_by and str(signed_by).strip():
            return self.get_distribution_urls(
                build_id,
                include_signed_rpm_distro=True,
                skip_logs_repo=skip_logs,
                skip_sbom_repo=skip_sbom,
                skip_artifacts_repo=skip_artifacts,
            )
        return self.get_distribution_urls(
            build_id,
            skip_logs_repo=skip_logs,
            skip_sbom_repo=skip_sbom,
            skip_artifacts_repo=skip_artifacts,
        )

    def ensure_rpm_repository_for_arch(self, build_id: str, arch: str) -> str:
        """Create or get RPM repository for ``target_arch_repo`` mode (base_path = arch)."""
        return self._repository_manager.ensure_rpm_repository_for_arch(build_id, arch)

    def ensure_side_tag_rpm_repository(self, build_id: str, side_tag: str) -> tuple[str, str]:
        """
        Create or get an extra RPM repository and distribution for side-tag promotions.

        Returns:
            Tuple of (repository_href, distribution_base_url)
        """
        sanitized_build = sanitize_build_id_for_repository(build_id)
        build_name = strip_namespace_from_build_id(sanitized_build)
        tag_segment = side_tag_distribution_base_path(side_tag)
        base_path = f"{build_name}/{tag_segment}"
        full_name = base_path
        new_repo = RepositoryRequest(name=full_name, autopublish=True)
        new_distro = DistributionRequest(name=full_name, base_path=base_path)
        _prn, repository_href = self.create_or_get_repository(
            sanitized_build,
            "rpms",
            new_repository=new_repo,
            new_distribution=new_distro,
        )
        if not repository_href:
            raise RuntimeError(f"No repository href for side-tag RPM repository {full_name}")
        distribution_url = self.distribution_url_for_base_path(base_path)
        return repository_href, distribution_url

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
        by delegating to the RepositoryManager.

        Args:
            build_id: Build ID for naming repositories and distributions
            repo_api_type: Type of repository or API ('rpms', 'logs', 'sbom', 'artifacts', 'rpm','file')
            new_repository: RepositoryRequest model for the repository to create
            new_distribution: DistributionRequest model for the distribution to create

        Returns:
            Tuple of (repository_prn, repository_href) where href is None for file repos
        """

        return self._repository_manager.create_or_get_repository(
            build_id, repo_api_type, new_repository, new_distribution
        )

    def process_architecture_uploads(
        self,
        client: "PulpClient",
        args: UploadRpmContext,
        repositories: RepositoryRefs,
        *,
        date_str: str,
        rpm_href: str,
        results_model: PulpResultsModel,
    ) -> dict[str, RpmUploadResult]:
        """
        Process uploads for all supported architectures.

        Delegates to UploadOrchestrator.

        Args:
            client: PulpClient instance for API interactions
            args: Command line arguments
            repositories: Dictionary of repository identifiers
            date_str: Build date string
            rpm_href: RPM repository href for adding content
            results_model: PulpResultsModel to update with upload counts

        Returns:
            Dictionary mapping architecture names to RpmUploadResult
        """
        distribution_urls = self.get_distribution_urls_for_upload_context(args.build_id, args)
        return self._upload_orchestrator.process_architecture_uploads(
            client,
            args,
            repositories,
            date_str=date_str,
            rpm_href=rpm_href,
            results_model=results_model,
            distribution_urls=distribution_urls,
            pulp_helper=self,
            target_arch_repo=args.target_arch_repo,
        )

    def process_uploads(
        self,
        client: "PulpClient",
        args: UploadRpmContext,
        repositories: RepositoryRefs,
        *,
        pulp_helper: Optional["PulpHelper"] = None,
    ) -> str | None:
        """
        Process all upload operations.

        Delegates to UploadOrchestrator.

        Args:
            client: PulpClient instance for API interactions
            args: UploadRpmContext with command line arguments (including date_str)
            repositories: RepositoryRefs containing all repository identifiers
            pulp_helper: Helper instance for per-arch RPM repos when ``target_arch_repo`` is set

        Returns:
            URL of the uploaded results JSON, or None if upload failed
        """
        return self._upload_orchestrator.process_uploads(client, args, repositories, pulp_helper=pulp_helper or self)

    def process_file_uploads(
        self, client: "PulpClient", context: UploadFilesContext, repositories: RepositoryRefs
    ) -> str | None:
        """
        Process upload of individual files to Pulp repositories.

        Delegates to UploadOrchestrator.

        Args:
            client: PulpClient instance for API interactions
            context: UploadFilesContext with file paths and metadata
            repositories: RepositoryRefs containing all repository identifiers

        Returns:
            URL of the uploaded results JSON, or None if upload failed
        """
        return self._upload_orchestrator.process_file_uploads(client, context, repositories)


__all__ = ["PulpHelper"]
