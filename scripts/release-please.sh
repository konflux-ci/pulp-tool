#!/usr/bin/env bash
# Run Release Please locally (maintainer workflow). See docs/releasing.md.
#
# Usage:
#   ./scripts/release-please.sh pr [-- extra release-please flags]
#   ./scripts/release-please.sh publish
#   ./scripts/release-please.sh sync-release-labels
#
# pr:      uses release-please release-pr (GitHub API — needs gh login or a token)
# publish: git tag + push, then mark the merged release PR complete for Release Please
#
# Optional BUMP=major|minor|bugfix overrides conventional-commit semver inference:
# pr passes --release-as with the bumped version; publish tags that version.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RELEASE_PLEASE_VERSION="${RELEASE_PLEASE_VERSION:-17.2.0}"
TARGET_BRANCH="${RELEASE_PLEASE_TARGET_BRANCH:-main}"
RELEASE_GIT_REMOTE="${RELEASE_GIT_REMOTE:-origin}"
CONFIG_FILE="${RELEASE_PLEASE_CONFIG_FILE:-.github/release-please-config.json}"
MANIFEST_FILE="${RELEASE_PLEASE_MANIFEST_FILE:-.release-please-manifest.json}"

# BUMP (make) or RELEASE_BUMP: major | minor | bugfix (patch accepted as bugfix).
RELEASE_BUMP="${RELEASE_BUMP:-${BUMP:-}}"

semver_tag_pattern='^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$'

normalize_release_bump() {
  local raw="${1,,}"
  case "$raw" in
    major | minor | bugfix | patch) printf '%s' "$raw" ;;
    *)
      echo "Invalid release bump \"${1}\" (expected major, minor, or bugfix)" >&2
      return 1
      ;;
  esac
}

bump_version_from_manifest() {
  local bump_kind
  bump_kind="$(normalize_release_bump "$1")"
  if [[ "$bump_kind" == patch ]]; then
    bump_kind="bugfix"
  fi
  python3 - "$bump_kind" "$MANIFEST_FILE" <<'PY'
import json
import re
import sys

bump = sys.argv[1]
with open(sys.argv[2], encoding="utf-8") as fh:
    data = json.load(fh)
base = data.get(".")
if not base or not isinstance(base, str):
    raise SystemExit(f"Invalid manifest version in {sys.argv[2]!r}: {base!r}")
base = base.strip()
match = re.match(r"^(\d+)\.(\d+)\.(\d+)", base)
if not match:
    raise SystemExit(f"Cannot bump version {base!r} (expected X.Y.Z prefix)")
major, minor, patch = (int(match.group(i)) for i in range(1, 4))
if bump == "major":
    major += 1
    minor = 0
    patch = 0
elif bump == "minor":
    minor += 1
    patch = 0
elif bump == "bugfix":
    patch += 1
else:
    raise SystemExit(f"Unsupported bump {bump!r}")
print(f"{major}.{minor}.{patch}")
PY
}

usage() {
  cat <<'EOF'
Usage: release-please.sh <command> [-- extra release-please flags]

Commands:
  pr        Create or update the release pull request (run on main after feature merges).
            Also syncs container/pulp-tool-container.build-args, VERSION, and pulp_tool/_version.py
            on the release PR branch.
  publish   Create and push v* tag from .release-please-manifest.json (triggers release.yml),
            then update autorelease labels on the merged release PR so the next release-pr
            run can open a new Release PR. Optional BUMP=major|minor|bugfix tags a bumped
            version instead of the manifest.
  sync-release-labels  Update autorelease labels only (no tag). Uses the version in
            .release-please-manifest.json — for recovery when the tag was pushed earlier.

Authentication:
  pr        release-please talks to the GitHub API. Provide GITHUB_TOKEN/GH_TOKEN, or run
            `gh auth login` — the script uses `gh auth token` when no token env var is set.
  publish   git tag push (SSH or HTTPS) plus GitHub API via `gh` (or GITHUB_TOKEN/GH_TOKEN)
            to clear autorelease: pending on the merged release PR

Environment:
  BUMP or RELEASE_BUMP        Optional bump kind for pr (--release-as) or publish (tag):
                              major, minor, bugfix (patch is an alias for bugfix).
                              make release-please BUMP=major
  GITHUB_TOKEN or GH_TOKEN   Optional if `gh auth login` is configured (pr command only)
  GITHUB_REPOSITORY          owner/repo (optional; inferred from RELEASE_GIT_REMOTE)
  RELEASE_GIT_REMOTE         Git remote for fetch/pull/tag push and repo inference (default: origin)
  RELEASE_PLEASE_VERSION     npm package pin (default: 17.2.0)
  RELEASE_PLEASE_TARGET_BRANCH Target branch (default: main)

Examples:
  gh auth login
  ./scripts/release-please.sh pr
  make release-please BUMP=major
  make release-please BUMP=bugfix
  ./scripts/release-please.sh pr -- --dry-run --debug
  make release-publish BUMP=minor
  # Fork workflow (canonical repo on upstream remote):
  RELEASE_GIT_REMOTE=upstream ./scripts/release-please.sh pr
  RELEASE_GIT_REMOTE=upstream ./scripts/release-please.sh publish
EOF
}

