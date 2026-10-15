---
name: troubleshooting-pulp-tool-ci
description: >-
  Use when pre-commit hooks fail, make test-diff-coverage fails, lint errors
  persist after make format, or local checks disagree with CI on pulp-tool.
---

# Troubleshooting pulp-tool CI

Lint toolchain and hook list: [CONTRIBUTING.md](../../CONTRIBUTING.md) and [llm-development-guidelines-deep.mdc](../../.cursor/rules/llm-development-guidelines-deep.mdc).

## Pre-commit loop

```bash
make install-dev      # once per clone: commit + pre-push hooks
make pre-commit-ci    # before opening a PR
```

Or step by step:

```bash
pre-commit run --all-files
git fetch origin
pre-commit run --hook-stage pre-push --all-files
```

Fix **every** failure, then re-run until zero failures. Single hook: `pre-commit run <hook-id> --all-files`.

## Diff coverage (100% on PR diff)

Merge requires **100% coverage on changed lines** vs the PR base — not overall project coverage.

```bash
git fetch origin
make test-diff-coverage
# Non-main base: make test-diff-coverage COMPARE_BRANCH=origin/<base>
```

1. Read uncovered lines from `diff-cover` output.
2. Add or extend tests until every **changed** line is executed.
3. Re-run `make test`, then `make test-diff-coverage`; repeat until green.

**Red flags:** PR-ready after `make test` only; relying on high overall coverage; `# pragma: no cover` without justification.

## Lint quick reference

```bash
make lint && make format
make audit
```

Prefer Makefile targets over invoking tools directly.

## Common issues

| Issue | Solution |
|-------|----------|
| Ruff import order (I001) | Run `make format` or `ruff check --fix` |
| Ruff S105 on OAuth/token URLs | Use `RED_HAT_SSO_TOKEN_URL` constant or `# noqa: S105` |
| Mypy errors in specific modules | Check `[[tool.mypy.overrides]]` in `pyproject.toml` |
| Hooks fail on commit | Loop `pre-commit run --all-files` until clean |
| Local vs CI pylint mismatch | Use `make lint-pylint` (same as GHA); pre-commit pylint uses `scripts/run-pylint.sh staged` with the same flags and default `-j 1`; `-j 0` auto-parallel often **slows** this repo (import-heavy tree) — try `PYLINT_JOBS=2` on a fast machine if needed |
| Pylint pegs CPU / feels stuck | Default is single-process (`PYLINT_JOBS=1`); `pre-commit run --all-files` lints the full tree when ≥40 Python files match; incremental cache is `.pylint.d/` (`make clean` removes it) |
| Pre-commit fans out CPU (many hooks) | `PRE_COMMIT_NO_CONCURRENCY=1` runs hook repos one at a time |
| Yamllint truthy on `on:` | `# yamllint disable-line rule:truthy` (see release workflow) |
| Hadolint DL3041/DL3013 | Ignored in pre-commit/CI (UBI microdnf + pip pattern) |
| checkton: docker/podman required | Install podman/docker, or rely on CI `tekton-lint` |
| checkton: missing `origin/main` | `git fetch origin main` or set `CHECKTON_DIFF_BASE` |
| checkton detached HEAD after pre-push | Do not set `CHECKTON_DIFF_HEAD` locally |
| test-diff-coverage on pre-push | `git fetch origin` so compare ref exists |
| pip-audit rewrites `_version.py` | `make audit` uses `uv export` (no editable install) |

## Config files

`.pre-commit-config.yaml`, `pyproject.toml`, `config/yamllint.yml`, `Makefile` (`make pre-commit-ci`, `make clean`).
