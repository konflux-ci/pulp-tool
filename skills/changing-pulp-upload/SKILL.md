---
name: changing-pulp-upload
description: >-
  Use when changing upload, global CLI flags (--config, --build-id, --namespace),
  --rpm-path, --parent-package, --sbom-path, --artifact-results, Tekton
  workspace paths, or Konflux downstream integration. Container image *build*:
  changing-pulp-container.
---

# Changing pulp upload / Konflux integration

## Overview

Downstream Tekton pipelines invoke `pulp-tool upload` with fixed paths and flags. Changes must stay compatible with **both** call sites. **Source of truth:** [CLAUDE.md](../../docs/CLAUDE.md). **Code map:** [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) — keep logic in `PulpHelper` / `UploadService` only.

## Workflow

1. Read [CLAUDE.md](../../docs/CLAUDE.md) (two pipelines, regression checklist).
2. Re-open current upstream task YAML on GitHub (pipelines evolve):
   - [import-to-quay.yaml](https://github.com/konflux-ci/rpmbuild-pipeline/blob/main/task/import-to-quay.yaml) — step `push-to-pulp-select-auth`
   - [push-artifacts-to-storage.yaml](https://github.com/konflux-ci/release-service-catalog/blob/development/tasks/managed/push-artifacts-to-storage/push-artifacts-to-storage.yaml) — step `push-build-to-artifact-storage`
3. Implement + extend tests for every checklist item touched.
4. Update [CLAUDE.md](../../docs/CLAUDE.md) if invocation, paths, or flags change.
5. Update [docs/cli-reference.md](../../docs/cli-reference.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) when behavior or layout changes.

## Regression checklist

Before merge, verify (extend tests where applicable):

- [ ] `upload` / `upload-files` behavior, defaults, required options
- [ ] Global: `--config`, `--build-id`, `--namespace`
- [ ] `--rpm-path`, `--parent-package`, `--sbom-path`, `--artifact-results`, **`--oci-storage`** (Konflux `ociStorage`; no `cli.oci_storage` in config)
- [ ] Config/TLS/paths assumed in containers; image entrypoint and invocation (image *build*: **changing-pulp-container**)
- [ ] RPM discovery under `--rpm-path`
- [ ] Both pipelines still match (config path, flags, workspace `/var/workdir/results`, `oras-staging/` where used)

## Red flags — stop and re-read CLAUDE.md

- Changing a default flag without checking **both** Tekton scripts
- Assuming one pipeline’s flags apply to the other (`--sbom-path` is import-to-quay only)
- Duplicating upload logic outside `PulpHelper` / `UploadService`
- Skipping upstream YAML review (“we only changed tests” on upload paths)

## Common rationalizations

| Excuse | Reality |
|--------|---------|
| "Only affects rpmbuild-pipeline" | Release path uses different config and fewer flags — check both |
| "Tests pass locally" | Container paths and Tekton result files need explicit coverage |
| "Upstream YAML is stable" | ORAS/staging layout changes; re-verify linked tasks |

## Quick reference

| | import-to-quay | push-artifacts-to-storage |
|--|----------------|---------------------------|
| Config | `/pulp-access/cli.toml` | `/etc/rok-access/cli.toml` |
| Upload flags | `--parent-package`, `--sbom-path`, `--artifact-results`, **`--oci-storage`** | `--rpm-path` only |
| Missing config | Skip upload; empty Tekton results | Exit 0 without `pulp-tool` |

Full command examples and secrets behavior: [CLAUDE.md](../../docs/CLAUDE.md).
