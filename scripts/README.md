# Development Scripts

This directory contains helper scripts for common development tasks.

## Available Scripts

### `dev-setup.sh`

One-command development environment setup.

```bash
./scripts/dev-setup.sh
```

This script:
- Checks Python version
- Installs the package in development mode
- Installs pre-commit hooks

### `run-tests.sh`

Standardized test execution.

```bash
# Run all tests with coverage
./scripts/run-tests.sh

# Run specific tests
./scripts/run-tests.sh tests/cli/test_cli_core.py -v
```

### `check-all.sh`

Run all code quality checks (formatting, linting, type checking, tests).

```bash
./scripts/check-all.sh
```

This script runs:
1. Ruff lint and format check (`pulp_tool/`, `tests/`)
2. Pylint (errors only, `pulp_tool/`, `tests/`)
3. Mypy type checking
4. Pytest with coverage (options from `pyproject.toml`)
5. Diff coverage vs merge base when available (100%, same as PR CI)

For full CI parity (yamllint, shellcheck, hadolint, codespell, pip-audit, checkton), use `make pre-commit-ci`.

### `run-pylint-precommit.sh` / `run-pip-audit-precommit.sh`

Used by pre-commit for faster local hooks: scoped parallel pylint; pip-audit with a persistent `.audit-venv` and skip when lockfiles are unchanged. `make audit` calls the pip-audit script with `--force`.

### `update-deps.sh`

Update all dependencies to latest versions.

```bash
./scripts/update-deps.sh
```

This script:
- Updates pip
- Updates build tools
- Updates package dependencies
- Updates pre-commit hooks

### `release-please.sh`

Run [Release Please](https://github.com/googleapis/release-please) locally as part of the maintainer flow: **`make release-please`** (Release PR + merge + wait for Konflux on-push build) → **`make release-publish`** (`v*` tag → PyPI) → **Konflux release** (manual Release Plan for the container). See [docs/releasing.md](../docs/releasing.md).

```bash
gh auth login

# Open or update the release PR (run on main after feature merges)
./scripts/release-please.sh pr
make release-please

# After merging the release PR — push v* tag (git credentials only)
./scripts/release-please.sh publish
make release-publish

# Canonical repo on upstream (fork on origin):
RELEASE_GIT_REMOTE=upstream make release-please
RELEASE_GIT_REMOTE=upstream make release-publish

# Preview without opening a PR
./scripts/release-please.sh pr -- --dry-run --debug

# Override semver bump (major, minor, or bugfix) instead of conventional-commit inference:
make release-please BUMP=major
make release-please BUMP=bugfix
make release-publish BUMP=minor
BUMP=major ./scripts/release-please.sh pr
```

`make release-please` needs GitHub API access (`gh auth login` or a token). `make release-publish` uses plain `git tag` / `git push` only. Optional **`BUMP=major`**, **`BUMP=minor`**, or **`BUMP=bugfix`** (alias **`patch`**) bumps from [`.release-please-manifest.json`](../.release-please-manifest.json): on **`pr`**, passes **`--release-as`** to Release Please; on **`publish`**, tags the bumped version instead of the manifest value. Set **`RELEASE_GIT_REMOTE`** (default `origin`) when the release target is not `origin` — see [docs/releasing.md](../docs/releasing.md#fork-and-upstream-remotes).

## Usage

All scripts are executable and can be run directly:

```bash
chmod +x scripts/*.sh
./scripts/dev-setup.sh
```

Alternatively, use the Makefile targets:

```bash
make install-dev  # editable install + pre-commit (+ pre-push) hooks
make test         # Same as ./scripts/run-tests.sh (pytest with coverage)
make check        # lint + test (subset; use make pre-commit-ci for full CI lint gates)
make pre-commit-ci  # all pre-commit hooks (matches GitHub PR CI)
make lock         # Regenerate uv.lock (see also ./scripts/update-deps.sh for broader bumps)
make release-please   # Open/update release PR (maintainers; see docs/releasing.md)
make release-publish  # Tag release after merging release PR
make release-please BUMP=major   # Force major release PR from manifest
make release-publish BUMP=bugfix # Tag patch bump from manifest (hotfix)
```

Optional scripts (run directly):

```bash
./scripts/dev-setup.sh   # Python version check + install-dev (no commit-msg hook)
./scripts/run-tests.sh
./scripts/check-all.sh
./scripts/update-deps.sh
```
