#!/usr/bin/env bash
# Pylint for pre-commit: parallel (-j 0) and only staged Python under pulp_tool/ or tests/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYLINT=(pylint --rcfile=config/pylintrc --errors-only -j 0)

if [[ $# -eq 0 ]]; then
  exec "${PYLINT[@]}" pulp_tool tests
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

exec "${PYLINT[@]}" "${targets[@]}"
