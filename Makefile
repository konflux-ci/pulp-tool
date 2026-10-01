# Makefile for pulp-tool development tasks

COMPARE_BRANCH ?= origin/main
AUDIT_VENV ?= .audit-venv

.PHONY: help install install-dev test test-container test-e2e-container test-e2e-cleanup-container test-diff-coverage lint format check clean audit lock lock-check pre-commit-ci release-please release-publish

# Default target
help:
	@echo "Available targets:"
	@echo "  make install      - Install package"
	@echo "  make install-dev  - Install package with dev dependencies"
	@echo "  make test         - Run tests with coverage"
	@echo "  make test-container - Optional local Dockerfile smoke-test (Konflux Tekton builds on PR/push)"
	@echo "  make test-e2e-container - Optional local Dockerfile.e2e smoke-test (e2e Tekton runner image)"
	@echo "  make test-e2e-cleanup-container - Optional local Dockerfile.e2e-cleanup smoke-test (e2e finally cleanup image)"
	@echo "  make test-diff-coverage - make test + diff-cover 100% vs COMPARE_BRANCH (same gate as PR CI)"
	@echo "  make lint         - Run all linters"
	@echo "  make format       - Format code with Ruff"
	@echo "  make check        - Run all checks (lint + test)"
	@echo "  make pre-commit-ci - Run pre-commit commit + push stages (matches PR CI)"
	@echo "  make audit        - Run pip-audit (reuses .audit-venv; dev deps from uv.lock)"
	@echo "  make clean        - Clean build artifacts"
	@echo "  make lock         - Regenerate uv.lock from pyproject.toml (uv lock)"
	@echo "  make lock-check   - Fail if pyproject.toml and uv.lock are out of sync"
	@echo "  make release-please [BUMP=major|minor|bugfix]  - Open/update release PR (Release Please; gh auth or GITHUB_TOKEN)"
	@echo "  make release-publish [BUMP=major|minor|bugfix] - Push v* tag from manifest or bumped version (git only; triggers release.yml)"
	@echo "  Release remote: RELEASE_GIT_REMOTE=upstream (default origin; see docs/releasing.md)"
	@echo ""
	@echo "  Diff coverage base: COMPARE_BRANCH=origin/main (override for e.g. origin/release-1.0)"

# Installation
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	pre-commit install || echo "pre-commit not available, skipping"
	pre-commit install --hook-type pre-push || echo "pre-push hooks skipped"
	pre-commit install --hook-type commit-msg || echo "commit-msg hooks skipped"

lock:
	@command -v uv >/dev/null 2>&1 && uv lock || python3 -m uv lock

lock-check:
	@command -v uv >/dev/null 2>&1 && uv lock --check || python3 -m uv lock --check

# Testing
test:
	python3 -m pytest

# Same as GitHub Actions: 100% coverage on lines changed vs merge base (requires coverage.xml from test).
# Requires diff-cover (included in pip install -e ".[dev]" / make install-dev).
# Build the Konflux container image locally and verify pulp-tool starts (Python 3.12 / UBI 10).
test-container:
	@command -v podman >/dev/null 2>&1 && ENGINE=podman || ENGINE=docker; \
	./scripts/sync-container-build-args.sh; \
	$$ENGINE build -f container/Dockerfile --build-arg-file container/pulp-tool-container.build-args -t pulp-tool:test . && \
	$$ENGINE run --rm pulp-tool:test python3 --version && \
	$$ENGINE run --rm pulp-tool:test pulp-tool --version && \
	$$ENGINE run --rm pulp-tool:test pulp-tool --help && \
	$$ENGINE run --rm pulp-tool:test oras version && \
	$$ENGINE run --rm pulp-tool:test sh -c 'select-oci-auth quay.io/example/repo 2>/dev/null | grep -q auths'

test-e2e-container:
	@command -v podman >/dev/null 2>&1 && ENGINE=podman || ENGINE=docker; \
	$$ENGINE build -f e2e/Dockerfile.e2e -t pulp-e2e:test . && \
	$$ENGINE run --rm pulp-e2e:test python3 --version && \
	$$ENGINE run --rm pulp-e2e:test pulp-tool --version && \
	$$ENGINE run --rm pulp-e2e:test pulp --help && \
	$$ENGINE run --rm pulp-e2e:test python3 -c "import rpm_rs; print('rpm-rs OK')" && \
	$$ENGINE run --rm pulp-e2e:test oras version && \
	$$ENGINE run --rm pulp-e2e:test yq --version && \
	$$ENGINE run --rm pulp-e2e:test test -x /usr/local/bin/get-reference-base

test-e2e-cleanup-container:
	@command -v podman >/dev/null 2>&1 && ENGINE=podman || ENGINE=docker; \
	$$ENGINE build -f e2e/Dockerfile.e2e-cleanup -t pulp-e2e-cleanup:test . && \
	$$ENGINE run --rm pulp-e2e-cleanup:test python3 --version && \
	$$ENGINE run --rm pulp-e2e-cleanup:test pulp --help

test-diff-coverage: test
	@command -v diff-cover >/dev/null 2>&1 || { echo "diff-cover not found. Run: make install-dev"; exit 1; }
	@echo "Diff coverage vs $(COMPARE_BRANCH) (fail under 100%)..."
	diff-cover coverage.xml --compare-branch=$(COMPARE_BRANCH) --fail-under=100

test-fast:
	python3 -m pytest -v --tb=short

test-unit:
	python3 -m pytest -v -m unit

test-integration:
	python3 -m pytest -v -m integration

# Linting
lint: lint-ruff lint-pylint lint-mypy

lint-ruff:
	python3 -m ruff check pulp_tool/ tests/
	python3 -m ruff format --check pulp_tool/ tests/

lint-pylint:
	python3 -m pylint --rcfile=config/pylintrc pulp_tool/ tests/ --errors-only -j 0

lint-mypy:
	python3 -m mypy pulp_tool/ tests/ --show-error-codes

# Formatting
format:
	python3 -m ruff format pulp_tool/ tests/
	python3 -m ruff check --fix pulp_tool/ tests/

# Run all checks
check: lint test

# Same hooks as GitHub PR CI (commit stage + push stage).
pre-commit-ci:
	pre-commit run --all-files
	pre-commit run --hook-stage pre-push --all-files

# Pygments CVE-2026-4539: see scripts/run-pip-audit-precommit.sh and security-scan.yml

audit:
	@scripts/run-pip-audit-precommit.sh --force

# Cleanup
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf htmlcov/
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	rm -rf .audit-venv/
	rm -f coverage.xml
	rm -f .coverage
	rm -f .checkton.sarif
	rm -rf pulp_tool.egg-info
	find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

# Development helpers
setup: install-dev
	@echo "Development environment setup complete!"

update-deps:
	@./scripts/update-deps.sh

run-tests:
	@./scripts/run-tests.sh $(ARGS)

check-all:
	@./scripts/check-all.sh

# Maintainer release helpers (local Release Please — see docs/releasing.md).
# Optional BUMP=major|minor|bugfix overrides conventional-commit semver; passed to the script.
release-please:
	@BUMP='$(BUMP)' ./scripts/release-please.sh pr

release-publish:
	@BUMP='$(BUMP)' ./scripts/release-please.sh publish
