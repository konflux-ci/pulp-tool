"""Run-scoped naming helpers for concurrent e2e execution against a shared Pulp instance."""

from __future__ import annotations

import os
import re
from typing import Final

from large_upload import LARGE_RPM_FILENAME

# Build IDs created by the e2e upload/upload-files tests (without run suffix).
BUILD_ID_UPLOAD_MINIMAL: Final = "test-build-123"
BUILD_ID_UPLOAD_FULL: Final = "test-build-456"
BUILD_ID_UPLOAD_RESULTS: Final = "test-upload-results"
BUILD_ID_UPLOAD_TARGET_ARCH: Final = "test-build-789"
BUILD_ID_UPLOAD_FILES: Final = "test-build-files"
BUILD_ID_UPLOAD_LARGE: Final = "test-build-large"

# Standalone repositories from create-repository tests.
REPO_CREATE_REPOSITORY: Final = "test-repo"
REPO_CREATE_REPOSITORY_JSON: Final = "test-repo-json"
BASE_PATH_CREATE_REPOSITORY: Final = "repo_0/test"
BASE_PATH_CREATE_REPOSITORY_JSON: Final = "repo_1/path"

# Per-arch RPM repos (--target-arch-repo); globally named in Pulp and cannot be shared concurrently.
TARGET_ARCH_REPOS: Final = frozenset({"aarch64", "noarch", "x86_64"})

_RPM_REPOS_BASE: Final = {
    "aarch64": ["test.3-1.0.0-1.aarch64.rpm"],
    "noarch": ["test.3-1.0.0-1.noarch.rpm"],
    "x86_64": ["test.3-1.0.0-1.x86_64.rpm"],
    f"{BUILD_ID_UPLOAD_FILES}/rpms": ["test.4-1.0.0-1.x86_64.rpm"],
    f"{BUILD_ID_UPLOAD_MINIMAL}/rpms": [
        "test.0-1.0.0-1.aarch64.rpm",
        "test.0-1.0.0-1.noarch.rpm",
        "test.0-1.0.0-1.x86_64.rpm",
    ],
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

_FILE_REPOS_BASE: Final = {
    f"{BUILD_ID_UPLOAD_FILES}/artifacts": ["pulp_results.json", "test.md"],
    f"{BUILD_ID_UPLOAD_FILES}/logs": ["x86_64/build.log"],
    f"{BUILD_ID_UPLOAD_FILES}/sbom": ["sbom.json"],
    f"{BUILD_ID_UPLOAD_MINIMAL}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPLOAD_FULL}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPLOAD_FULL}/sbom": ["sbom.json"],
    f"{BUILD_ID_UPLOAD_TARGET_ARCH}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPLOAD_RESULTS}/artifacts": ["pulp_results.json"],
    f"{BUILD_ID_UPLOAD_LARGE}/artifacts": ["pulp_results.json"],
}


def rpm_repos_for_run(run_id: str | None) -> dict[str, list[str]]:
    """Return RPM repository expectations keyed by run-scoped Pulp names."""
    if not run_id:
        return dict(_RPM_REPOS_BASE)
    return {scoped_repo_name(name, run_id): content for name, content in _RPM_REPOS_BASE.items()}


def file_repos_for_run(run_id: str | None) -> dict[str, list[str]]:
    """Return file repository expectations keyed by run-scoped Pulp names."""
    if not run_id:
        return dict(_FILE_REPOS_BASE)
    return {scoped_repo_name(name, run_id): content for name, content in _FILE_REPOS_BASE.items()}


def rpm_repo_names_for_cleanup(run_id: str | None) -> set[str]:
    """RPM repository/distribution names to destroy after a run."""
    return set(rpm_repos_for_run(run_id))


def file_repo_names_for_cleanup(run_id: str | None) -> set[str]:
    """File repository/distribution names to destroy after a run."""
    return set(file_repos_for_run(run_id))


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


def scoped_repo_name(base_repo: str, run_id: str | None) -> str:
    """Qualify repository/distribution names that embed a build id or arch repo key."""
    if not run_id:
        return base_repo
    if "/" in base_repo:
        build_part, repo_suffix = base_repo.split("/", 1)
        return f"{scoped_build_id(build_part, run_id)}/{repo_suffix}"
    if base_repo in TARGET_ARCH_REPOS:
        return base_repo
    return scoped_build_id(base_repo, run_id)