parse_github_repo_from_remote_url() {
  local remote_url="$1"
  if [[ "$remote_url" =~ github\.com[:/]([^/]+)/([^/.]+)(\.git)?$ ]]; then
    printf '%s/%s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    return 0
  fi
  return 1
}

resolve_repo_url() {
  if [[ -n "${GITHUB_REPOSITORY:-}" ]]; then
    printf '%s' "$GITHUB_REPOSITORY"
    return 0
  fi
  local remote_url=""
  remote_url="$(git remote get-url "$RELEASE_GIT_REMOTE" 2>/dev/null || true)"
  if parse_github_repo_from_remote_url "$remote_url"; then
    return 0
  fi
  echo "Set GITHUB_REPOSITORY=owner/repo or configure RELEASE_GIT_REMOTE (${RELEASE_GIT_REMOTE}) with a github.com URL." >&2
  return 1
}

resolve_github_token() {
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    printf '%s' "$GITHUB_TOKEN"
    return 0
  fi
  if [[ -n "${GH_TOKEN:-}" ]]; then
    printf '%s' "$GH_TOKEN"
    return 0
  fi
  if command -v gh >/dev/null 2>&1; then
    gh auth token 2>/dev/null || true
    return 0
  fi
  return 1
}

read_manifest_version() {
  if [[ ! -f "$MANIFEST_FILE" ]]; then
    echo "Manifest not found: ${MANIFEST_FILE}" >&2
    return 1
  fi
  python3 - "$MANIFEST_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
version = data.get(".")
if not version or not isinstance(version, str):
    raise SystemExit(f"Invalid manifest version in {sys.argv[1]!r}: {version!r}")
print(version.strip())
PY
}

args_contain_dry_run() {
  local arg
  for arg in "$@"; do
    if [[ "$arg" == *dry-run* ]]; then
      return 0
    fi
  done
  return 1
}

sync_container_build_args_to_release_pr() {
  local repo_url="$1"
  shift
  local -a rp_extra_args=("$@")

  if args_contain_dry_run "${rp_extra_args[@]}"; then
    echo "Dry run: skipping container build-args sync on release PR."
    return 0
  fi

  if ! command -v gh >/dev/null 2>&1; then
    echo "Install gh to auto-sync version files onto the release PR (VERSION, _version.py, build-args)." >&2
    return 0
  fi

  local pr_number
  pr_number="$(gh pr list --repo "$repo_url" --state open \
    --json number,title \
    --jq '[.[] | select(.title | test(": release [0-9]"))][0].number // empty')"

  if [[ -z "$pr_number" ]]; then
    echo "No open release PR found; skipping container build-args sync." >&2
    return 0
  fi

  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Working tree has uncommitted changes; commit or stash before release-please syncs version files." >&2
    return 1
  fi

  local start_branch=""
  start_branch="$(git branch --show-current 2>/dev/null || true)"

  echo "Syncing version files on release PR #${pr_number}..."
  gh pr checkout "$pr_number" --repo "$repo_url"

  "${REPO_ROOT}/scripts/sync-container-build-args.sh"

  local -a version_paths=(
    container/pulp-tool-container.build-args
    VERSION
    pulp_tool/_version.py
  )
  if git diff --quiet -- "${version_paths[@]}"; then
    echo "Version files already match manifest on PR #${pr_number}."
  else
    git add "${version_paths[@]}"
    git commit -m "chore(release): sync version files for release"
    git push
    echo "Pushed version file updates to release PR #${pr_number}."
  fi

  if [[ -n "$start_branch" ]]; then
    git checkout "$start_branch"
  fi
}

ensure_release_please_tagged_label() {
  local repo_url="$1"
  gh label create "autorelease: tagged" --repo "$repo_url" \
    --color "0E8A16" --description "Release Please: release completed" 2>/dev/null || true
}

mark_merged_release_pr_tagged() {
  local version="$1"
  local repo_url="$2"

  if ! command -v gh >/dev/null 2>&1; then
    echo "Install gh to mark the merged release PR complete for Release Please." >&2
    exit 1
  fi
  if [[ -z "$(resolve_github_token || true)" ]]; then
    echo "release-publish needs GitHub API access to update autorelease labels." >&2
    echo "Run 'gh auth login' or set GITHUB_TOKEN / GH_TOKEN (issues: write)." >&2
    exit 1
  fi

  ensure_release_please_tagged_label "$repo_url"

  local pr_number=""
  pr_number="$(gh search issues --repo "$repo_url" \
    "is:pr is:merged label:\"autorelease: pending\" \"release ${version}\"" \
    --json number,title \
    --jq '[.[] | select(.title | test(": release [0-9]"))][0].number // empty' 2>/dev/null || true)"

  if [[ -z "$pr_number" ]]; then
    local pending_count="0"
    pending_count="$(gh search issues --repo "$repo_url" \
      'is:pr is:merged label:"autorelease: pending"' \
      --json number --jq 'length' 2>/dev/null || echo "0")"
    if [[ "$pending_count" != "0" ]]; then
      echo "Warning: ${pending_count} merged release PR(s) still have autorelease: pending" \
        "but none matched release ${version} in the title." >&2
      echo "Update labels on the release PR manually, then re-run make release-please." >&2
      exit 1
    fi
    echo "No merged release PR with autorelease: pending (already marked complete)."
    return 0
  fi

  echo "Marking merged release PR #${pr_number} complete for Release Please (v${version})..."
  gh issue edit "$pr_number" --repo "$repo_url" \
    --remove-label "autorelease: pending" \
    --add-label "autorelease: tagged"
}

