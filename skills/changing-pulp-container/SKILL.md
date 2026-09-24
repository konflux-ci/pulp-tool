---
name: changing-pulp-container
description: >-
  Use when changing the Dockerfile, .tekton/ PipelineRuns, pulp-tool-container
  image, UBI/Python base, or Konflux container build integration. Container
  images are built by Konflux Tekton — not GitHub Actions.
---

# Changing pulp-tool container image / Konflux build

## Overview

The **`pulp-tool-container`** image is built and published by **Konflux Tekton** (Pipelines as Code). GitHub Actions runs unit tests and lint only; it does **not** build the container.

**In-repo:** [Dockerfile](../../Dockerfile), [`.tekton/`](../../.tekton/). **Remote pipeline:** [docker-build-oci-ta.yaml](https://github.com/konflux-ci/container-build-catalog/blob/main/pipelines/docker-build-oci-ta/docker-build-oci-ta.yaml) (git resolver @ `main`). Full task chain: [reference.md](reference.md).

**Downstream consumers** of the published image: **changing-pulp-upload** + [CLAUDE.md](../../CLAUDE.md).

## In-repo PipelineRuns

| File | PAC trigger | Output image |
|------|-------------|--------------|
| [pulp-tool-container-build-push.yaml](../../.tekton/pulp-tool-container-build-push.yaml) | `push` → `main` | `quay.io/.../pulp-tool-container:latest` |
| [pulp-tool-container-build-pull-request.yaml](../../.tekton/pulp-tool-container-build-pull-request.yaml) | `pull_request` → `main` | `…/pulp-tool-container:on-pr-{{revision}}` (`image-expires-after: 5d`) |

Shared: namespace `artifact-storage-tenant`, app/component `tooling` / `pulp-tool-container`, SA `build-pipeline-pulp-tool-container`, workspace `git-auth`, params `git-url` + `revision`, **`build-source-image: "true"`** (required for release `push-snapshot` to resolve `{digest}.src` source containers), **`build-args-file: .tekton/pulp-tool-container.build-args`** (`VERSION`/`RELEASE` for image labels and `pulp-tool --version`; [`VERSION`](../../VERSION), [`pulp_tool/_version.py`](../../pulp_tool/_version.py), and build-args synced on the release PR by [`scripts/release-please.sh`](../../scripts/release-please.sh) via [`scripts/sync-container-build-args.sh`](../../scripts/sync-container-build-args.sh)). Release Please PR merges to `main` trigger the on-push build (see [docs/releasing.md](../../docs/releasing.md)); there is no on-tag PipelineRun.

## What the remote pipeline does

1. **`init`** — gate build; optional cache proxy.
2. **`git-clone-oci-ta`** — checkout repo at `revision`.
3. **`prefetch-dependencies-oci-ta`** — Cachi2 (empty for pulp-tool; no prefetch config in-repo).
4. **`buildah-oci-ta` (`build-container`)** — **Buildah builds [Dockerfile](../../Dockerfile) at repo root (`path-context: .`) and pushes `output-image`.** Builder stage uses network for `microdnf`/`pip`/`uv`; runtime stage installs only `python3` + `shadow-utils` and copies prefetched Python packages (no `microdnf update`, no runtime `uv`).
5. **`build-image-index`** — pass-through when `build-image-index=false`; pipeline `IMAGE_URL` / `IMAGE_DIGEST` results come from this task.
6. **`source-build-oci-ta` (`build-source-image`)** — builds and pushes a `.src` source container (PipelineRuns set `build-source-image=true`; release `push-snapshot` expects tag `{sha256-digest-with-colons-as-dashes}.src` on the same Quay repo).
7. **Post-build checks** (unless `skip-checks`) — deprecated base image, Clair, cert preflight, Snyk SAST, ClamAV, shell/unicode SAST, RPM signature scan, apply-tags, push-dockerfile.

**Debug tip:** Dockerfile errors appear in Konflux **`build-container`** logs, not GitHub Actions.

## Workflow

1. Read this skill, [Dockerfile](../../Dockerfile), and [reference.md](reference.md).
2. Re-open `.tekton/pulp-tool-container-build-*.yaml` and upstream **docker-build-oci-ta** on GitHub (bundles evolve).
3. Edit `Dockerfile` / `pyproject.toml` install deps as needed.
4. Edit `.tekton/` for publish paths/triggers only — do not vendor the remote pipeline in-repo.
5. Do **not** add GitHub Actions `docker build` as a merge gate.
6. Optional local check: `make test-container`.
7. Confirm Konflux PipelineRun on PR; after merge, **pulp-tool-container-on-push** on App Studio.
8. For version cuts, maintainers follow [docs/releasing.md](../../docs/releasing.md): after **`make release-publish`** (PyPI), run the **Konflux release** for **`pulp-tool-container`** (manual Release Plan — not triggered by the git tag).
9. If runtime Tekton invocation changes, load **changing-pulp-upload**.

## Regression checklist

- [ ] `Dockerfile` passes hadolint locally (`pre-commit run hadolint --all-files`) and in CI (DL3041/DL3013 ignored; pin UBI base tag for DL3006)
- [ ] `.tekton/` embedded scripts pass Checkton (`pre-commit run --hook-stage pre-push checkton --all-files` or CI tekton-lint job)
- [ ] `Dockerfile` builds (`make test-container` or Konflux PR `build-container` task)
- [ ] `pulp-tool --version` / `--help` in built image
- [ ] `oras version` and `select-oci-auth` in built image (ORAS push uses Tekton `~/.docker/config.json` via [select-oci-auth.sh](https://github.com/konflux-ci/build-trusted-artifacts/blob/main/select-oci-auth.sh))
- [ ] Python matches UBI base (currently **3.12** on UBI 10 minimal)
- [ ] `.tekton/` image refs and PAC CEL expressions correct
- [ ] `build-source-image` task succeeds on PR/main (release `push-snapshot` requires `.src` tag on Quay)
- [ ] No duplicate GHA container workflow
- [ ] Downstream tasks ([CLAUDE.md](../../CLAUDE.md)) unchanged

## Red flags

- GHA `docker build` as CI gate — Konflux builds on every PR/push to `main`
- Hermetic build without prefetch — would break `dnf`/`pip` in Dockerfile
- Stale Python pin vs UBI base image
- `/root/.cache` left in final image layers
- `microdnf update` in Dockerfile — adds fragile metadata fetch during Konflux builds
- Quay path / component label changes without tenant coordination

## Quick reference

| Concern | Where |
|---------|--------|
| Image recipe | `Dockerfile` |
| Triggers / Quay tags | `.tekton/pulp-tool-container-build-*.yaml` |
| Build implementation | Upstream `docker-build-oci-ta` → `buildah-oci-ta` |
| Task details | [reference.md](reference.md) |
| Local smoke test | `make test-container` |
| Runtime usage | **changing-pulp-upload** + [CLAUDE.md](../../CLAUDE.md) |
