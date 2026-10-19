# Releasing pulp-tool

Maintainer guide for publishing **`pulp-tool`** to [PyPI](https://pypi.org/project/pulp-tool/) and coordinating the Konflux **container** image. For day-to-day development and pull requests, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Overview

| Artifact | When | Mechanism |
|----------|------|-----------|
| **Container image (build)** | Merge to **`main`** (including the Release Please PR) | [`.tekton/pulp-tool-container-build-push.yaml`](../.tekton/pulp-tool-container-build-push.yaml) — PipelineRun **`pulp-tool-container-on-push`** |
| **Container image (release)** | After **`make release-publish`** and PyPI upload | Manual **Konflux release** (tenant Release Plan / RPA; see [Konflux container build and release](#konflux-container-build-and-release)) |
| **Python package (PyPI)** | **`v*`** tag on **`main`** | [`.github/workflows/release.yml`](../.github/workflows/release.yml) — build, GitHub Release, PyPI upload |

**Release PR automation** uses [Release Please](https://github.com/googleapis/release-please) run **locally** by maintainers ([`scripts/release-please.sh`](../scripts/release-please.sh)). It opens a Release PR with [`CHANGELOG.md`](../CHANGELOG.md) and [`.release-please-manifest.json`](../.release-please-manifest.json) updates, then syncs [`VERSION`](../VERSION), [`pulp_tool/_version.py`](../pulp_tool/_version.py), and [`container/pulp-tool-container.build-args`](../container/pulp-tool-container.build-args) onto that PR branch via [`scripts/sync-container-build-args.sh`](../scripts/sync-container-build-args.sh).

Manual tagging (below) remains supported for hotfixes or when Release Please is skipped.

## Maintainer flow (three steps)

Canonical order: **`make release-please`** → **`make release-publish`** → **Konflux release**.

| Phase | What happens | Automation |
|-------|----------------|------------|
| **1. Release Please** | Open/update Release PR, curate changelog, merge to `main`, wait for container build | `make release-please` + human merge; **`pulp-tool-container-on-push`** on push to `main` |
| **2. Publish (Python)** | Cut `vX.Y.Z` tag; clear Release Please `autorelease` labels; GitHub Release + PyPI | `make release-publish` → **`release.yml`** |
| **3. Konflux release** | Promote the built image to downstream registries/consumers | **Manual** Release Plan in Konflux / App Studio ([Konflux releasing](https://konflux-ci.dev/docs/releasing/)) |

```mermaid
flowchart TD
  subgraph step1 [1_release_please]
    RP["make release-please"]
    Curate[Curate CHANGELOG on Release PR]
    Merge[Merge Release PR to main]
    WaitBuild["Wait: pulp-tool-container-on-push succeeds"]
    RP --> Curate --> Merge --> WaitBuild
  end
  subgraph step2 [2_release_publish]
    Pub["make release-publish"]
    GHA["release.yml: GitHub Release + PyPI"]
    Pub --> GHA
  end
  subgraph step3 [3_Konflux_release]
    RelPlan["Run Release Plan in Konflux/App Studio"]
    Promote["RPA promotes image e.g. push-to-external-registry"]
    RelPlan --> Promote
  end
  WaitBuild --> Pub
  GHA --> RelPlan
```

**Checklist**

1. **`make release-please`** → curate the Release PR → merge → confirm **`pulp-tool-container-on-push`** is green in Konflux / App Studio.
2. **`make release-publish`** → confirm [**`release.yml`**](#what-runs-on-tag-push) (GitHub Release + PyPI).
3. **Run the Konflux release** for component **`pulp-tool-container`** per [Konflux releasing documentation](https://konflux-ci.dev/docs/releasing/) (tenant Release Plan / RPA; catalog pipeline e.g. [`push-to-external-registry`](https://github.com/konflux-ci/release-service-catalog/tree/development/pipelines/managed/push-to-external-registry)). Source-container (`.src`) expectations for `push-snapshot` are documented in [changing-pulp-container](../skills/changing-pulp-container/SKILL.md).

## One-time setup

### PyPI trusted publisher

Upload uses [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/) (OpenID Connect from GitHub Actions). No `PYPI_API_TOKEN` or other PyPI repository secret is required.

At https://pypi.org/manage/account/publishing/, add a publisher for the **`pulp-tool`** project with values that **exactly** match this repository and workflow:

| Field | Value |
|-------|--------|
| PyPI project name | `pulp-tool` |
| Owner | `konflux-ci` |
| Repository name | `pulp-tool` |
| Workflow name | `release.yml` |
| Environment name | *(leave blank — the workflow does not set a GitHub Environment)* |

Register the publisher before the first tag-driven release (or use a pending publisher so the project is created on first successful upload).

### GitHub repository

- Ensure **Actions** is enabled for the repository (tag push runs [`.github/workflows/release.yml`](../.github/workflows/release.yml)).
- The upload job in [`.github/workflows/release.yml`](../.github/workflows/release.yml) grants **`id-token: write`** only on **`upload-to-pypi`** (required for trusted publishing). Do not add that permission elsewhere.
- **`create-github-release`** uses **`contents: write`** only on that job.
- If you previously stored **`PYPI_API_TOKEN`**, revoke the token on PyPI and remove the repository secret; it is no longer used.

Optional hardening: create a GitHub **Environment** (e.g. `pypi`) with required reviewers, add `environment: pypi` to the upload job, and set the same environment name on the PyPI trusted publisher. That is not configured in the workflow today.

### Release Please (local CLI)

Release Please does **not** run in GitHub Actions for this repository. Maintainers run it from a checkout of **`main`**.

**Prerequisites**

| Requirement | Notes |
|-------------|--------|
| **Node.js + npm** | For `npx release-please@…` on **`make release-please`** (or install globally: `npm i -g release-please`) |
| **GitHub CLI (`gh`)** or **token** | **`make release-please`** calls the GitHub API to open/update the release PR. Use `gh auth login` (recommended) or set `GITHUB_TOKEN` / `GH_TOKEN` with **contents** and **pull-requests** write. There is no token-free mode for this step. |
| **Git push access** | **`make release-publish`** runs `git tag` + `git push` (SSH or HTTPS) |
| **GitHub CLI (`gh`) or token** | **`make release-publish`** also updates `autorelease` labels on the merged release PR (`gh auth login` or `GITHUB_TOKEN` / `GH_TOKEN` with issues write) so the next **`make release-please`** can open a new Release PR |
| **Clean `main` checkout** | `git checkout main && git pull <remote> main` before `make release-please` (use `upstream` when `RELEASE_GIT_REMOTE=upstream`) |

**Configuration files**

| File | Role |
|------|------|
| [`.github/release-please-config.json`](../.github/release-please-config.json) | `simple` release type (no `pyproject.toml` version bump — [setuptools-scm](../pyproject.toml) reads the git tag), Keep a Changelog sections |
| [`.release-please-manifest.json`](../.release-please-manifest.json) | Last released version (updated in the release PR) |

Tags use the **`v` prefix** (e.g. **`v1.2.3`**) to match [`.github/workflows/release.yml`](../.github/workflows/release.yml) and [setuptools-scm](../pyproject.toml).

**Commands**

```bash
# release-pr: gh auth is enough (no exported GITHUB_TOKEN required)
gh auth login
make release-please

# Force semver bump from manifest instead of conventional-commit inference:
make release-please BUMP=major
make release-please BUMP=bugfix

# Dry-run (no PR created):
./scripts/release-please.sh pr -- --dry-run --debug

# After merging the release PR — tag via git (no GitHub API token)
make release-publish
```

Pin the CLI version with `RELEASE_PLEASE_VERSION` (default **`17.2.0`** in the script). Override the GitHub repo with `GITHUB_REPOSITORY=owner/repo`, or set **`RELEASE_GIT_REMOTE`** so both `release-please` and `release-publish` infer `owner/repo` from that remote (default **`origin`**).

Optional **`BUMP=major`**, **`BUMP=minor`**, or **`BUMP=bugfix`** (alias **`patch`**) on **`make release-please`** computes the next version from [`.release-please-manifest.json`](../.release-please-manifest.json) and passes **`--release-as`** to Release Please — use when conventional commits would pick the wrong bump level. On **`make release-publish`**, the same variable tags the bumped version instead of the manifest (mainly for hotfix recovery; after a normal release PR merge, omit **`BUMP`** so the tag matches the manifest).

### Fork and upstream remotes

If you use a personal fork as **`origin`** and the canonical repo as **`upstream`** (e.g. `konflux-ci/pulp-tool`), releases must target **`upstream`** — PyPI trusted publishing and [`.github/workflows/release.yml`](../.github/workflows/release.yml) are registered for the canonical repo, not your fork.

```bash
# Sync main from upstream before releasing
git checkout main && git fetch upstream && git pull --ff-only upstream main

# Open/update Release PR on konflux-ci/pulp-tool (inferred from upstream URL)
RELEASE_GIT_REMOTE=upstream make release-please

# After merging the Release PR — push v* tag to upstream (triggers release.yml + PyPI)
RELEASE_GIT_REMOTE=upstream make release-publish
```

You can still set `GITHUB_REPOSITORY=konflux-ci/pulp-tool` explicitly if the remote URL is not on github.com. `gh auth login` must have permission to open PRs on the canonical repo.

### Konflux container build and release

#### Automatic build on `main`

Merging the Release Please PR (or any push) to **`main`** runs [`.tekton/pulp-tool-container-build-push.yaml`](../.tekton/pulp-tool-container-build-push.yaml), which builds:

`quay.io/redhat-user-workloads/artifact-storage-tenant/tooling/pulp-tool-container:latest`

There is **no** separate on-tag container build — the release commit is already on `main` when the release PR merges. Wait for PipelineRun **`pulp-tool-container-on-push`** to succeed before **`make release-publish`**.

#### Manual release (after `release-publish`)

After the **`v*`** tag is pushed and PyPI / GitHub Release succeed, run the **Konflux release** for **`pulp-tool-container`** using your tenant Release Plan (see [Konflux releasing](https://konflux-ci.dev/docs/releasing/)). Wire **Release Plan Admission** to a catalog pipeline such as [`push-to-external-registry`](https://github.com/konflux-ci/release-service-catalog/tree/development/pipelines/managed/push-to-external-registry) to promote the image built on `main`. This step is **not** triggered by the git tag.

**Version files synced from the manifest** (same script for Konflux and Python imports on `main` before the tag exists):

| File | Role |
|------|------|
| [`.release-please-manifest.json`](../.release-please-manifest.json) | Source of truth during the release PR (becomes the tag at publish) |
| [`container/pulp-tool-container.build-args`](../container/pulp-tool-container.build-args) | Konflux `VERSION` / `RELEASE` build args |
| [`VERSION`](../VERSION) | Copied into the Docker build context; setuptools-scm fallback without `.git` |
| [`pulp_tool/_version.py`](../pulp_tool/_version.py) | Pinned `__version__` for `pulp-tool --version` from a source checkout |

Konflux passes [`build-args-file`](https://konflux-ci.dev/docs/building/build-with-args/) into the `Dockerfile` `ARG`s for OCI labels and `pulp-tool --version`. **`make release-please`** runs [`scripts/sync-container-build-args.sh`](../scripts/sync-container-build-args.sh) on the open release PR branch after Release Please updates the manifest (requires `gh` and a clean working tree). For local smoke tests, `make test-container` runs the same sync before `podman`/`docker` build. The git tag (`make release-publish`) is created **after** the on-push container build, so the manifest is the build-time source of truth; it matches the tag once publish completes. Local editable installs may still regenerate `_version.py` via setuptools-scm until the release PR lands.

## Version numbers

Package version comes from [setuptools-scm](https://setuptools-scm.readthedocs.io/) and the git tag (see `[tool.setuptools_scm]` in [`pyproject.toml`](../pyproject.toml)). Tag **`v1.2.3`** produces version **`1.2.3`**. The release workflow sets **`SETUPTOOLS_SCM_PRETEND_VERSION`** from the pushed tag so PyPI never receives a local/dev version (e.g. `1.2.3.dev0+g…`, which PyPI rejects).

Build metadata in tags (e.g. **`v1.2.3+build.1`**) is accepted by the workflow; confirm how `setuptools_scm` maps that to the PyPI version string before publishing non-standard tags.

## Changelog format

[`CHANGELOG.md`](../CHANGELOG.md) follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/):

- Add user-facing notes under **`## [Unreleased]`** while work is in progress. Release Please may place the new **`## [X.Y.Z]`** section above `[Unreleased]` on the release PR — that is fine; after merge, keep `[Unreleased]` below the latest released version with only upcoming work.
- On release, **move** `[Unreleased]` entries into the new version section (ISO date in the heading when curating by hand). Do not leave shipped items under Unreleased.
- Use subsections **Added**, **Changed**, **Deprecated**, **Removed**, **Fixed**, **Security** as needed. Omit empty subsections.
- Write for humans: one clear line per change. End each line with a link to the implementing commit on `konflux-ci/pulp-tool`: `([abc1234](https://github.com/konflux-ci/pulp-tool/commit/abc1234))`. Use multiple links when a bullet spans more than one commit.
- Update the compare links at the bottom of the file (`[Unreleased]`, `[X.Y.Z]`, …) to point at `konflux-ci/pulp-tool`.

Release Please appends conventional-commit bullets with commit links when opening the release PR. Before merging, **curate** that section into the format above: merge duplicate bullets, keep human-readable text, **preserve commit links**, and fix org URLs to `konflux-ci/pulp-tool`.

## Automated release (recommended)

Prepare on **`main`**: merge feature PRs with conventional commit prefixes where possible (`feat:`, `fix:`, …). Continue adding user-facing notes under **`[Unreleased]`** in [`CHANGELOG.md`](../CHANGELOG.md) when helpful — Release Please consolidates them into the release PR.

### Step 1 — Release Please

1. Run **`make release-please`** on up-to-date **`main`**.
2. Review the Release PR on GitHub (title like `chore: release X.Y.Z`); **curate** the generated `CHANGELOG.md` section per [Changelog format](#changelog-format).
3. Confirm CI is green (`make test`, `make pre-commit-ci`, or `make test-diff-coverage` after `git fetch origin`).
4. **Merge the Release PR** — wait for Konflux **`pulp-tool-container-on-push`** to succeed ([automatic build](#automatic-build-on-main)).

### Step 2 — Release publish

5. Run **`make release-publish`** locally (creates tag **`vX.Y.Z`** on `main` from [`.release-please-manifest.json`](../.release-please-manifest.json) **after** the release PR merge is pulled — the script syncs from `RELEASE_GIT_REMOTE` before reading the manifest).
6. Tag push starts **`release.yml`** — build & inspect, **GitHub Release** (notes from CHANGELOG), **PyPI** upload.

### Step 3 — Konflux release

7. Run the **Konflux release** for **`pulp-tool-container`** ([manual release](#manual-release-after-release-publish)).

### Maintainer gates

- **Human merge** of the Release Please PR is the release approval gate (changelog and version files land on `main`; container image builds automatically).
- **`make release-publish`** is the deliberate step that cuts the PyPI tag.
- **Konflux release** promotes the image after PyPI is published — do not skip if downstream consumers depend on the promoted image.
- Optional: add a GitHub **Environment** on `upload-to-pypi` for extra PyPI approval (see one-time setup).
- **Do not** use Konflux [`release-to-github`](https://github.com/konflux-ci/release-service-catalog/tree/development/pipelines/managed/release-to-github) for PyPI — that pipeline attaches **binaries extracted from container images**, not Python sdist/wheel from git tags.

## Manual release (hotfix or bypass)

1. Merge changes to **`main`** and confirm CI is green.
2. Update [`CHANGELOG.md`](../CHANGELOG.md): move items from **`[Unreleased]`** into a new **`[X.Y.Z]`** section with the release date, and add compare links at the bottom per [Keep a Changelog](https://keepachangelog.com/).
3. Commit the changelog update on **`main`** if it is not already included.
4. Tag and push:

```bash
git checkout main
git pull origin main
git tag v1.2.3
git push origin v1.2.3
```

5. Bump [`.release-please-manifest.json`](../.release-please-manifest.json) to **`"1.2.3"`** on `main` in a follow-up PR so Release Please stays in sync.

Tags must match **`vMAJOR.MINOR.PATCH`** with optional SemVer pre-release and build metadata (e.g. **`v1.2.3`**, **`v1.2.3-rc1`**, **`v1.2.3+build.1`**) and must point at a commit on **`main`**. Other tags are rejected by the workflow.

## What runs on tag push

**Release python package** ([`.github/workflows/release.yml`](../.github/workflows/release.yml)):

1. **Build & inspect package** — builds sdist and wheel with Python **3.12**, runs wheel/README checks via [`hynek/build-and-inspect-python-package`](https://github.com/hynek/build-and-inspect-python-package).
2. **Create GitHub Release** — release notes from the matching **`## [X.Y.Z]`** section in [`CHANGELOG.md`](../CHANGELOG.md) (via [`.github/scripts/extract-changelog-notes.sh`](../.github/scripts/extract-changelog-notes.sh)); pre-releases when the tag contains **`-`**.
3. **Upload package to PyPI** — [`pypa/gh-action-pypi-publish`](https://github.com/pypa/gh-action-pypi-publish) with trusted publishing (OIDC).

Container images are **not** rebuilt on tag push; they are produced when the release commit merges to **`main`** (see [Konflux container build and release](#konflux-container-build-and-release) above).

## Verify the release

- In GitHub **Actions**, open the workflow run for the tag and confirm build, GitHub Release, and PyPI jobs succeeded.
- On GitHub **Releases**, confirm the release page and notes.
- On PyPI, confirm the new version at https://pypi.org/project/pulp-tool/
- In Konflux, confirm **`pulp-tool-container-on-push`** succeeded for the release merge commit.
- After the **Konflux release**, confirm the promoted container image on tenant Quay / external registry (per your Release Plan).
- Optionally install locally: `pip install pulp-tool==1.2.3`

## Troubleshooting

| Issue | Check |
|-------|-------|
| No Release Please PR | Run `make release-please` on up-to-date `main`; ensure commits since last tag warrant a release; try `--dry-run --debug` |
| `release-please` / `npx` not found | Install Node.js/npm or `npm i -g release-please` |
| Token errors on `make release-please` | Run `gh auth login` or set `GITHUB_TOKEN` with contents + pull-requests write; Release Please cannot open PRs without GitHub API auth |
| `make release-publish` git push failed | Configure git push (SSH key or HTTPS credential helper) for `RELEASE_GIT_REMOTE` |
| `make release-publish` label sync failed | Run `gh auth login` or set `GITHUB_TOKEN` / `GH_TOKEN`. If the tag is already on the remote, run **`./scripts/release-please.sh sync-release-labels`** (uses [`.release-please-manifest.json`](../.release-please-manifest.json)), then **`make release-please`** |
| Untagged merged release PRs / `make release-please` aborts | Merged release PR still has **`autorelease: pending`** while **`vX.Y.Z`** already exists — run **`./scripts/release-please.sh sync-release-labels`** on up-to-date **`main`**, then **`make release-please`** |
| Tag not created after release PR merge | Run `make release-publish` locally — tagging is not automatic on merge |
| Wrong tag version on publish | Ensure the release PR is merged and run publish **after** the script pulls `main` (it reads `.release-please-manifest.json` from the synced tree, not a stale local copy). Delete a mistaken tag on the remote if needed before re-publishing. |
| Tag pushed to fork by mistake | Use `RELEASE_GIT_REMOTE=upstream make release-publish` (or `git push upstream vX.Y.Z`); PyPI expects tags on `konflux-ci/pulp-tool` |
| Release Please PR out of sync after manual tag | Update [`.release-please-manifest.json`](../.release-please-manifest.json) to the released version on `main` |
| Workflow did not start | Tag must match `v*` and be pushed to the canonical repo (`RELEASE_GIT_REMOTE=upstream` or `git push upstream vX.Y.Z`) |
| Tag format rejected | Use SemVer tags such as `v1.2.3`, `v1.2.3-rc1`, or `v1.2.3+build.1` (not `1.2.3` without the `v` prefix) |
| Not on `main` | Tag must point at a commit reachable from `main` (checked via GitHub compare API) |
| Upload auth failed | PyPI trusted publisher must match `konflux-ci` / `pulp-tool` / workflow `release.yml` with a blank environment name; upload job needs `id-token: write` |
| PyPI 400 local version (`+g…` or `.dev0`) | Tag build must use a clean semver — [`.github/workflows/release.yml`](../.github/workflows/release.yml) sets `SETUPTOOLS_SCM_PRETEND_VERSION` from the tag; re-run after that fix is on `main`, or delete the tag and re-push on a commit that includes the fix |
| Empty GitHub Release notes | Ensure `CHANGELOG.md` has a **`## [X.Y.Z]`** section for that version before tagging |
| Wrong package version | Tag name must match the intended release; rebuild requires a new tag |
| Container not rebuilt | Merging the release PR must land on `main`; check Konflux PipelineRun `pulp-tool-container-on-push` |
| Image not promoted externally | Konflux **release** is manual after `release-publish`; run the tenant Release Plan for `pulp-tool-container` ([Konflux releasing](https://konflux-ci.dev/docs/releasing/)) |
