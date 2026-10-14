#!/usr/bin/env bash
# Pylint for pre-commit: errors-only, bounded parallelism (unlike CI/Makefile -j 0).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Default: low parallelism for interactive hooks (avoids saturating CPU/RAM).
# Override: PYLINT_JOBS=0 for all cores (same as make lint / CI).
pylint_jobs() {
  if [[ -n "${PYLINT_JOBS:-}" ]]; then
    echo "$PYLINT_JOBS"
    return
  fi
  local n="${1:-1}"
  if [[ "$n" -le 5 ]]; then
    echo 1
  else
    echo 4
  fi
}

run_pylint() {
  local -a paths=("$@")
  local jobs
  jobs="$(pylint_jobs "${#paths[@]}")"
  pylint --rcfile=config/pylintrc --errors-only -j "$jobs" "${paths[@]}"
}

if [[ $# -eq 0 ]]; then
  run_pylint pulp_tool tests
  exit 0
fi

targets=()
for path in "$@"; do
  case "$path" in
    pulp_tool/*|tests/*) targets+=("$path") ;;
  esac
done

if [[ ${#targets[@]} -eq 0 ]]; then
  exit 0
fi

# Many paths (e.g. pre-commit --all-files): one tree pass is simpler for pylint's job pool.
if [[ ${#targets[@]} -ge 40 ]]; then
  run_pylint pulp_tool tests
else
  run_pylint "${targets[@]}"
fi
