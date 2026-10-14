# 3. Upload domain package and layout models

Date: 2026-10-14

## Status

Accepted

## Context

Upload logic was spread across `pulp_tool/utils/` (`uploads`, `upload_orchestrator`) and `pulp_tool/services/` (`upload_service`, `upload_collect`). CLI flags such as `--target-arch-repo` and `--target-arch-repo-build-scoped` required threading parallel booleans through many modules. Distribution URLs and Pulp labels were passed as untyped `dict[str, str]`, which made refactors error-prone and tests verbose.

Konflux Tekton tasks depend on stable CLI flags and a single orchestration path ([ARCHITECTURE.md](../ARCHITECTURE.md) §6).

## Decision

1. **`pulp_tool/upload/`** owns the upload pipeline (artifacts, SBOM, batch JSON, results gather, directory orchestration). Repository setup remains on `PulpHelper` / `RepositoryManager`.
2. **`RpmRepoLayout`** (Pydantic, frozen) is the single interpreter for RPM repository naming modes (`build_rpms`, `per_arch`, `per_arch_build_scoped`). `UploadRpmContext.rpm_repo_layout()` is the only production entry from CLI flags.
3. **Upload DTOs** (`UploadLabels`, `DistributionUrlMap`, `UploadPlan`) use `KonfluxBaseModel`. Models validate and compute paths; they do not perform HTTP.
4. **Aggressive imports:** old module paths are removed in the same change series; no re-export shims in `pulp_tool.utils` or `pulp_tool.services`.
5. **CLI-only surface:** Konflux and operators invoke `pulp-tool` commands; upload behavior is reached via `PulpHelper` → `pulp_tool.upload`, not a supported Python library API.

## Consequences

- Easier to add upload modes and Konflux-safe behavior without boolean sprawl.
- `content_query` and `repository_manager` depend on `RpmRepoLayout` for per-arch paths (optional follow-up split of large files remains in backlog).
- Contributors must place new upload behavior under `pulp_tool/upload/` and extend DTOs rather than new `dict` parameters.
- Test layout mirrors `tests/upload/` for unit coverage of the domain.
