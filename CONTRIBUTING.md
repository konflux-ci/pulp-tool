# Contributing to Pulp Tool

Thank you for your interest in contributing to Pulp Tool! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.12 (matches CI and the Konflux container image on UBI 10); `requires-python` is `>=3.12`
- Git
- pip

### Initial Setup

1. Fork the repository on GitHub
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/pulp-tool.git
   cd pulp-tool
   ```

3. Install the package in development mode and set up pre-commit hooks:
   ```bash
   make install-dev
   ```
   This runs `pip install -e ".[dev]"`, `pre-commit install`, `pre-commit install --hook-type pre-push`, and optional commit-msg hooks.

### Using Development Scripts

We provide scripts to help with common development tasks:

```bash
# Setup development environment
./scripts/dev-setup.sh

# Run all tests
./scripts/run-tests.sh

# Run all checks (linting, type checking, tests)
./scripts/check-all.sh

# Update dependencies
./scripts/update-deps.sh
```

Alternatively, use the Makefile:

```bash
make test      # Run tests
make lint      # Run linters
make format    # Format code
make check     # Run all checks
make clean     # Remove coverage, caches, and local build artifacts
```

### Documentation for coding agents

- **[AGENTS.md](docs/AGENTS.md)** — canonical agent scaffold; **§ Bootstrap** lists the read-first order (minimizes context thrash).
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — system design, code map, diagrams, invariants, glossary (living doc).
- **Cursor rules:** [`.cursor/rules/llm-development-guidelines.mdc`](.cursor/rules/llm-development-guidelines.mdc) (always-on essentials), [`.cursor/rules/llm-development-guidelines-deep.mdc`](.cursor/rules/llm-development-guidelines-deep.mdc) (skill index).
- **Agent skills:** [`skills/`](skills/) — portable on-demand workflows ([`skills/README.md`](skills/README.md)); auto-discovered via [`.cursor/skills/`](.cursor/skills/) and [`.agents/skills/`](.agents/skills/) symlinks for Cursor and other agentskills.io clients.
- **[CLAUDE.md](docs/CLAUDE.md)** — Konflux/Tekton downstream contracts (paths, flags, task YAMLs), regression checklist; complements **AGENTS.md** / **ARCHITECTURE.md**.
- Optional: [AgentReady](https://github.com/ambient-code/agentready) (`agentready assess .`) with [.agentready-config.yaml](.agentready-config.yaml).

### Dependency lock file

Pinned lockfile:

- **`uv.lock`** — from **`pyproject.toml`** via **[uv](https://github.com/astral-sh/uv)** (`uv lock` or `python3 -m uv lock`).

After changing dependencies in **`pyproject.toml`**, regenerate the lockfile:

```bash
pip install -e ".[dev]"
make lock
```

Commit the updated **`uv.lock`**. Normal installs remain **`pip install -e ".[dev]"`** from pyproject; the lockfile supports reproducible CI, audits, and the Konflux container image. **`setup.py`** is a thin shim only — all dependency ranges and package metadata are in **`pyproject.toml`**. The Konflux image [`container/Dockerfile`](container/Dockerfile) exports runtime pins from **`uv.lock`** (`uv export --frozen --no-dev`) and installs with **`pip`**.

**Mintmaker / Renovate** ([`.github/renovate.json`](.github/renovate.json)) bumps **`pyproject.toml`** and regenerates **`uv.lock`** in the same PR (`pep621` manager + `lockFileMaintenance`). CI runs **`make lock-check`** (`uv lock --check`) so the two files cannot drift on merge.

### Commit messages

Optional [**Conventional Commits**](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, …) are enforced if you install commit-msg hooks:

```bash
pre-commit install --hook-type commit-msg
```

## Code Style

### Formatting

We use [Ruff](https://docs.astral.sh/ruff/) for code formatting and linting (replacing Black and Flake8) with a line length of 120 characters.

```bash
# Format code
make format
# or: ruff format pulp_tool/ tests/ && ruff check --fix pulp_tool/ tests/

