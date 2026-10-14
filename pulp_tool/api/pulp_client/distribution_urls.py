"""RPM distribution URL helpers (shared by :class:`PulpClientContentQueryMixin`)."""

from __future__ import annotations

from ...models.rpm_repo_layout import RpmRepoLayout
from ...utils.artifact_detection import rpm_packages_letter_and_basename
from ...utils.constants import SUPPORTED_ARCHITECTURES
from ...utils.validation import sanitize_build_id_for_repository, validate_build_id


def rpm_distribution_base_url_from_labels(
    *,
    base_url: str,
    namespace: str,
    labels: dict[str, str],
    target_arch_repo_build_scoped: bool = False,
) -> str:
    """Build RPM distribution base URL when using per-arch repository layout."""
    base_url_str = base_url.rstrip("/")
    pulp_content = f"{base_url_str}/api/pulp-content/"
    ns = namespace if isinstance(namespace, str) else ""
    arch = (labels.get("arch") or "").strip() or "noarch"
    arch_seg = sanitize_build_id_for_repository(arch)
    if not validate_build_id(arch_seg):
        arch_seg = "noarch"
    layout = RpmRepoLayout.from_target_arch_flags(True, target_arch_repo_build_scoped)
    if layout.target_arch_repo_build_scoped:
        build_id = (labels.get("build_id") or "").strip()
        if build_id:
            path_seg = layout.repository_name(build_id, arch_seg)
            return f"{pulp_content}{ns}/{path_seg}/"
    return f"{pulp_content}{ns}/{arch_seg}/"


def build_rpm_packages_url_for_arch(
    *,
    base_url: str,
    namespace: str,
    arch: str,
    relative_path: str,
    labels: dict[str, str] | None = None,
    target_arch_repo_build_scoped: bool = False,
) -> str:
    """Build RPM content URL under per-arch distribution (namespace/arch/Packages/...)."""
    base_url_str = base_url.rstrip("/")
    pulp_content_base_url = f"{base_url_str}/api/pulp-content"
    ns = namespace if isinstance(namespace, str) else ""
    path_seg = arch
    layout = RpmRepoLayout.from_target_arch_flags(True, target_arch_repo_build_scoped)
    if layout.target_arch_repo_build_scoped and labels:
        build_id = (labels.get("build_id") or "").strip()
        if build_id:
            path_seg = layout.repository_name(build_id, arch)
    base = f"{pulp_content_base_url}/{ns}/{path_seg}/"
    filename, first_letter = rpm_packages_letter_and_basename(relative_path)
    if filename:
        return f"{base}Packages/{first_letter}/{filename}"
    return relative_path


def build_rpm_distribution_url(
    *,
    base_url: str,
    namespace: str,
    relative_path: str,
    distribution_urls: dict[str, str],
    labels: dict[str, str] | None = None,
    target_arch_repo: bool = False,
    target_arch_repo_build_scoped: bool = False,
) -> str:
    """Build distribution URL for RPM artifacts (Packages/<letter>/<basename>)."""
    labels = labels or {}
    if target_arch_repo:
        arch = (labels.get("arch") or "").strip()
        if arch and arch in SUPPORTED_ARCHITECTURES:
            return build_rpm_packages_url_for_arch(
                base_url=base_url,
                namespace=namespace,
                arch=arch,
                relative_path=relative_path,
                labels=labels,
                target_arch_repo_build_scoped=target_arch_repo_build_scoped,
            )
        rpms_url = rpm_distribution_base_url_from_labels(
            base_url=base_url,
            namespace=namespace,
            labels=labels,
            target_arch_repo_build_scoped=target_arch_repo_build_scoped,
        )
        filename, first_letter = rpm_packages_letter_and_basename(relative_path)
        if filename:
            return f"{rpms_url}Packages/{first_letter}/{filename}"
        return relative_path
    if labels.get("signed_by") and distribution_urls.get("rpms_signed"):
        rpms_url = distribution_urls["rpms_signed"]
        if rpms_url:
            filename, first_letter = rpm_packages_letter_and_basename(relative_path)
            if filename:
                return f"{rpms_url}Packages/{first_letter}/{filename}"
    rpms_url = distribution_urls.get("rpms", "")
    if rpms_url:
        filename, first_letter = rpm_packages_letter_and_basename(relative_path)
        if filename:
            return f"{rpms_url}Packages/{first_letter}/{filename}"
    return relative_path