publish_git_tag() {
  local version tag manifest_version=""

  git fetch "$RELEASE_GIT_REMOTE" "$TARGET_BRANCH"
  git checkout "$TARGET_BRANCH"
  git pull --ff-only "$RELEASE_GIT_REMOTE" "$TARGET_BRANCH"

  if [[ -n "$RELEASE_BUMP" ]]; then
    version="$(bump_version_from_manifest "$RELEASE_BUMP")"
    manifest_version="$(read_manifest_version)" || true
    if [[ -n "$manifest_version" && "$manifest_version" != "$version" ]]; then
      echo "Note: tagging v${version} (BUMP=${RELEASE_BUMP} from manifest ${manifest_version})." >&2
    fi
  else
    # Read manifest after sync — a stale local file before pull caused wrong tags.
    version="$(read_manifest_version)"
  fi
  tag="v${version}"

  if [[ ! "$tag" =~ $semver_tag_pattern ]]; then
    echo "Refusing to tag: manifest version ${version!r} -> ${tag!r} (expected SemVer)" >&2
    exit 1
  fi

  if git rev-parse "refs/tags/${tag}" >/dev/null 2>&1; then
    echo "Tag ${tag} already exists locally." >&2
    exit 1
  fi
  if git ls-remote --exit-code --tags "$RELEASE_GIT_REMOTE" "refs/tags/${tag}" >/dev/null 2>&1; then
    echo "Tag ${tag} already exists on ${RELEASE_GIT_REMOTE}." >&2
    exit 1
  fi

  echo "Tagging ${tag} from ${MANIFEST_FILE} at $(git rev-parse --short HEAD) on ${TARGET_BRANCH} (${RELEASE_GIT_REMOTE})"
  git tag "$tag"
  git push "$RELEASE_GIT_REMOTE" "$tag"
  echo "Pushed ${tag} to ${RELEASE_GIT_REMOTE}. release.yml should start on GitHub Actions."

  local repo_url=""
  repo_url="$(resolve_repo_url)"
  mark_merged_release_pr_tagged "$version" "$repo_url"
}

sync_release_labels_only() {
  local version repo_url
  version="$(read_manifest_version)"
  repo_url="$(resolve_repo_url)"
  mark_merged_release_pr_tagged "$version" "$repo_url"
}

run_release_pr_command() {
  local token repo_url release_as
  local -a rp_cli_args extra_args=("$@")

  token="$(resolve_github_token || true)"
  if [[ -z "$token" ]]; then
    echo "release-pr needs GitHub API access." >&2
    echo "Run 'gh auth login' or set GITHUB_TOKEN / GH_TOKEN (contents + pull-requests write)." >&2
    exit 1
  fi
  repo_url="$(resolve_repo_url)"
  rp_cli_args=(
    release-pr
    --token="$token"
    --repo-url="$repo_url"
    --target-branch="$TARGET_BRANCH"
    --config-file="$CONFIG_FILE"
    --manifest-file="$MANIFEST_FILE"
  )
  if [[ -n "$RELEASE_BUMP" ]]; then
    release_as="$(bump_version_from_manifest "$RELEASE_BUMP")"
    echo "Using release-as=${release_as} (BUMP=${RELEASE_BUMP} from manifest)."
    rp_cli_args+=(--release-as="$release_as")
  fi
  run_release_please "${rp_cli_args[@]}" "${extra_args[@]}"
  sync_container_build_args_to_release_pr "$repo_url" "${extra_args[@]}"
}

run_release_please() {
  if command -v release-please >/dev/null 2>&1; then
    release-please "$@"
    return
  fi
  if ! command -v npx >/dev/null 2>&1; then
    echo "Install Node.js/npm (for npx) or release-please globally: npm i -g release-please" >&2
    exit 1
  fi
  npx --yes "release-please@${RELEASE_PLEASE_VERSION}" "$@"
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

cmd="$1"
shift

extra_args=()
if [[ $# -gt 0 ]]; then
  if [[ "$1" == "--" ]]; then
    shift
  fi
  extra_args=("$@")
fi

case "$cmd" in
  pr|release-pr)
    run_release_pr_command "${extra_args[@]}"
    ;;
  publish|tag)
    publish_git_tag
    ;;
  sync-release-labels|sync-labels)
    sync_release_labels_only
    ;;
  github-release)
    echo "The github-release command is deprecated; use publish (tag + label sync) or sync-release-labels." >&2
    exit 1
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