# Check formatting and lint without changes
make lint
# or: ruff check pulp_tool/ tests/ && ruff format --check pulp_tool/ tests/
```

### Linting

We use multiple linting tools:

- **Ruff**: Style guide enforcement, import sorting, and security checks (S ruleset)
- **Pylint**: Code quality analysis (errors only in CI)
- **Mypy**: Static type checking
- **yamllint**, **ShellCheck**, **hadolint**, **codespell**: YAML, shell scripts, Dockerfile, and spelling (pre-commit + CI)
- **Checkton**: ShellCheck on embedded Tekton scripts (pre-push hook + CI)

```bash
# Run Python linters (same commands as CI python-lint job)
make lint

# Or individually:
ruff check pulp_tool/ tests/
ruff format --check pulp_tool/ tests/
pylint --rcfile=config/pylintrc pulp_tool/ tests/ --errors-only -j 0
mypy pulp_tool/ tests/ --show-error-codes
```

**Pre-commit matches GitHub PR CI** for full-tree checks (`make pre-commit-ci`). On each commit, **pylint** runs only on staged `pulp_tool/` and `tests/` Python files (parallel `-j 0`); **pip-audit** runs only when `uv.lock` or `pyproject.toml` change (reuses `.audit-venv`, skips if those files are unchanged since the last successful audit). Pre-push hooks run `make test-diff-coverage` and Checkton (install with `pre-commit install --hook-type pre-push`). Run everything locally:

```bash
make pre-commit-ci
# or:
pre-commit run --all-files
pre-commit run --hook-stage pre-push --all-files   # needs git fetch origin first
```

Requires `pip install -e ".[dev]"` (ruff, pylint, mypy, yamllint, pre-commit). Hadolint is downloaded into the pre-commit cache on first use; codespell runs via the pre-commit hook environment. Checkton (pre-push) needs docker or podman.

### Type Annotations

- All function arguments must have type annotations
- Return types should be specified for all functions
- Use `Optional[T]` for nullable types
- Use `Union[T1, T2]` for multiple possible types
- Use `TYPE_CHECKING` for forward references to avoid circular imports

Example:
```python
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .api.pulp_client import PulpClient

def my_function(client: "PulpClient", value: Optional[str] = None) -> bool:
    """Function with proper type annotations."""
    return value is not None
```

## Testing

### Running Tests

```bash
# Run all tests with coverage (preferred; enforces 85%+)
make test

# Before a PR: full suite + 100% coverage on git diff vs origin/main (matches CI)
# git fetch origin   # ensure compare branch exists
make test-diff-coverage
# Override base branch: make test-diff-coverage COMPARE_BRANCH=origin/my-base

# Or with pytest directly (options from pyproject.toml)
pytest

# Run specific test file
pytest tests/cli/test_cli_core.py -v

# Run specific test markers
pytest -m unit
pytest -m integration
```

### Test Requirements

- All new code must include tests
- Overall test coverage must remain at or above 85%
- New and changed lines must have 100% coverage (enforced in CI via diff coverage)
- **Before opening or updating a PR**, run `make test-diff-coverage` after `git fetch origin` so your local report matches the merge gate (`diff-cover` vs `origin/main` by default). Use `make test-diff-coverage COMPARE_BRANCH=origin/<base>` if the PR targets another branch.
- Tests should be fast and isolated
- Use fixtures from `tests/conftest.py` when possible
- Mark slow tests with `@pytest.mark.slow`
- Mark integration tests with `@pytest.mark.integration`

### Writing Tests

- Follow the existing test structure
- Use descriptive test names: `test_function_name_scenario_expected_result`
- Use pytest fixtures for common setup
- Mock external dependencies (HTTP calls, file system, etc.)
- Test both success and failure cases
- Test edge cases and boundary conditions

Example:
```python
import pytest
from unittest.mock import Mock, patch

def test_upload_content_success():
    """Test successful content upload."""
    client = Mock()
    client.upload_content.return_value = "/api/v3/content/123/"

    result = upload_content(client, "/path/to/file.rpm", {})
    assert result == "/api/v3/content/123/"
    client.upload_content.assert_called_once()
