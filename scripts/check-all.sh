#!/bin/bash
# Run all code quality checks for pulp-tool
#
# After tests, runs diff-cover vs origin/main when available (100% on PR diff, same as CI).
# Set DIFF_COVER_COMPARE_BRANCH to override the base (e.g. origin/release-1.0).
# Requires dev deps (diff-cover). If the compare ref is missing: git fetch origin

set -e

echo "Running all code quality checks..."
echo ""

# Ruff lint and format
echo "1. Running Ruff (lint + format check)..."
python3 -m ruff check pulp_tool/ tests/ || {
    echo "❌ Ruff lint check failed. Run 'make format' to fix."
    exit 1
}
python3 -m ruff format --check pulp_tool/ tests/ || {
    echo "❌ Ruff format check failed. Run 'make format' to fix."
    exit 1
}
echo "✅ Ruff checks passed"
echo ""

# Pylint (errors only)
echo "2. Running Pylint (errors only)..."
python3 -m pylint --rcfile=config/pylintrc pulp_tool/ tests/ --errors-only -j 0 || {
    echo "❌ Pylint check failed."
    exit 1
}
echo "✅ Pylint check passed"
echo ""

# Mypy type checking
echo "3. Running Mypy type checking..."
python3 -m mypy pulp_tool/ tests/ --show-error-codes || {
    echo "❌ Mypy type checking failed."
    exit 1
}
echo "✅ Mypy type checking passed"
echo ""

# Run tests (pytest options from pyproject.toml [tool.pytest.ini_options])
echo "4. Running tests..."
python3 -m pytest --cov-report=xml || {
    echo "❌ Tests failed or coverage below threshold."
    exit 1
}
echo "✅ Tests passed"
echo ""

# PR merge gate: 100% coverage on changed lines vs merge base (optional if branch missing)
COMPARE_BRANCH="${DIFF_COVER_COMPARE_BRANCH:-origin/main}"
if command -v diff-cover >/dev/null 2>&1; then
    if git rev-parse --verify "$COMPARE_BRANCH" >/dev/null 2>&1; then
        echo "5. Diff coverage vs $COMPARE_BRANCH (100% required in PR CI)..."
        diff-cover coverage.xml --compare-branch="$COMPARE_BRANCH" --fail-under=100 || {
            echo "❌ Diff coverage below 100%. Fix tests or run: make test-diff-coverage COMPARE_BRANCH=$COMPARE_BRANCH"
            exit 1
        }
        echo "✅ Diff coverage OK"
    else
        echo "⚠️  Skipping diff-cover: $COMPARE_BRANCH not found. Run: git fetch origin"
        echo "    Then re-run this script or: make test-diff-coverage COMPARE_BRANCH=$COMPARE_BRANCH"
    fi
else
    echo "⚠️  diff-cover not on PATH; install dev deps (make install-dev). Run: make test-diff-coverage"
fi
echo ""

echo "🎉 All checks passed!"
