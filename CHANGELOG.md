# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0](https://github.com/konflux-ci/pulp-tool/compare/v1.1.0...v1.2.0) (2026-09-18)


### Added

* **constants:** add ppc64 to SUPPORTED_ARCHITECTURES ([2d0186a](https://github.com/konflux-ci/pulp-tool/commit/2d0186aaa355f4cadfe224b1357369caf48ee236))
* **constants:** add ppc64 to SUPPORTED_ARCHITECTURES ([49bb42e](https://github.com/konflux-ci/pulp-tool/commit/49bb42e2c10ff8a8262e102771fe43259cd023d4))


### Fixed

* **config:** remove invalid cicd_pipeline_visibility exclusion ([c43bb0d](https://github.com/konflux-ci/pulp-tool/commit/c43bb0d03af30e86b6581a78df000211d861da72))
* **config:** remove invalid cicd_pipeline_visibility exclusion ([5cc38d7](https://github.com/konflux-ci/pulp-tool/commit/5cc38d78759edecba29a5065f6ed5c4d7eddecab))
* **upload:** use 30-minute timeout for large multipart uploads ([d7b357d](https://github.com/konflux-ci/pulp-tool/commit/d7b357de74d2088d4ab9664010b51da263c9699f))
* **upload:** use 30-minute timeout for large multipart uploads ([b4cb414](https://github.com/konflux-ci/pulp-tool/commit/b4cb414257eee4c62043dcd8d3998d78193816a0))

## [Unreleased]

### Added

- `upload-build` command (`upload` remains a compatibility alias): ORAS publish of `pulp_results.json` via **`--oci-storage`** (Konflux `ociStorage`) or `cli.oci_storage`; with `--artifact-results`, Tekton files get OCI image URL (without digest) and `sha256:` digest matching import-to-quay `PULP-IMAGE_*` results ([2a3f5c8](https://github.com/konflux-ci/pulp-tool/commit/2a3f5c8))
- `pull --oci-storage` for side-tag ORAS publish (flag overrides transfer config) ([2a3f5c8](https://github.com/konflux-ci/pulp-tool/commit/2a3f5c8))
- `pull --side-tag` (with `--transfer-dest`): extra ROK RPM repo/distribution, versioned `pulp_results.json` merge, ORAS push, `--artifact-results` Tekton outputs, and optional `--snapshot-path` (`pulpResultsOciManifest`) for trusted-artifact release workspaces ([2a3f5c8](https://github.com/konflux-ci/pulp-tool/commit/2a3f5c8))
- `pulp-tool-container` image: ORAS CLI, `jq`, and Konflux `select-oci-auth` for registry auth (`oras --registry-config`); e2e ORAS tests when e2e **`--oci-storage`** is set (Konflux `ociStorage` param) ([2a3f5c8](https://github.com/konflux-ci/pulp-tool/commit/2a3f5c8))
- `pull --artifact-location` accepts an OCI manifest reference (`registry/repo@sha256:…` or `oci:…`); `pulp_results.json` is fetched with ORAS (`select-oci-auth`) before artifact download ([6e0cb3f](https://github.com/konflux-ci/pulp-tool/commit/6e0cb3f))
- Konflux e2e: side-tag pull transfer from HTTPS `pulp_results.json` or OCI manifest ref, with run-scoped `--side-tag` names and Tekton-style `--artifact-results` ([6e0cb3f](https://github.com/konflux-ci/pulp-tool/commit/6e0cb3f))
- E2e distribution URL verification: after `test_upload_full`, HTTP GET of RPM, SBOM, and `pulp_results.json` distribution URLs with Basic Auth from `pulp-access` `cli.toml` and SHA256 checks against upload metadata (`e2e/distribution_fetch.py`)
- E2e distribution fetch: wall-clock polling via `E2E_DISTRIBUTION_FETCH_MAX_WAIT_S` (default 300s) for pulp-content propagation; optional `E2E_DISTRIBUTION_FETCH_ATTEMPTS` cap; SBOM vs `pulp_results.json` probe logging on failure ([34d2254](https://github.com/konflux-ci/pulp-tool/commit/34d2254))
- E2e large RPM upload: `pre-test.py` builds a **> 300 MiB** RPM (`--large-rpm-size-mb`, default 301 MiB incompressible payload); e2e uploads to Pulp and verifies via `search-by --checksums` ([b4cb414](https://github.com/konflux-ci/pulp-tool/commit/b4cb414))
- `UPLOAD_CONTENT_TIMEOUT` (30 minutes) for multipart RPM and file uploads ([b4cb414](https://github.com/konflux-ci/pulp-tool/commit/b4cb414))
- `ppc64` architecture support in `SUPPORTED_ARCHITECTURES`, RPM path detection, upload orchestration, and content queries

### Added

- Unit test for `scripts/sync-container-build-args.sh` manifest → build-args, `VERSION`, and `pulp_tool/_version.py` output

### Changed

- Maintainer release documentation: canonical flow `make release-please` → `make release-publish` → Konflux release; version-file table; updates in `docs/releasing.md`, `CONTRIBUTING.md`, `README.md`, and agent skills
- `scripts/sync-container-build-args.sh` (run by `make release-please` on the release PR branch or `make test-container` locally) syncs `.tekton/pulp-tool-container.build-args`, `VERSION`, and `pulp_tool/_version.py` from `.release-please-manifest.json`
- `CHANGELOG.md` compare links for `v1.2.0` / `[Unreleased]`
- Konflux `pulp-tool-container` PipelineRuns pass `build-args-file` (`.tekton/pulp-tool-container.build-args`) so image OCI labels and `pulp-tool --version` use the Release Please manifest version instead of hardcoded `Dockerfile` defaults
- Konflux `pulp-tool-container` PipelineRuns migrated from deprecated `single-arch-build-pipeline` (`olm-operator-konflux-sample`) to `docker-build-oci-ta` (`container-build-catalog`), adding Conforma-required SAST and RPM signature scan tasks and dropping expired `sbom-json-check`
- Pytest configuration consolidated in `pyproject.toml` only (removed duplicate `.pytest.ini`; 85% coverage threshold unified)
- CHANGELOG entries link to implementing commits; `docs/releasing.md` and PR-drafting templates document link preservation when curating releases
- **fixing-diff-cover-failures** skill removed; diff-cover loop merged into **troubleshooting-pulp-tool-ci**
- Side-tag RPM repository and distribution use build-scoped names `{build_id}/side-tag-{tag}` (not a global `side-tag-{tag}` base path) ([6e0cb3f](https://github.com/konflux-ci/pulp-tool/commit/6e0cb3f))
- Bare Konflux `ociStorage` repository strings (no `:tag` or `@digest`) resolve with `:latest` for ORAS push and resolve ([6e0cb3f](https://github.com/konflux-ci/pulp-tool/commit/6e0cb3f))

### Fixed

- Upload and pull paths now require Pulp tasks to finish with `state == completed` (`wait_for_successful_task`), including `pulp_results.json` and RPM `add_content`, instead of treating failed tasks as success ([34d2254](https://github.com/konflux-ci/pulp-tool/commit/34d2254))
- Release `push-snapshot` failure resolving `{digest}.src` source container: PipelineRuns set `build-source-image=true` so `source-build-oci-ta` publishes the source image expected when release mapping defaults `pushSourceContainer` to true
- `upload --signed-by` now stores RPMs in the `rpms-signed` repository (matching `pulp_results.json` distribution URLs and CLI docs); previously RPMs were added to `rpms` while URLs pointed at `rpms-signed`
- Large RPM uploads no longer fail with `httpx.WriteTimeout` at the previous 120-second write limit (e.g. large debuginfo packages in sign-and-verify pipelines) ([b4cb414](https://github.com/konflux-ci/pulp-tool/commit/b4cb414))
- `pull --transfer-dest` reuses destination `RepositoryRefs` from the initial setup instead of calling `setup_repositories` again during upload (fixes Pulp HTTP 400 unique repository name on side-tag transfer) ([6e0cb3f](https://github.com/konflux-ci/pulp-tool/commit/6e0cb3f))
- Side-tag ORAS publish reuses the side-tag distribution URL from the upload step instead of creating the side-tag RPM repository twice ([6e0cb3f](https://github.com/konflux-ci/pulp-tool/commit/6e0cb3f))
- Repository create treats HTTP 400 “name must be unique” as idempotent get-existing, consistent with distribution create ([6e0cb3f](https://github.com/konflux-ci/pulp-tool/commit/6e0cb3f))

## [1.1.0] - 2026-08-25

### Added

- `i686` architecture support in `SUPPORTED_ARCHITECTURES`, RPM path detection, upload orchestration, and content queries ([e06cf41](https://github.com/konflux-ci/pulp-tool/commit/e06cf41))
- `upload --overwrite`: remove matching RPM content units in the target repo before upload (RPM-only; respects `signed_by` when set) ([01c9750](https://github.com/konflux-ci/pulp-tool/commit/01c9750))
- E2e reusable test image ([`Dockerfile.e2e`](Dockerfile.e2e)) and concurrent run isolation via `E2E_RUN_ID` / [`e2e/names.py`](e2e/names.py) ([c060d79](https://github.com/konflux-ci/pulp-tool/commit/c060d79))
- Release automation for maintainers: local [Release Please](https://github.com/googleapis/release-please) ([`scripts/release-please.sh`](scripts/release-please.sh), `make release-please`, `make release-publish`), [`.github/workflows/release.yml`](.github/workflows/release.yml), and [`docs/releasing.md`](docs/releasing.md) ([c02a88b](https://github.com/konflux-ci/pulp-tool/commit/c02a88b))
- `make lock-check` (`uv lock --check`) in CI ([6f3b1cf](https://github.com/konflux-ci/pulp-tool/commit/6f3b1cf))
- `drafting-pulp-tool-pr` agent skill for paste-ready PR drafts ([e06cf41](https://github.com/konflux-ci/pulp-tool/commit/e06cf41))
- Expanded lint toolchain: Ruff (replaces Black and Flake8), yamllint, ShellCheck, hadolint, codespell, and Checkton in pre-commit and/or CI ([3fd8121](https://github.com/konflux-ci/pulp-tool/commit/3fd8121))

### Changed

- Container image on UBI 10 minimal with Python 3.12; OpenShift preflight labels, `/licenses/LICENSE`, and non-root `USER 1001` ([0d6c302](https://github.com/konflux-ci/pulp-tool/commit/0d6c302))
- GitHub Actions unit/lint and security workflows on Python 3.12; container image build remains Konflux Tekton only ([0d6c302](https://github.com/konflux-ci/pulp-tool/commit/0d6c302))
- Agent documentation split: on-demand workflows under `skills/`; `CLAUDE.md` scoped to Konflux contracts; architecture narrative in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ([bfe4c5e](https://github.com/konflux-ci/pulp-tool/commit/bfe4c5e), [c45eb5b](https://github.com/konflux-ci/pulp-tool/commit/c45eb5b))
- Documentation audit across README, `docs/cli-reference.md`, `CONTRIBUTING.md`, `SECURITY.md`, and related files ([3fd8121](https://github.com/konflux-ci/pulp-tool/commit/3fd8121))
- `setup.py` is a thin shim; dependency ranges and package metadata live in `pyproject.toml` ([fcf528c](https://github.com/konflux-ci/pulp-tool/commit/fcf528c))
- Container `Dockerfile` installs runtime deps from `uv.lock` (`uv export --frozen --no-dev`) ([6f3b1cf](https://github.com/konflux-ci/pulp-tool/commit/6f3b1cf))
- Removed `ensure_pulp_capabilities` pre-flight status/version checks from upload, search, and pull flows ([d08de8f](https://github.com/konflux-ci/pulp-tool/commit/d08de8f))
- Mypy `[[tool.mypy.overrides]]` for `tests.*` to tolerate mocks and intentional invalid inputs ([f67bdba](https://github.com/konflux-ci/pulp-tool/commit/f67bdba))

### Removed

- Black, Flake8, and `.flake8`; deprecated `safety check` and non-blocking bandit steps from `security-scan.yml` ([3fd8121](https://github.com/konflux-ci/pulp-tool/commit/3fd8121))

### Fixed

- HTTP response validation and clearer content-search parse errors across more Pulp client paths ([c565851](https://github.com/konflux-ci/pulp-tool/commit/c565851))
- Checkton CI on pull requests only; `scripts/run-checkton.sh` fetches `origin/main` and sets diff base/head ([0e60822](https://github.com/konflux-ci/pulp-tool/commit/0e60822))
- `make audit` / pre-commit pip-audit installs from `uv.lock` so setuptools-scm does not rewrite `_version.py` during commits ([3fd8121](https://github.com/konflux-ci/pulp-tool/commit/3fd8121))
- Async repository setup tests stable under concurrent `asyncio.gather` (mock by repo name suffix, not call order) ([a329395](https://github.com/konflux-ci/pulp-tool/commit/a329395))
- Idempotent distribution setup after gateway 504 retries and Pulp name/base_path uniqueness errors ([3cee8bb](https://github.com/konflux-ci/pulp-tool/commit/3cee8bb))
- `signed_by` label normalization for uploads and Pulp queries (commas and parentheses) ([ebf366e](https://github.com/konflux-ci/pulp-tool/commit/ebf366e))
- Konflux `--artifact-results` digest writes `sha256:<hex>` from the uploaded artifact ([7fdeb58](https://github.com/konflux-ci/pulp-tool/commit/7fdeb58))
- Partial RPM upload accounting, missing `--sbom-path` errors, and SBOM classification in `--results-json` ([7fdeb58](https://github.com/konflux-ci/pulp-tool/commit/7fdeb58))
- Konflux artifact type detection by file extension before substring matching ([51f3c3f](https://github.com/konflux-ci/pulp-tool/commit/51f3c3f))
- Repository and package metadata URLs corrected to `konflux-ci/pulp-tool` ([fcf528c](https://github.com/konflux-ci/pulp-tool/commit/fcf528c))
- E2e Tekton `task-init` 0.3 migration in `pulp-e2e-testing` ([3833b01](https://github.com/konflux-ci/pulp-tool/commit/3833b01))
- Codecov flag name and `codecov.yml` configuration ([2311b82](https://github.com/konflux-ci/pulp-tool/commit/2311b82))
- Container certification preflight failures (UBI base, license, labels, non-root user) ([0d6c302](https://github.com/konflux-ci/pulp-tool/commit/0d6c302))

### Security

- Pin `pip>=26.2` in the `dev` extra for CVE-2026-13346 (doubly-encoded index URLs) ([b313813](https://github.com/konflux-ci/pulp-tool/commit/b313813))

## [1.0.0] - 2026-08-25

### Added

- Initial release of pulp-tool: CLI commands `upload`, `upload-files`, `pull`, `search-by`, and `create-repository` ([16eb193](https://github.com/konflux-ci/pulp-tool/commit/16eb193), [1001bcf](https://github.com/konflux-ci/pulp-tool/commit/1001bcf), [bf83734](https://github.com/konflux-ci/pulp-tool/commit/bf83734), [407419c](https://github.com/konflux-ci/pulp-tool/commit/407419c))
- `PulpClient`, `PulpHelper`, and `DistributionClient` for Pulp API interactions ([1001bcf](https://github.com/konflux-ci/pulp-tool/commit/1001bcf))
- RPM, log, and SBOM file management; OAuth2 authentication with automatic token refresh ([16eb193](https://github.com/konflux-ci/pulp-tool/commit/16eb193))
- `upload --target-arch-repo`: per-architecture RPM repos/distributions (`{namespace}/{arch}/Packages/...`); logs/SBOM/artifacts stay build-scoped ([c296907](https://github.com/konflux-ci/pulp-tool/commit/c296907))
- `upload --signed-by`: `signed_by` pulp label on RPMs only; separate `rpms-signed` repo ([abe5724](https://github.com/konflux-ci/pulp-tool/commit/abe5724))
- `upload --results-json`: upload artifacts listed in `pulp_results.json` ([03e8fd2](https://github.com/konflux-ci/pulp-tool/commit/03e8fd2))
- `search-by`: search RPM content by checksum, filename, and/or `signed_by`; filter `pulp_results.json` output ([abe5724](https://github.com/konflux-ci/pulp-tool/commit/abe5724))
- `pull --distribution-config` and DistributionClient username/password (Basic Auth) support ([b7dfaa3](https://github.com/konflux-ci/pulp-tool/commit/b7dfaa3))
- `--artifact-results` folder mode for local `pulp_results.json` output ([cb4603e](https://github.com/konflux-ci/pulp-tool/commit/cb4603e))
- packages.redhat.com configuration (OAuth2 and Basic Auth) documented in README ([f67bdba](https://github.com/konflux-ci/pulp-tool/commit/f67bdba))
- `make test-diff-coverage` at 100% vs `origin/main` (PR merge gate) ([c296907](https://github.com/konflux-ci/pulp-tool/commit/c296907))
- Konflux downstream documentation in `CLAUDE.md` and `.cursor/rules/konflux-ecosystem.mdc` ([cbce4e8](https://github.com/konflux-ci/pulp-tool/commit/cbce4e8))
- `AGENTS.md`, `docs/ARCHITECTURE.md`, and portable agent skills under `skills/` ([cbce4e8](https://github.com/konflux-ci/pulp-tool/commit/cbce4e8), [c45eb5b](https://github.com/konflux-ci/pulp-tool/commit/c45eb5b), [bfe4c5e](https://github.com/konflux-ci/pulp-tool/commit/bfe4c5e))
- `changing-pulp-container` agent skill; Hypothesis property tests; test tree mirroring `pulp_tool/` ([f7bc1a6](https://github.com/konflux-ci/pulp-tool/commit/f7bc1a6), [cb0ebd8](https://github.com/konflux-ci/pulp-tool/commit/cb0ebd8))
- Pulp client package refactor (`pulp_tool/api/pulp_client/`); `RepositoryApiOps`; upload gather split (`upload_collect`, `upload_common`) ([b48f73f](https://github.com/konflux-ci/pulp-tool/commit/b48f73f))
- `create_file_content_and_wait` helper; comprehensive type annotations; pre-commit hooks; `CONTRIBUTING.md`; `Makefile`; `Dockerfile` ([b48f73f](https://github.com/konflux-ci/pulp-tool/commit/b48f73f), [f67bdba](https://github.com/konflux-ci/pulp-tool/commit/f67bdba), [16cc3d4](https://github.com/konflux-ci/pulp-tool/commit/16cc3d4))
- `codecov.yml`; developer scripts; `.editorconfig`; test suite with high coverage ([a4d9277](https://github.com/konflux-ci/pulp-tool/commit/a4d9277), [c02a88b](https://github.com/konflux-ci/pulp-tool/commit/c02a88b), [16cc3d4](https://github.com/konflux-ci/pulp-tool/commit/16cc3d4))

### Changed

- Renamed `transfer` command to `pull` (`cli/pull.py`, `pulp_tool/pull/`, `PullContext`, `PullService`) ([5678651](https://github.com/konflux-ci/pulp-tool/commit/5678651))
- `pull`: re-upload to destination repos only when `--transfer-dest` is set; download URLs use per-artifact `url` fields only ([dff9ff1](https://github.com/konflux-ci/pulp-tool/commit/dff9ff1))
- Upload orchestration uses `RpmUploadResult` and typed gather models; incremental `pulp_results.json` population ([1d3bb13](https://github.com/konflux-ci/pulp-tool/commit/1d3bb13))
- `pulp_results.json` `distributions` keys for per-arch RPM bases are `rpm_<arch>` (e.g. `rpm_x86_64`) ([c296907](https://github.com/konflux-ci/pulp-tool/commit/c296907))
- Upload infers log/SBOM repo needs before setup; optional skip when no uploads expected ([c296907](https://github.com/konflux-ci/pulp-tool/commit/c296907))
- `RepositoryManager.get_repository_methods` returns `RepositoryApiOps` instead of a dict of callables ([b48f73f](https://github.com/konflux-ci/pulp-tool/commit/b48f73f))
- Consolidated dependencies into `pyproject.toml`; raised minimum versions for runtime and dev tooling ([93ee138](https://github.com/konflux-ci/pulp-tool/commit/93ee138))
- Upload progress messages at INFO; authentication failures exit with code 1 again ([785e999](https://github.com/konflux-ci/pulp-tool/commit/785e999), [ee8e255](https://github.com/konflux-ci/pulp-tool/commit/ee8e255))

### Removed

- `pulp_tool.api.task_manager`; unused status/capability helpers and trimmed test-only utilities ([6d531d4](https://github.com/konflux-ci/pulp-tool/commit/6d531d4))
- `requirements.in` and `requirements.txt` (superseded by `uv.lock`) ([6f3b1cf](https://github.com/konflux-ci/pulp-tool/commit/6f3b1cf))
- `transfer` command (use `pull`); docs GitHub workflow; Makefile `docs` targets ([5678651](https://github.com/konflux-ci/pulp-tool/commit/5678651), [8872f23](https://github.com/konflux-ci/pulp-tool/commit/8872f23))
- Sphinx and sphinx-rtd-theme from optional `dev` extras ([1f74717](https://github.com/konflux-ci/pulp-tool/commit/1f74717))

### Fixed

- Path traversal via `--results-json` artifact keys and pull log `arch` labels ([7fdeb58](https://github.com/konflux-ci/pulp-tool/commit/7fdeb58))
- Invalid `arch` in Pulp file content paths rejected ([7fdeb58](https://github.com/konflux-ci/pulp-tool/commit/7fdeb58))
- `@cached_get` cache keys include method name and full arguments ([b48f73f](https://github.com/konflux-ci/pulp-tool/commit/b48f73f))
- Synchronous `_chunked_get` raises `RuntimeError` when an event loop is already running ([4700618](https://github.com/konflux-ci/pulp-tool/commit/4700618))
- Content search empty/non-JSON bodies surface HTTP status, URL, and body preview ([e1bd66b](https://github.com/konflux-ci/pulp-tool/commit/e1bd66b))
- `PulpClient` fails fast when mTLS cert/key paths are missing ([91ce902](https://github.com/konflux-ci/pulp-tool/commit/91ce902))
- Generic `/api/v3/content/` bare JSON array responses handled without `TypeError` ([288a8d1](https://github.com/konflux-ci/pulp-tool/commit/288a8d1))
- Results JSON RPM URLs with `--signed-by` use the `rpms-signed` distribution base ([abe5724](https://github.com/konflux-ci/pulp-tool/commit/abe5724))
- RPM distribution `Packages/<letter>/` uses lowercase first character of RPM basename ([1b0e525](https://github.com/konflux-ci/pulp-tool/commit/1b0e525))
- Clear error when no auth credentials are provided ([abe5724](https://github.com/konflux-ci/pulp-tool/commit/abe5724))
- Konflux `--artifact-results` digest, partial RPM upload accounting, and parallel upload locking ([7fdeb58](https://github.com/konflux-ci/pulp-tool/commit/7fdeb58))
- CI security scan runs `pip-audit` before optional `safety`/`bandit` installs ([3833b01](https://github.com/konflux-ci/pulp-tool/commit/3833b01))

### Security

- `pip-audit` in optional `dev` dependencies, `make audit`, and `security-scan.yml` ([1f74717](https://github.com/konflux-ci/pulp-tool/commit/1f74717))
- Path traversal fixes for `--results-json` and pull log architecture labels ([7fdeb58](https://github.com/konflux-ci/pulp-tool/commit/7fdeb58))

[Unreleased]: https://github.com/konflux-ci/pulp-tool/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/konflux-ci/pulp-tool/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/konflux-ci/pulp-tool/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/konflux-ci/pulp-tool/releases/tag/v1.0.0
