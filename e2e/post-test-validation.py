#!/usr/bin/env python3
"""Validate test repositories and distributions in Pulp after e2e tests."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from names import file_repos_for_run, normalize_oci_storage, resolve_run_id, rpm_repos_for_run


def verify_content(config_path: Path, repo_type: str, name: str, expected_content: list[str]) -> bool:
    """Verify that a repository contains expected content.

    Args:
        config_path: Path to Pulp CLI config file
        repo_type: Type of repository ("rpm" or "file")
        name: Name of the repository to verify
        expected_content: List of location_href (rpm) or relative_path (file) values

    Returns:
        True if all expected content is present, False otherwise
    """
    cmd = [
        "pulp",
        "--config",
        str(config_path),
        repo_type,
        "repository",
        "content",
        "list",
        "--repository",
        name,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(
            f"Error: Failed to list content for {repo_type} repository '{name}': {result.stderr}",
            file=sys.stderr,
        )
        return False

    try:
        content_list = json.loads(result.stdout)

        if not isinstance(content_list, list):
            print(
                f"Error: Unexpected response format for repository '{name}'",
                file=sys.stderr,
            )
            return False

        content_key = "relative_path" if repo_type == "file" else "location_href"

        content_values = {
            item.get(content_key) for item in content_list if isinstance(item, dict) and content_key in item
        }

        expected_set = set(expected_content)
        missing = [value for value in expected_content if value not in content_values]
        extra = [value for value in content_values if value not in expected_set]

        if missing:
            print(
                f"Error: Repository '{name}' missing expected content: {missing}",
                file=sys.stderr,
            )
            print(
                f"Found {content_key} values: {content_values}",
                file=sys.stderr,
            )
            return False

        if extra:
            print(
                f"Error: Repository '{name}' contains unexpected content: {extra}",
                file=sys.stderr,
            )
            print(
                f"Expected {content_key} values: {expected_set}",
                file=sys.stderr,
            )
            return False

        print(f"✓ Repository '{name}' contains all expected content (no extra content)")
        return True

    except json.JSONDecodeError as e:
        print(
            f"Error: Failed to parse JSON response for repository '{name}': {e}",
            file=sys.stderr,
        )
        return False


def verify_repos(config_path: Path, run_id: str | None, oci_storage: str | None) -> int:
    """Verify all test repositories contain expected content.

    Args:
        config_path: Path to Pulp CLI config file
        run_id: Optional run suffix used during test execution

    Returns:
        Exit code (0 for success, 1 if any failures occurred)
    """
    rpm_repos = rpm_repos_for_run(run_id, oci_storage)
    file_repos = file_repos_for_run(run_id, oci_storage)

    if run_id:
        print(f"=== Verifying repository content (run id: {run_id}) ===\n")
    else:
        print("=== Verifying repository content ===\n")

    failures = 0

    for repo_name, expected_content in rpm_repos.items():
        if not verify_content(config_path, "rpm", repo_name, expected_content):
            failures += 1

    for repo_name, expected_content in file_repos.items():
        if not verify_content(config_path, "file", repo_name, expected_content):
            failures += 1

    total_repos = len(rpm_repos) + len(file_repos)
    verified = total_repos - failures

    print(f"\n=== Verification complete: {verified}/{total_repos} repositories verified ===")

    return 1 if failures > 0 else 0


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate test repositories in Pulp",
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
    return verify_repos(config_path, run_id, oci_storage or None)


if __name__ == "__main__":
    sys.exit(main())
