#!/usr/bin/env python3
"""Clean up test repositories and distributions in Pulp after e2e tests."""

import argparse
import subprocess
import sys
from pathlib import Path

from names import file_repo_names_for_cleanup, normalize_oci_storage, resolve_run_id, rpm_repo_names_for_cleanup


def destroy_resource(config_path: Path, repo_type: str, resource: str, name: str, dry_run: bool = False) -> bool:
    """Destroy a Pulp repository or distribution.

    Args:
        config_path: Path to Pulp CLI config file
        repo_type: Type of repository ("rpm" or "file")
        resource: Resource type ("repository" or "distribution")
        name: Name of the resource to destroy
        dry_run: If True, only print what would be destroyed without executing

    Returns:
        True if successful (or if dry-run), False otherwise
    """
    cmd = [
        "pulp",
        "--config",
        str(config_path),
        repo_type,
        resource,
        "destroy",
        "--name",
        name,
    ]

    if dry_run:
        print(f"[DRY RUN] Would destroy {repo_type} {resource}: {name}")
        return True

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(
            f"Warning: Failed to destroy {repo_type} {resource} '{name}': {result.stderr}",
            file=sys.stderr,
        )
        return False
    return True


def cleanup_repos(config_path: Path, run_id: str | None, oci_storage: str | None, dry_run: bool = False) -> int:
    """Clean up all test repositories and distributions.

    Args:
        config_path: Path to Pulp CLI config file
        run_id: Optional run suffix used during test execution
        dry_run: If True, only show what would be destroyed without executing

    Returns:
        Exit code (0 for success, 1 if any failures occurred)
    """
    rpm_repos = rpm_repo_names_for_cleanup(run_id, oci_storage)
    file_repos = file_repo_names_for_cleanup(run_id, oci_storage)

    if dry_run:
        print("=== DRY RUN MODE: No resources will be destroyed ===\n")
    elif run_id:
        print(f"=== Cleaning up test resources (run id: {run_id}) ===\n")
    else:
        print("=== Cleaning up test resources ===\n")

    total_resources = (len(rpm_repos) + len(file_repos)) * 2  # repos + distributions
    current = 0
    failures = 0

    if not dry_run:
        for repo in rpm_repos:
            current += 1
            print(f"[{current}/{total_resources}] Destroying rpm repository: {repo}")
            if not destroy_resource(config_path, "rpm", "repository", repo, dry_run):
                failures += 1

            current += 1
            print(f"[{current}/{total_resources}] Destroying rpm distribution: {repo}")
            if not destroy_resource(config_path, "rpm", "distribution", repo, dry_run):
                failures += 1

        for repo in file_repos:
            current += 1
            print(f"[{current}/{total_resources}] Destroying file repository: {repo}")
            if not destroy_resource(config_path, "file", "repository", repo, dry_run):
                failures += 1

            current += 1
            print(f"[{current}/{total_resources}] Destroying file distribution: {repo}")
            if not destroy_resource(config_path, "file", "distribution", repo, dry_run):
                failures += 1

        # Cleanup abandoned packages and files
        print("Cleaning up orphaned content.")
        cmd = ["pulp", "--config", str(config_path), "orphan", "cleanup"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(
                f"Warning: Failed to cleanup orphaned content: {result.stderr}",
                file=sys.stderr,
            )
            failures += 1

    if dry_run:
        print(f"\n=== DRY RUN COMPLETE: {total_resources} resources would be destroyed ===")
    else:
        success = total_resources - failures
        print(f"\n=== Cleanup complete: {success}/{total_resources} resources destroyed successfully ===")

    return 1 if failures > 0 else 0


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Clean up test repositories in Pulp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to Pulp CLI config file (cli.toml)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run suffix used during e2e tests (default: E2E_RUN_ID env var)",
    )
    parser.add_argument(
        "--oci-storage",
        default=None,
        help="OCI registry for ORAS e2e (must match test-pulp-tool.py; Konflux ociStorage)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be destroyed without actually destroying anything",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    if not args.config.exists():
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        return 1

    config_path = args.config.resolve()
    run_id = resolve_run_id(args.run_id)
    oci_storage = normalize_oci_storage(args.oci_storage)
    return cleanup_repos(config_path, run_id, oci_storage or None, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
