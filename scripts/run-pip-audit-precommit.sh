#!/usr/bin/env bash
# pip-audit for local hooks: reuse .audit-venv; skip when uv.lock/pyproject.toml unchanged.
# make audit invokes this with --force (always audit; still reuses the venv).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

AUDIT_VENV="${AUDIT_VENV:-.audit-venv}"
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
  esac
done

# Keep in sync with security-scan.yml
AUDIT_IGNORES=(--ignore-vuln CVE-2026-4539 --ignore-vuln GHSA-5239-wwwm-4pmq)

deps_hash() {
  sha256sum uv.lock pyproject.toml | sha256sum | awk '{print $1}'
}

CURRENT="$(deps_hash)"
STAMP="${AUDIT_VENV}/.deps-hash"

if [[ "${FORCE}" -eq 0 && -f "${STAMP}" && "$(cat "${STAMP}")" == "${CURRENT}" ]]; then
  echo "pip-audit: skip (uv.lock and pyproject.toml unchanged since last successful audit)"
  exit 0
fi

if [[ ! -x "${AUDIT_VENV}/bin/pip-audit" ]]; then
  echo "pip-audit: creating ${AUDIT_VENV}..."
  rm -rf "${AUDIT_VENV}"
  python3 -m venv "${AUDIT_VENV}"
  "${AUDIT_VENV}/bin/python" -m pip install -q -U pip uv pip-audit
fi

"${AUDIT_VENV}/bin/uv" export --frozen --extra dev --no-emit-project \
  -o "${AUDIT_VENV}/requirements-audit.txt" >/dev/null

REQ_HASH="$(sha256sum "${AUDIT_VENV}/requirements-audit.txt" | awk '{print $1}')"
if [[ ! -f "${AUDIT_VENV}/.req-hash" || "$(cat "${AUDIT_VENV}/.req-hash")" != "${REQ_HASH}" ]]; then
  echo "pip-audit: installing dev requirements from uv.lock..."
  "${AUDIT_VENV}/bin/python" -m pip install -q -r "${AUDIT_VENV}/requirements-audit.txt"
  echo "${REQ_HASH}" > "${AUDIT_VENV}/.req-hash"
fi

"${AUDIT_VENV}/bin/pip-audit" -l --desc on "${AUDIT_IGNORES[@]}"
echo "${CURRENT}" > "${STAMP}"
echo "pip-audit: OK"
