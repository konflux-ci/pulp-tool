"""Run-scoped naming helpers for concurrent e2e execution against a shared Pulp instance."""

from __future__ import annotations

import os
import re
from typing import Final

from large_upload import LARGE_RPM_FILENAME


def _e2e_strip_namespace_from_build_id(build_id: str) -> str:
    """Match :func:`pulp_tool.utils.validation.strip_namespace_from_build_id` (no pulp-tool import for cleanup image)."""
    if not build_id:
        return ""
    if "/" in build_id:
        return build_id.split("/", 1)[1]
    return build_id


def _e2e_sanitize_build_id_for_repository(build_id: str) -> str:
    """Match :func:`pulp_tool.utils.validation.sanitize_build_id_for_repository` for transfer path segments."""
    if not build_id or not isinstance(build_id, str):
        return "default-build"
    invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
    sanitized = build_id
    for char in invalid_chars:
        sanitized = sanitized.replace(char, "-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    sanitized = sanitized.strip("-").lower()
    return sanitized if sanitized else "default-build"


def e2e_transfer_destination_repo_prefix(*, source_domain: str, build_id: str) -> str:
    """
    Base path prefix for repos ``transfer`` creates on the destination (matches pulp-tool).

    ``konflux-<source-domain>/<source-repo>`` with ``<source-repo>`` = namespace-stripped ``build_id``.
    """
    source_repo = _e2e_strip_namespace_from_build_id(build_id)
    source_repo_seg = _e2e_sanitize_build_id_for_repository(source_repo)
    raw_domain = (source_domain or "").strip() or "unknown"
    if not raw_domain.lower().startswith("konflux-"):
        raw_domain = f"konflux-{raw_domain}"
    domain_seg = _e2e_sanitize_build_id_for_repository(raw_domain)
    return f"{domain_seg}/{source_repo_seg}"

# Build IDs created by the e2e upload/upload-files tests (without run suffix).
BUILD_ID_UPLOAD_MINIMAL: Final = "test-build-123"
BUILD_ID_UPLOAD_FULL: Final = "test-build-456"
BUILD_ID_UPLOAD_RESULTS: Final = "test-upload-results"
BUILD_ID_UPLOAD_TARGET_ARCH: Final = "test-build-789"
BUILD_ID_UPLOAD_FILES: Final = "test-build-files"
BUILD_ID_UPLOAD_LARGE: Final = "test-build-large"
BUILD_ID_PULL_SIDE_TAG: Final = "test-pull-side-tag"
BUILD_ID_PULL_SIDE_TAG_OCI: Final = "test-pull-side-tag-oci"
BUILD_ID_TRANSFER_OCI_ATTACH: Final = "test-transfer-oci-attach"
BUILD_ID_TRANSFER_OCI_SUBJECT: Final = "test-transfer-oci-subject"
BUILD_ID_TRANSFER_OCI_BUNDLE: Final = "test-transfer-oci-bundle"
BUILD_ID_TRANSFER_PULP_ORAS_CP: Final = "test-transfer-pulp-oras-cp"
BUILD_ID_TRANSFER_PULP_ORAS_CP_BUNDLE: Final = "test-transfer-pulp-oras-cp-bundle"
BUILD_ID_PULL_GPG_VERIFY: Final = "test-pull-gpg-verify"
BUILD_ID_UPLOAD_ORAS: Final = "test-upload-oras"
BUILD_ID_UPDATE_BUILD: Final = "test-update-build"
BUILD_ID_UPDATE_BUILD_REPLACED: Final = "test-update-build-replaced"
BUILD_ID_UPDATE_BUILD_PULL: Final = "test-update-build-pull"
BUILD_ID_E2E_ERROR_EMPTY: Final = "test-error-empty-upload"
BASE_PATH_E2E_ERROR_DUP: Final = "repo_error/dup"
REPO_E2E_ERROR_DUP: Final = "test-error-dup-repo"
SIDE_TAG_E2E_NAME: Final = "e2e-test"


def side_tag_e2e_name(run_id: str | None) -> str:
    """Run-scoped side-tag name so Pulp side-tag distributions do not collide across e2e runs."""
    if not run_id:
        return SIDE_TAG_E2E_NAME
    return f"{SIDE_TAG_E2E_NAME}-{run_id}"


def side_tag_e2e_repo_suffix(run_id: str | None) -> str:
    """Sanitized side-tag path segment for validation/cleanup (matches pulp-tool base_path)."""
    raw = side_tag_e2e_name(run_id)
    return _e2e_sanitize_build_id_for_repository(raw)


def e2e_error_upload_repo_names(build_id: str) -> list[str]:
    """Repository names a standard ``upload`` may create (for error-test cleanup)."""
    return [
        f"{build_id}/rpms",
        f"{build_id}/artifacts",
        f"{build_id}/logs",
        f"{build_id}/sbom",
    ]


def pull_side_tag_rpm_repo_key(run_id: str | None) -> str:
    """Global side-tag RPM repo key (sanitized tag only), not under source ``build_id``."""
    return side_tag_e2e_repo_suffix(run_id)

# Standalone repositories from create-repository tests.
REPO_CREATE_REPOSITORY: Final = "test-repo"
REPO_CREATE_REPOSITORY_JSON: Final = "test-repo-json"
BASE_PATH_CREATE_REPOSITORY: Final = "repo_0/test"
BASE_PATH_CREATE_REPOSITORY_JSON: Final = "repo_1/path"

_RPM_REPOS_BASE: Final = {
    f"{BUILD_ID_UPLOAD_TARGET_ARCH}/aarch64": ["test.3-1.0.0-1.aarch64.rpm"],
    f"{BUILD_ID_UPLOAD_TARGET_ARCH}/noarch": ["test.3-1.0.0-1.noarch.rpm"],
    f"{BUILD_ID_UPLOAD_TARGET_ARCH}/x86_64": ["test.3-1.0.0-1.x86_64.rpm"],
    f"{BUILD_ID_UPLOAD_FILES}/rpms": ["test.4-1.0.0-1.x86_64.rpm"],
    f"{BUILD_ID_UPLOAD_MINIMAL}/rpms": [
        "test.0-1.0.0-1.aarch64.rpm",
        "test.0-1.0.0-1.noarch.rpm",
        "test.0-1.0.0-1.x86_64.rpm",
    ],
    f"{BUILD_ID_UPLOAD_ORAS}/rpms": ["test.2-1.0.0-1.noarch.rpm"],
    f"{BUILD_ID_TRANSFER_OCI_SUBJECT}/rpms": ["test.2-1.0.0-1.noarch.rpm"],
    f"{BUILD_ID_TRANSFER_OCI_ATTACH}/rpms": ["test.2-1.0.0-1.noarch.rpm"],
    f"{BUILD_ID_UPDATE_BUILD}/rpms": ["test.2-1.0.0-1.noarch.rpm"],
    f"{BUILD_ID_UPDATE_BUILD_REPLACED}/rpms": ["test.2-1.0.0-1.noarch.rpm"],
    f"{BUILD_ID_UPDATE_BUILD_PULL}/rpms": ["test.2-1.0.0-1.noarch.rpm"],
    # Side-tag RPM repo key is run-scoped via ``pull_side_tag_rpm_repo_key`` in ``rpm_repos_for_run``.
    f"{BUILD_ID_UPLOAD_FULL}/rpms": [],
    f"{BUILD_ID_UPLOAD_FULL}/rpms-signed": [
        "test.1-1.0.0-1.aarch64.rpm",
        "test.1-1.0.0-1.noarch.rpm",
        "test.1-1.0.0-1.x86_64.rpm",
    ],
    REPO_CREATE_REPOSITORY: ["duck-0.6-1.noarch.rpm"],
    REPO_CREATE_REPOSITORY_JSON: ["duck-0.8-1.noarch.rpm", "giraffe-0.67-2.noarch.rpm"],
    f"{BUILD_ID_UPLOAD_RESULTS}/rpms": ["test.2-1.0.0-1.noarch.rpm"],
    f"{BUILD_ID_UPLOAD_LARGE}/rpms": [LARGE_RPM_FILENAME],
}

# Repos created only when ORAS e2e tests run (``--oci-storage`` set); omitted from validation/cleanup otherwise.
_OCI_OPTIONAL_RPM_REPOS: Final = frozenset(
    {
        f"{BUILD_ID_UPLOAD_ORAS}/rpms",
        f"{BUILD_ID_UPDATE_BUILD}/rpms",
        f"{BUILD_ID_UPDATE_BUILD_REPLACED}/rpms",
        f"{BUILD_ID_UPDATE_BUILD_PULL}/rpms",
        f"{BUILD_ID_TRANSFER_OCI_ATTACH}/rpms",
        f"{BUILD_ID_TRANSFER_OCI_SUBJECT}/rpms",
        f"{BUILD_ID_TRANSFER_PULP_ORAS_CP}/rpms",
    }
)
_OCI_OPTIONAL_FILE_REPOS: Final = frozenset(
    {
        f"{BUILD_ID_UPLOAD_ORAS}/artifacts",
        f"{BUILD_ID_TRANSFER_OCI_ATTACH}/artifacts",
        f"{BUILD_ID_TRANSFER_OCI_SUBJECT}/artifacts",
        f"{BUILD_ID_TRANSFER_PULP_ORAS_CP}/artifacts",
        f"{BUILD_ID_UPDATE_BUILD}/artifacts",
        f"{BUILD_ID_UPDATE_BUILD_REPLACED}/artifacts",
        f"{BUILD_ID_UPDATE_BUILD_PULL}/artifacts",
    }
)

# ``transfer`` promotes these source builds to ``konflux-<source-domain>/<source-repo>/{rpms|artifacts|…}``.
_TRANSFER_PROMOTED_RPM: Final = {
    BUILD_ID_PULL_SIDE_TAG: ["test.0-1.0.0-1.noarch.rpm"],
    BUILD_ID_PULL_SIDE_TAG_OCI: ["test.0-1.0.0-1.noarch.rpm"],
    BUILD_ID_PULL_GPG_VERIFY: ["test.3-1.0.0-1.noarch.rpm"],
    BUILD_ID_TRANSFER_OCI_ATTACH: ["test.2-1.0.0-1.noarch.rpm"],
    BUILD_ID_TRANSFER_OCI_SUBJECT: ["test.2-1.0.0-1.noarch.rpm"],
    BUILD_ID_TRANSFER_OCI_BUNDLE: ["test.2-1.0.0-1.noarch.rpm"],
    BUILD_ID_TRANSFER_PULP_ORAS_CP: ["test.2-1.0.0-1.noarch.rpm"],
    BUILD_ID_TRANSFER_PULP_ORAS_CP_BUNDLE: ["test.2-1.0.0-1.noarch.rpm"],
}
_TRANSFER_PROMOTED_FILES: Final = {
    BUILD_ID_PULL_SIDE_TAG: ["pulp_results.json"],
    BUILD_ID_PULL_SIDE_TAG_OCI: ["pulp_results.json"],
    BUILD_ID_PULL_GPG_VERIFY: ["pulp_results.json"],
    BUILD_ID_TRANSFER_OCI_ATTACH: ["pulp_results.json"],
    BUILD_ID_TRANSFER_OCI_SUBJECT: ["pulp_results.json"],
    BUILD_ID_TRANSFER_OCI_BUNDLE: ["pulp_results.json"],
    BUILD_ID_TRANSFER_PULP_ORAS_CP: ["pulp_results.json"],
    BUILD_ID_TRANSFER_PULP_ORAS_CP_BUNDLE: ["pulp_results.json"],
}

# Build IDs that create Pulp container-push OCI storage via ``--pulp-oras-cp-target`` (post-test cleanup).
CONTAINER_OCI_E2E_BUILD_IDS: Final = (
    BUILD_ID_TRANSFER_PULP_ORAS_CP,
    BUILD_ID_TRANSFER_PULP_ORAS_CP_BUNDLE,
)


def normalize_oci_storage(oci_storage: str | None) -> str:
    """Strip Konflux ``ociStorage`` / e2e ``--oci-storage`` (same as pulp-tool ``--oci-storage``)."""
    return (oci_storage or "").strip()


def oci_storage_repository_without_tag(oci_storage: str) -> str:
    """Repository reference with any tag or digest removed (Konflux bare ``ociStorage``)."""
    ref = normalize_oci_storage(oci_storage)
    if not ref:
        return ref
    if "@" in ref:
        ref = ref.split("@", 1)[0]
    slash = ref.find("/")
    if slash == -1:
        return ref
    head, tail = ref[:slash], ref[slash:]
    if ":" in tail:
        tail = tail.rsplit(":", 1)[0]
    return head + tail


def scoped_oci_storage(oci_storage: str, build_id: str, run_id: str | None) -> str:
    """
    Per-build OCI tag under ``oci_storage`` so parallel e2e uploads do not stomp ``:latest``.

    Each ``upload-build`` / side-tag ORAS publish uses ``repo:e2e-<build-id>-<run>`` instead of
    sharing one moving tag (which made later pulls of earlier ``oci_manifest`` digests fail).
    """
    repo = oci_storage_repository_without_tag(oci_storage)
    if not repo:
        return repo
    if run_id and build_id.endswith(f"-{run_id}"):
        tag_key = build_id
    else:
        tag_key = scoped_build_id(build_id, run_id)
    safe_build = re.sub(r"[^a-zA-Z0-9._-]", "-", tag_key)[:64]
    return f"{repo}:e2e-{safe_build}"


def oci_storage_e2e_enabled(oci_storage: str | None) -> bool:
    """True when ORAS-dependent e2e tests are expected to have created Pulp repos."""
    return bool(normalize_oci_storage(oci_storage))


def _without_optional_oci_repos(
    repos: dict[str, list[str]],
    optional: frozenset[str],
    oci_storage: str | None,
) -> dict[str, list[str]]:
    if oci_storage_e2e_enabled(oci_storage):
        return repos
    return {name: content for name, content in repos.items() if name not in optional}


_FILE_REPOS_BASE: Final = {
    f"{BUILD_ID_UPLOAD_FILES}/artifacts": ["pulp_results.json", "test.md"],
    f"{BUILD_ID_UPLOAD_FILES}/logs": ["x86_64/build.log"],
    f"{BUILD_ID_UPLOAD_FILES}/sbom": ["sbom.json"],
    f"{BUILD_ID_UPLOAD_MINIMAL}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPLOAD_ORAS}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_TRANSFER_OCI_ATTACH}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_TRANSFER_OCI_SUBJECT}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPDATE_BUILD}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPDATE_BUILD_REPLACED}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPDATE_BUILD_PULL}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPLOAD_FULL}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPLOAD_FULL}/sbom": ["sbom.json"],
    f"{BUILD_ID_UPLOAD_TARGET_ARCH}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPLOAD_RESULTS}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPLOAD_LARGE}/artifacts": ["pulp_results.json"],
}


def _transfer_destination_repos(
    run_id: str | None,
    source_domain: str,
    *,
    include_side_tag_sources: bool,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """RPM and file repo expectations on the Pulp domain after ``transfer`` (mainline aggregate paths)."""
    rpm_out: dict[str, list[str]] = {}
    file_out: dict[str, list[str]] = {}
    for base_build_id, rpms in _TRANSFER_PROMOTED_RPM.items():
        if not include_side_tag_sources and base_build_id in (
            BUILD_ID_PULL_SIDE_TAG,
            BUILD_ID_PULL_SIDE_TAG_OCI,
        ):
            continue
        bid = scoped_build_id(base_build_id, run_id)
        prefix = e2e_transfer_destination_repo_prefix(source_domain=source_domain, build_id=bid)
        rpm_out[f"{prefix}/rpms"] = list(rpms)
    for base_build_id, files in _TRANSFER_PROMOTED_FILES.items():
        if not include_side_tag_sources and base_build_id in (
            BUILD_ID_PULL_SIDE_TAG,
            BUILD_ID_PULL_SIDE_TAG_OCI,
        ):
            continue
        bid = scoped_build_id(base_build_id, run_id)
        prefix = e2e_transfer_destination_repo_prefix(source_domain=source_domain, build_id=bid)
        file_out[f"{prefix}/artifacts"] = list(files)
    return rpm_out, file_out


def rpm_repos_for_run(
    run_id: str | None,
    oci_storage: str | None = None,
    *,
    source_domain: str = "",
) -> dict[str, list[str]]:
    """Return RPM repository expectations keyed by run-scoped Pulp names."""
    base = _without_optional_oci_repos(dict(_RPM_REPOS_BASE), _OCI_OPTIONAL_RPM_REPOS, oci_storage)
    side_tag_repo: dict[str, list[str]] = {}
    if oci_storage_e2e_enabled(oci_storage):
        side_tag_repo[pull_side_tag_rpm_repo_key(run_id)] = ["test.0-1.0.0-1.noarch.rpm"]
    domain = (source_domain or "").strip()
    transfer_rpm: dict[str, list[str]] = {}
    if domain:
        transfer_rpm, _ = _transfer_destination_repos(
            run_id,
            domain,
            include_side_tag_sources=oci_storage_e2e_enabled(oci_storage),
        )
    if not run_id:
        base.update(side_tag_repo)
        base.update(transfer_rpm)
        return base
    scoped = {scoped_repo_name(name, run_id): content for name, content in base.items()}
    scoped.update(side_tag_repo)
    scoped.update(transfer_rpm)
    return scoped


def file_repos_for_run(
    run_id: str | None,
    oci_storage: str | None = None,
    *,
    source_domain: str = "",
) -> dict[str, list[str]]:
    """Return file repository expectations keyed by run-scoped Pulp names."""
    base = _without_optional_oci_repos(dict(_FILE_REPOS_BASE), _OCI_OPTIONAL_FILE_REPOS, oci_storage)
    domain = (source_domain or "").strip()
    _, transfer_file = _transfer_destination_repos(
        run_id,
        domain,
        include_side_tag_sources=oci_storage_e2e_enabled(oci_storage),
    )
    if not run_id:
        out = dict(base)
        out.update(transfer_file)
        return out
    scoped = {scoped_repo_name(name, run_id): content for name, content in base.items()}
    scoped.update(transfer_file)
    return scoped


def rpm_repo_names_for_cleanup(
    run_id: str | None,
    oci_storage: str | None = None,
    *,
    source_domain: str = "",
) -> set[str]:
    """RPM repository/distribution names to destroy after a run."""
    return set(rpm_repos_for_run(run_id, oci_storage, source_domain=source_domain))


def file_repo_names_for_cleanup(
    run_id: str | None,
    oci_storage: str | None = None,
    *,
    source_domain: str = "",
) -> set[str]:
    """File repository/distribution names to destroy after a run."""
    return set(file_repos_for_run(run_id, oci_storage, source_domain=source_domain))


def resolve_run_id(explicit: str | None = None) -> str | None:
    """Return a sanitized run id from CLI or ``E2E_RUN_ID``, or None for legacy single-run mode."""
    raw = (explicit or os.environ.get("E2E_RUN_ID") or "").strip()
    if not raw:
        return None
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "-", raw)
    return sanitized[:32] if sanitized else None


def scoped_build_id(base_build_id: str, run_id: str | None) -> str:
    """Append run suffix to a build id when isolating concurrent runs."""
    if not run_id:
        return base_build_id
    return f"{base_build_id}-{run_id}"


def scoped_base_path(base_path: str, run_id: str | None) -> str:
    """Append run suffix to a distribution base_path when isolating concurrent runs."""
    if not run_id:
        return base_path
    return f"{base_path}-{run_id}"


def e2e_pulp_container_oci_object_name(namespace: str, build_id: str) -> str:
    """Match :func:`pulp_tool.utils.pulp_container_oci.pulp_container_oci_object_name` for cleanup."""
    from pulp_tool.utils.pulp_container_oci import pulp_container_oci_object_name

    return pulp_container_oci_object_name(namespace, build_id)


def container_oci_names_for_cleanup(
    namespace: str,
    build_ids: list[str],
) -> list[str]:
    """Pulp container-push repository/distribution names created by ``--pulp-oras-cp-target``."""
    return [e2e_pulp_container_oci_object_name(namespace, bid) for bid in build_ids]


def scoped_repo_name(base_repo: str, run_id: str | None) -> str:
    """Qualify repository/distribution names that embed a build id or arch repo key."""
    if not run_id:
        return base_repo
    if "/" in base_repo:
        build_part, repo_suffix = base_repo.split("/", 1)
        return f"{scoped_build_id(build_part, run_id)}/{repo_suffix}"
    return scoped_build_id(base_repo, run_id)
