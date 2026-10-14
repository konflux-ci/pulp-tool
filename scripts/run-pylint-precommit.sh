#!/usr/bin/env bash
# Pre-commit wrapper — delegates to scripts/run-pylint.sh staged.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/run-pylint.sh" staged "$@"