```

## Pull Request Process

### Before Submitting

1. **Update CHANGELOG.md**: Add an entry describing your changes
2. **Update documentation**: If adding features, update README.md as needed
3. **Run all checks**: Ensure `make check` passes, or run `make pre-commit-ci` (matches GitHub PR CI), or `make lint` + `pre-commit run --all-files` + `git fetch origin` + `pre-commit run --hook-stage pre-push --all-files`
4. **Verify PR diff coverage**: Run `make test-diff-coverage` (requires `git fetch origin` so `origin/main` or your `COMPARE_BRANCH` exists); CI fails below 100% on the diff
5. **Write tests**: Add tests for new functionality (new/changed code requires 100% diff coverage)
6. **Update type hints**: Ensure all functions have proper type annotations

### PR Checklist

- [ ] Code follows the project's style guidelines
- [ ] All tests pass (`make test`)
- [ ] PR diff coverage is 100% (`make test-diff-coverage` after `git fetch origin`)
- [ ] All linters pass (`make lint` or commit-stage pre-commit hooks)
- [ ] Pre-commit hooks pass (`make pre-commit-ci`, or commit + pre-push stages separately)
- [ ] Test coverage is maintained or improved (85%+ overall, 100% for new/changed lines)
- [ ] CHANGELOG.md is updated
- [ ] Documentation (e.g. README.md) is updated if needed
- [ ] Commits follow the commit message conventions

### Commit Messages

Follow these conventions for commit messages:

```
type(scope): short description

Longer description if needed, explaining what and why.

Fixes #123
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Test additions or changes
- `chore`: Maintenance tasks

Examples:
```
feat(cli): add --overwrite option to upload command

Removes matching NVRA packages from the target RPM repo before upload
when the same filename (and signed_by label) already exists.

fix(pull): handle missing artifact metadata gracefully

Previously would crash if artifact JSON was missing expected
fields. Now logs warning and continues.

docs(readme): update installation instructions

Adds Python 3.12 support information.
```

#### AI-assisted commits

When the work was produced with an AI assistant, end the commit message with this trailer block (after a blank line following the subject or body):

```
<type(scope): short description>

Assisted-By: Cursor
Signed-off-by: Your Name <your-email@example.com>
```

- **Assisted-By:** The **agent or product** you used (e.g. `Cursor`, `Composer`, `Claude`).
- **Signed-off-by:** **You** as the human author, in [Developer Certificate of Origin](https://developercertificate.org/) form — typically `git config user.name` and `git config user.email`, often aligned with your [GitHub commit email](https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-email-preferences/setting-your-commit-email-address).

A blank layout you can copy is **`.github/commit-message-template.txt`**. To use it as the editor starter for every commit: `git config commit.template .github/commit-message-template.txt` (repo-relative path; adjust if you set it globally).

### PR Description Template

When creating a PR, include:

1. **Summary**: Brief description of changes
2. **Type**: Feature, Bug Fix, Documentation, etc.
3. **Changes**: Detailed list of changes
4. **Testing**: How to test the changes
5. **Related Issues**: Link to related issues

Example:
```markdown
## Summary
Adds --overwrite option to upload command to replace same-NVRA RPMs before upload.

## Type
Feature

## Changes
- Added --overwrite flag to upload command
- Removes existing RPM units in the target repo matching local NVRA (and signed_by when set)
- Updated help text and documentation

## Testing
- Run `pulp-tool upload --overwrite ...` against a repo with duplicate NVRA
- Verify old content is removed and new RPM is uploaded
- Check logs for overwrite/remove messages

## Related Issues
Closes #123
```

## Code Review

- All PRs require at least one approval before merging
- Address review comments promptly
- Be respectful and constructive in reviews
- Ask questions if something is unclear

## Releases

Maintainers publish **two artifacts** (Python on PyPI, container via Konflux). Canonical flow:

1. **`make release-please`** — open/update the Release PR, curate changelog, merge to `main`, wait for **`pulp-tool-container-on-push`**.
2. **`make release-publish`** — push the `v*` tag; GitHub Actions uploads to PyPI.
3. **Konflux release** — run the tenant Release Plan for **`pulp-tool-container`** after PyPI (image promotion is not automatic on tag push).

Full setup, diagrams, and troubleshooting: **[docs/releasing.md](docs/releasing.md)**.

## Questions?

- Open an issue for bug reports or feature requests
- Check existing issues and PRs before creating new ones
- Join discussions in existing issues/PRs

Thank you for contributing to Pulp Tool!
