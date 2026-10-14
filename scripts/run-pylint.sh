#!/usr/bin/env bash
# Canonical pylint entry (Makefile, GitHub Actions, pre-commit).
#
#   full|ci     — entire tree: pulp_tool tests (make lint-pylint, CI)
#   staged …    — pre-commit: staged paths under pulp_tool/ or tests/
#
# Flags: --rcfile=config/pylintrc --errors-only -j "${PYLINT_JOBS:-0}"
# Override jobs locally: PYLINT_JOBS=4 scripts/run-pylint.sh staged …
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYLINT=(python3 -m pylint --rcfile=config/pylintrc --errors-only)
JOBS="${PYLINT_JOBS:-0}"
LINT_TREE=(pulp_tool tests)

run_full_tree() {
  "${PYLINT[@]}" -j "$JOBS" "${LINT_TREE[@]}"
}

run_staged() {
  local -a targets=()
  for path in "$@"; do
    case "$path" in
      pulp_tool/*|tests/*) targets+=("$path") ;;
    esac
  done
  if [[ ${#targets[@]} -eq 0 ]]; then
    exit 0
  fi
  if [[ ${#targets[@]} -ge 40 ]]; then
    run_full_tree
    exit 0
  fi
  "${PYLINT[@]}" -j "$JOBS" "${targets[@]}"
}

mode="${1:-full}"
case "$mode" in
  full | ci)
    run_full_tree
    ;;
  staged)
    shift
    if [[ $# -eq 0 ]]; then
      run_full_tree
    else
      run_staged "$@"
    fi
    ;;
  *)
    echo "usage: $0 full|ci|staged [paths…]" >&2
    exit 2
    ;;
esac
