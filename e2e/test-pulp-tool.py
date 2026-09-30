#!/usr/bin/env python3
"""
End-to-end test suite for pulp-tool CLI
Tests all commands, global options, and error scenarios
"""

import argparse
import hashlib
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Dict, List

from distribution_fetch import (
    DistributionFetchError,
    distribution_client_from_config,
    distribution_fetch_retry_policy_summary,
    fetch_and_verify_sha256,
    fetch_bytes,
    fetch_pulp_results_json,
    format_fetch_check_summary,
    format_pulp_results_for_diagnostics,
    normalize_sha256_hex,
    probe_http_get_status,
)
from distribution_verify_queue import DistributionCheckRunner, DistributionVerifyQueue
from large_upload import (
    LARGE_RPM_ARCH,
    LARGE_RPM_FILENAME,
    LARGE_RPM_PACKAGE,
    LARGE_RPM_RELEASE,
    LARGE_RPM_VERSION,
    LARGE_UPLOAD_MIN_SIZE_BYTES,
)
from names import (
    BASE_PATH_CREATE_REPOSITORY,
    BASE_PATH_CREATE_REPOSITORY_JSON,
    BASE_PATH_E2E_ERROR_DUP,
    BUILD_ID_E2E_ERROR_EMPTY,
    BUILD_ID_PULL_SIDE_TAG,
    BUILD_ID_PULL_SIDE_TAG_OCI,
    BUILD_ID_UPDATE_BUILD,
    BUILD_ID_UPDATE_BUILD_PULL,
    BUILD_ID_UPDATE_BUILD_REPLACED,
    BUILD_ID_UPLOAD_FILES,
    BUILD_ID_UPLOAD_FULL,
    BUILD_ID_UPLOAD_LARGE,
    BUILD_ID_UPLOAD_MINIMAL,
    BUILD_ID_UPLOAD_ORAS,
    BUILD_ID_UPLOAD_RESULTS,
    BUILD_ID_UPLOAD_TARGET_ARCH,
    REPO_CREATE_REPOSITORY,
    REPO_CREATE_REPOSITORY_JSON,
    REPO_E2E_ERROR_DUP,
    e2e_error_upload_repo_names,
    normalize_oci_storage,
    resolve_run_id,
    scoped_base_path,
    scoped_build_id,
    scoped_oci_storage,
    side_tag_e2e_name,
)
from rpm_variant import TEST2_NOARCH_RPM_NAME, build_test2_noarch_rpm


# ANSI color codes
class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"  # No Color


class TestStats:
    """Track test execution statistics"""

    def __init__(self):
        self.run = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0


class E2ETestSuite:
    """End-to-end test suite for pulp-tool CLI"""

    def __init__(
        self,
        config_file: Path,
        rpm_dir: Path,
        pulp_results: Path,
        test_dir: Path = None,
        skip_setup: bool = False,
        real_server: bool = False,
        dry_run: bool = True,
        run_id: str | None = None,
        oci_storage: str | None = None,
        skip_distribution_verify: bool = False,
    ):
        self.config_file = config_file
        self.rpm_dir_arg = rpm_dir
        self.pulp_results = pulp_results
        self.test_dir_arg = test_dir
        self.skip_setup = skip_setup
        self.real_server = real_server
        self.dry_run = dry_run
        self.run_id = resolve_run_id(run_id)
        self.oci_storage = normalize_oci_storage(oci_storage)
        self.stats = TestStats()
        self.rpm_dirs: Dict[int, Path] = {}
        self.current_rpm_index = 0
        self._test_case_index = 0
        self._current_case_id: str | None = None
        self.last_oci_pulp_results_ref: str | None = None
        self.last_oci_build_id: str | None = None
        self.skip_distribution_verify = skip_distribution_verify
        self.distribution_verify_queue = DistributionVerifyQueue()
        self._side_tag_source_pulp_results_url: str | None = None
        self._side_tag_oci_ref: str | None = None
        self._side_tag_oci_build_id: str | None = None

        with open(self.config_file, "rb") as f:
            config = tomllib.load(f)

        self.base_url = config["cli"]["base_url"]
        self.namespace = config["cli"]["domain"]

    def bid(self, base_build_id: str) -> str:
        """Return build id scoped to this e2e run when isolating concurrent executions."""
        return scoped_build_id(base_build_id, self.run_id)

    def bpath(self, base_path: str) -> str:
        """Return distribution base_path scoped to this e2e run when isolating concurrent executions."""
        return scoped_base_path(base_path, self.run_id)

    def log_info(self, message: str):
        """Log informational message"""
        prefix = f"[{self._current_case_id}] " if self._current_case_id else ""
        print(f"{Colors.BLUE}[INFO]{Colors.NC} {prefix}{message}")

    def log_success(self, message: str):
        """Log success message"""
        print(f"{Colors.GREEN}[PASS]{Colors.NC} {message}")

    def log_error(self, message: str):
        """Log error message"""
        print(f"{Colors.RED}[FAIL]{Colors.NC} {message}")

    def log_warn(self, message: str):
        """Log warning message"""
        print(f"{Colors.YELLOW}[WARN]{Colors.NC} {message}")

    def log_skip(self, message: str):
        """Log skip message"""
        print(f"{Colors.YELLOW}[SKIP]{Colors.NC} {message}")

    def run_command(self, cmd: List[str], cwd: Path = None, check: bool = False) -> tuple[int, str]:
        """
        Run a command and return exit code and output

        Args:
            cmd: Command and arguments as list
            check: If True, raise exception on non-zero exit

        Returns:
            Tuple of (exit_code, combined_output)
        """
        cmd_line = shlex.join(cmd)
        if len(cmd_line) > 600:
            cmd_line = f"{cmd_line[:600]}… (truncated)"
        cwd_label = f" cwd={cwd}" if cwd else ""
        self.log_info(f"$ {cmd_line}{cwd_label}")
        started = time.monotonic()
        try:
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)
            output = result.stdout + result.stderr
            elapsed_ms = (time.monotonic() - started) * 1000
            self.log_info(f"exit={result.returncode} elapsed_ms={elapsed_ms:.0f}")
            return result.returncode, output
        except subprocess.CalledProcessError as e:
            output = e.stdout + e.stderr
            elapsed_ms = (time.monotonic() - started) * 1000
            self.log_info(f"exit={e.returncode} elapsed_ms={elapsed_ms:.0f} (CalledProcessError)")
            return e.returncode, output
        except Exception as e:
            elapsed_ms = (time.monotonic() - started) * 1000
            self.log_info(f"exit=1 elapsed_ms={elapsed_ms:.0f} (exception: {e})")
            return 1, str(e)

    def assert_exit_code(self, expected: int, actual: int, test_name: str) -> bool:
        """Assert exit code matches expected"""
        if actual == expected:
            self.log_success(f"{test_name} (exit code: {actual})")
            self.stats.passed += 1
            return True
        else:
            self.log_error(f"{test_name} (expected exit code: {expected}, got: {actual})")
            self.stats.failed += 1
            return False

    def expect_cli_failure(
        self,
        test_label: str,
        cmd: List[str],
        *,
        substring: str | None = None,
        cwd: Path | None = None,
    ) -> bool:
        """Assert a CLI invocation exits non-zero; optionally require ``substring`` in combined output."""
        self.run_test(test_label)
        exit_code, output = self.run_command(cmd, cwd=cwd)
        if exit_code == 0:
            self.log_error(f"{test_label}: expected non-zero exit, got 0")
            if output:
                self.log_error(output[:800])
            self.stats.failed += 1
            return False
        if substring is not None and substring not in output:
            self.log_error(f"{test_label}: output missing expected text: {substring!r}")
            if output:
                self.log_error(output[:800])
            self.stats.failed += 1
            return False
        self.log_success(f"{test_label} (exit code: {exit_code})")
        self.stats.passed += 1
        return True

    def _destroy_pulp_rpm_repo(self, name: str) -> None:
        """Best-effort destroy of an RPM repository and its distribution (error-test cleanup)."""
        for resource in ("repository", "distribution"):
            subprocess.run(
                [
                    "pulp",
                    "--config",
                    str(self.config_file),
                    "rpm",
                    resource,
                    "destroy",
                    "--name",
                    name,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def _destroy_pulp_file_repo(self, name: str) -> None:
        """Best-effort destroy of a file repository and its distribution (error-test cleanup)."""
        for resource in ("repository", "distribution"):
            subprocess.run(
                [
                    "pulp",
                    "--config",
                    str(self.config_file),
                    "file",
                    resource,
                    "destroy",
                    "--name",
                    name,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def _cleanup_e2e_error_upload_repos(self, build_id: str) -> None:
        for repo_name in e2e_error_upload_repo_names(build_id):
            if repo_name.endswith("/rpms"):
                self._destroy_pulp_rpm_repo(repo_name)
            else:
                self._destroy_pulp_file_repo(repo_name)

    def _write_transfer_dest_config_no_oci(self) -> Path:
        """Transfer-dest config with credentials but without ``oci_storage`` (side-tag validation)."""
        path = self.test_dir / "transfer-cli-no-oci.toml"
        lines_out: list[str] = []
        in_cli = False
        for line in self.config_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "[cli]":
                in_cli = True
                lines_out.append(line)
                continue
            if in_cli and stripped.startswith("[") and stripped != "[cli]":
                in_cli = False
            if in_cli and stripped.startswith("oci_storage"):
                continue
            lines_out.append(line)
        if "[cli]" not in "\n".join(lines_out):
            lines_out = ["[cli]", *lines_out]
        cluster_line = 'cluster = "e2e-cluster"'
        if cluster_line not in lines_out:
            idx = next(i for i, line in enumerate(lines_out) if line.strip() == "[cli]")
            lines_out.insert(idx + 1, cluster_line)
        path.write_text("\n".join(lines_out).rstrip() + "\n", encoding="utf-8")
        return path

    def _write_minimal_pull_auth_config(self) -> Path:
        """``cli.toml`` with ``base_url`` only (no distribution credentials)."""
        path = self.test_dir / "pull-auth-none.toml"
        path.write_text(
            f'[cli]\nbase_url = "{self.base_url}"\n',
            encoding="utf-8",
        )
        return path

    def assert_output_contains(self, output: str, expected: str, test_name: str) -> bool:
        """Assert output contains expected string"""
        if expected in output:
            self.log_success(f"{test_name} (output contains: '{expected}')")
            self.stats.passed += 1
            return True
        else:
            self.log_error(f"{test_name} (output missing: '{expected}')")
            print(f"Actual output: {output[:500]}")
            self.stats.failed += 1
            return False

    def assert_search_by_package(
        self,
        output: str,
        *,
        name: str,
        version: str,
        release: str,
        arch: str,
        checksum: str | None = None,
        test_name: str,
    ) -> bool:
        """Assert search-by JSON output includes a package with the given NVRA (and optional checksum)."""
        try:
            packages = json.loads(output)
        except json.JSONDecodeError:
            self.log_error(f"{test_name} (output is not valid JSON)")
            print(f"Actual output: {output[:500]}")
            self.stats.failed += 1
            return False

        if not isinstance(packages, list):
            self.log_error(f"{test_name} (expected JSON array)")
            print(f"Actual output: {output[:500]}")
            self.stats.failed += 1
            return False

        for pkg in packages:
            if not isinstance(pkg, dict):
                continue
            if (
                pkg.get("name") == name
                and pkg.get("version") == version
                and pkg.get("release") == release
                and pkg.get("arch") == arch
            ):
                if checksum and pkg.get("pkgId", "").lower() != checksum.lower():
                    continue
                nvra = f"{name}-{version}-{release}.{arch}"
                self.log_success(f"{test_name} (found {nvra})")
                self.stats.passed += 1
                return True

        self.log_error(f"{test_name} (no matching package in search-by JSON)")
        print(f"Actual output: {output[:500]}")
        self.stats.failed += 1
        return False

    def assert_file_exists(self, filepath: Path, test_name: str) -> bool:
        """Assert file exists"""
        if filepath.exists():
            self.log_success(f"{test_name} (file exists: {filepath})")
            self.stats.passed += 1
            return True
        else:
            self.log_error(f"{test_name} (file not found: {filepath})")
            self.stats.failed += 1
            return False

    def log_distribution_fetch_diagnostics(
        self,
        pulp_results_content: dict,
        *,
        pulp_results_url: str,
        pulp_results_digest: str,
        sbom_url: str,
        failed_check: str | None = None,
        failed_url: str | None = None,
        failed_expected_sha256: str | None = None,
        failed_artifact_entry: dict | None = None,
        upload_output: str | None = None,
    ) -> None:
        """Print pulp_results.json and related context when distribution fetch checks fail."""
        self.log_error("--- distribution fetch diagnostics ---")
        if failed_check:
            self.log_error(f"failed check: {failed_check}")
        if failed_url:
            self.log_error(f"failed url: {failed_url}")
        if failed_expected_sha256:
            self.log_error(f"failed expected_sha256: {normalize_sha256_hex(failed_expected_sha256)}")
        if failed_artifact_entry is not None:
            self.log_error("failed artifact entry:\n" + json.dumps(failed_artifact_entry, indent=2, sort_keys=True))
        self.log_error(f"konflux pulp_results URL file: {pulp_results_url}")
        self.log_error(f"konflux pulp_results digest file: {pulp_results_digest}")
        self.log_error(f"sbom results URL: {sbom_url}")
        self.log_error(f"namespace: {self.namespace}")
        self.log_error(f"base_url: {self.base_url}")
        if upload_output:
            preview = upload_output if len(upload_output) <= 4000 else f"{upload_output[:4000]}… (truncated)"
            self.log_error(f"upload command output:\n{preview}")
        self.log_error("pulp_results.json:")
        print(format_pulp_results_for_diagnostics(pulp_results_content))
        self.log_error("--- end distribution fetch diagnostics ---")

    def verify_distribution_downloads(
        self,
        client,
        pulp_results_content: dict,
        sbom_url: str,
        pulp_results_url: str,
        pulp_results_digest: str,
    ) -> None:
        """HTTP GET distribution URLs and verify SHA256 against pulp_results metadata."""
        rpm_key = "test.1-1.0.0-1.x86_64.rpm"
        sbom_key = next(
            (
                key
                for key in pulp_results_content.get("artifacts", {})
                if key.endswith("/sbom.json") or key == "sbom.json"
            ),
            None,
        )
        checks: list[tuple[str, str, str, dict | None]] = [
            (
                "RPM (x86_64)",
                pulp_results_content["artifacts"][rpm_key]["url"],
                pulp_results_content["artifacts"][rpm_key]["sha256"],
                pulp_results_content["artifacts"][rpm_key],
            ),
            (
                "SBOM",
                sbom_url,
                pulp_results_content["artifacts"][sbom_key]["sha256"],
                pulp_results_content["artifacts"].get(sbom_key),
            ),
            (
                "pulp_results.json",
                pulp_results_url,
                normalize_sha256_hex(pulp_results_digest),
                None,
            ),
        ]
        diagnostics_logged = False
        self.log_info("Starting distribution URL fetch verification (RPM, SBOM, pulp_results.json)")
        for label, url, expected_sha256, artifact_entry in checks:
            self.log_info(f"Distribution fetch check: {label}")
            self.log_info(f"  URL: {url}")
            self.log_info(f"  expected SHA256: {normalize_sha256_hex(expected_sha256)}")
            try:
                fetch_and_verify_sha256(client, url, expected_sha256, label=label)
                self.stats.passed += 1
                self.log_success(f"Distribution fetch verified: {label}")
            except DistributionFetchError as exc:
                self.stats.failed += 1
                self.log_error(str(exc))
                if not diagnostics_logged:
                    self.log_distribution_fetch_diagnostics(
                        pulp_results_content,
                        pulp_results_url=pulp_results_url,
                        pulp_results_digest=pulp_results_file_digest,
                        sbom_url=sbom_url,
                        failed_check=label,
                        failed_url=url,
                        failed_expected_sha256=expected_sha256,
                        failed_artifact_entry=artifact_entry,
                    )
                    self.log_error(
                        format_fetch_check_summary(label, url, expected_sha256, artifact_entry=artifact_entry)
                    )
                    diagnostics_logged = True

    def defer_distribution_check(
        self,
        label: str,
        run: DistributionCheckRunner,
        *,
        build_id: str | None = None,
    ) -> None:
        """Queue a pulp-content HTTP check to run after all uploads complete."""
        if not self.real_server or self.skip_distribution_verify:
            return
        self.distribution_verify_queue.defer_callable(label, run, build_id=build_id)

    def run_distribution_verification_phase(self) -> None:
        """Run deferred pulp-content verifications (after upload phase)."""
        if not self.real_server or self.skip_distribution_verify:
            return
        pending = self.distribution_verify_queue.pending()
        if not pending:
            return

        self.begin_section(
            "Distribution URL verification (pulp-content)",
            description="HTTP GET artifact URLs after all uploads; uses distribution_fetch retry policy.",
        )
        self.log_info(f"Distribution fetch retry policy: {distribution_fetch_retry_policy_summary()}")
        self.log_info(f"Running {len(pending)} deferred distribution check(s)")
        for check in pending:
            self.run_test(f"distribution verify: {check.label}", detail=check.build_id or "")
            check.run(self)

    def begin_section(self, title: str, *, description: str = "") -> None:
        """Print a visible boundary between groups of related test cases."""
        print()
        print("#" * 70)
        print(f"  SECTION: {title}")
        if description:
            print(f"  {description}")
        print("#" * 70)

    def invoke_test_case(
        self,
        method: Callable[[], None],
        case_id: str,
        description: str,
        *,
        requires_real_server: bool = False,
    ) -> None:
        """Run one test method with a numbered header, context, and completion summary."""
        self._test_case_index += 1
        self._current_case_id = case_id
        before = (self.stats.passed, self.stats.failed, self.stats.skipped)
        started = time.monotonic()

        print()
        print("=" * 70)
        print(f"  TEST [{self._test_case_index:02d}] {case_id}")
        print(f"  {description}")
        if requires_real_server:
            if self.real_server:
                print(f"  {Colors.BLUE}Mode: live Pulp (--real-server){Colors.NC}")
            else:
                print(f"  {Colors.YELLOW}Mode: dry-run (Pulp mutations skipped inside this case){Colors.NC}")
        print("=" * 70)

        method()

        elapsed_s = time.monotonic() - started
        delta_passed = self.stats.passed - before[0]
        delta_failed = self.stats.failed - before[1]
        delta_skipped = self.stats.skipped - before[2]
        if delta_failed:
            outcome = f"{Colors.RED}FAILED{Colors.NC}"
        elif delta_skipped and delta_passed == 0:
            outcome = f"{Colors.YELLOW}SKIPPED{Colors.NC}"
        else:
            outcome = f"{Colors.GREEN}OK{Colors.NC}"

        print(
            f"{Colors.BLUE}[INFO]{Colors.NC} [{case_id}] finished in {elapsed_s:.1f}s "
            f"— {outcome} (+{delta_passed} pass, +{delta_failed} fail, +{delta_skipped} skip)"
        )
        print("-" * 70)
        self._current_case_id = None

    def run_test(self, step_name: str, *, detail: str | None = None) -> None:
        """Mark start of a step within the current test case."""
        self.stats.run += 1
        message = f"step: {step_name}"
        if detail:
            message = f"{message} — {detail}"
        self.log_info(message)

    def skip_test(self, test_name: str, reason: str) -> None:
        """Mark test as skipped"""
        self.stats.run += 1
        self.stats.skipped += 1
        case = f"[{self._current_case_id}] " if self._current_case_id else ""
        self.log_skip(f"{case}{test_name} — {reason}")

    def setup_test_env(self):
        """Setup test environment with temporary files and directories"""
        if self.test_dir_arg is not None:
            self.test_dir = self.test_dir_arg
        else:
            self.test_dir = Path(tempfile.mkdtemp())

        self.log_info(f"Setting up test environment in {self.test_dir}")
        self.log_info(f"Using config file: {self.config_file}")

        # Validate config file is readable
        if not self.config_file.is_file() or not os.access(self.config_file, os.R_OK):
            self.log_error(f"Config file is not readable: {self.config_file}")
            sys.exit(1)

        # Setup RPM directories - validate numbered subdirectories exist
        # Expected structure: rpm_dir/0/, rpm_dir/1/, rpm_dir/2/, etc.
        self.rpm_dir = self.rpm_dir_arg
        self.log_info(f"Using RPM base directory: {self.rpm_dir}")

        if not os.access(self.rpm_dir, os.R_OK):
            self.log_error(f"RPM directory is not readable: {self.rpm_dir}")
            sys.exit(1)

        # Discover and validate numbered subdirectories
        # We need at least 5 directories (0-4) for the upload tests
        required_dirs = 5
        for i in range(required_dirs):
            rpm_subdir = self.rpm_dir / str(i)
            if not rpm_subdir.is_dir():
                self.log_error(f"Required RPM subdirectory not found: {rpm_subdir}")
                self.log_error(f"Expected numbered subdirectories: 0/ through {required_dirs - 1}/")
                sys.exit(1)

            if not os.access(rpm_subdir, os.R_OK):
                self.log_error(f"RPM subdirectory not readable: {rpm_subdir}")
                sys.exit(1)

            self.rpm_dirs[i] = rpm_subdir

            # Count RPM files in this directory
            rpm_count = len(list(rpm_subdir.rglob("*.rpm")))
            self.log_info(f"Found {rpm_count} RPM file(s) in {rpm_subdir}")

        self.log_success(f"Validated {required_dirs} numbered RPM directories (0-{required_dirs - 1})")

        # Create test log files
        self.log_dir = self.test_dir / "logs"
        for arch in ["x86_64", "aarch64"]:
            arch_log_dir = self.log_dir / arch
            arch_log_dir.mkdir(parents=True)
            (arch_log_dir / "build.log").write_text(f"build log content for {arch}\n")
            (arch_log_dir / "root.log").write_text(f"root log content for {arch}\n")

        # Create test SBOM file
        self.sbom_file = self.test_dir / "sbom.json"
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.4",
            "version": 1,
            "metadata": {"timestamp": "2026-05-20T00:00:00Z"},
            "components": [],
        }
        self.sbom_file.write_text(json.dumps(sbom_data, indent=2))

        self.test_file = self.test_dir / "test.md"
        self.test_file.write_text("# test arbitrary file\n")

        self.upload_results_json = self.test_dir / "upload_pulp_results.json"
        rpm_file = list((self.rpm_dirs[2] / "noarch").rglob("*.rpm"))[0]
        with open(rpm_file, "rb") as f:
            digest = hashlib.file_digest(f, "sha256")
        upload_build_id = self.bid(BUILD_ID_UPLOAD_RESULTS)
        upload_results_data = {
            "artifacts": {
                "test.2-1.0.0-1.noarch.rpm": {
                    "pulp_labels": {
                        "date": "2026-06-03 13:31:09",
                        "build_id": upload_build_id,
                        "arch": "noarch",
                        "namespace": self.namespace,
                    },
                    "url": "test.2-1.0.0-1.noarch.rpm",
                    "sha256": str(digest.hexdigest()),
                }
            },
            "distributions": {"rpms": f"{self.base_url}/api/pulp-content/{self.namespace}/{upload_build_id}/rpms/"},
        }
        self.upload_results_json.write_text(json.dumps(upload_results_data, indent=2))

        # Create output directories
        self.output_dir = self.test_dir / "output"
        self.output_dir.mkdir(parents=True)

        self.log_success("Test environment setup complete")

    def cleanup_test_env(self):
        """Clean up test environment"""
        if self.test_dir and self.test_dir.exists():
            self.log_info(f"Cleaning up test environment: {self.test_dir}")
            shutil.rmtree(self.test_dir)

    # Test: pulp-tool version/help
    def test_help_commands(self):
        self.run_test("pulp-tool --help")
        exit_code, output = self.run_command(["pulp-tool", "--help"])
        self.assert_output_contains(output, "Usage:", "Help shows usage")

        self.run_test("pulp-tool --version")
        exit_code, output = self.run_command(["pulp-tool", "--version"])
        if exit_code == 0 or "version" in output.lower() or "pulp-tool" in output.lower():
            self.log_success("Version command works or shows tool name")
            self.stats.passed += 1
        else:
            self.log_warn("Version command not available (may be expected)")
            self.stats.skipped += 1

    # Test: upload command help
    def test_upload_help(self):
        self.run_test("pulp-tool upload --help")
        exit_code, output = self.run_command(["pulp-tool", "upload", "--help"])
        self.assert_exit_code(0, exit_code, "Upload help command")
        if exit_code > 0:
            self.log_error(output)
        self.assert_output_contains(output, "--rpm-path", "Help shows --rpm-path option")
        self.assert_output_contains(output, "--sbom-path", "Help shows --sbom-path option")

    def test_upload_build_help(self):
        self.run_test("pulp-tool upload-build --help")
        exit_code, output = self.run_command(["pulp-tool", "upload-build", "--help"])
        self.assert_exit_code(0, exit_code, "Upload-build help command")
        if exit_code > 0:
            self.log_error(output)
        self.assert_output_contains(output, "--rpm-path", "Upload-build help shows --rpm-path option")
        self.assert_output_contains(output, "--oci-storage", "Upload-build help shows --oci-storage option")

    # Test: upload-files command help
    def test_upload_files_help(self):
        self.run_test("pulp-tool upload-files --help")
        exit_code, output = self.run_command(["pulp-tool", "upload-files", "--help"])
        self.assert_exit_code(0, exit_code, "Upload-files help command")
        if exit_code > 0:
            self.log_error(output)
        self.assert_output_contains(output, "--rpm", "Help shows --rpm option")
        self.assert_output_contains(output, "--file", "Help shows --file option")
        self.assert_output_contains(output, "--log", "Help shows --log option")

    # Test: pull command help
    def test_pull_help(self):
        self.run_test("pulp-tool pull --help")
        exit_code, output = self.run_command(["pulp-tool", "pull", "--help"])
        self.assert_exit_code(0, exit_code, "Pull help command")
        if exit_code > 0:
            self.log_error(output)
        self.assert_output_contains(output, "--artifact-location", "Help shows --artifact-location option")
        self.assert_output_contains(output, "--content-types", "Help shows --content-types option")
        self.assert_output_contains(output, "--side-tag", "Help shows --side-tag option")
        self.assert_output_contains(output, "--artifact-results", "Help shows --artifact-results option")
        self.assert_output_contains(output, "--snapshot-path", "Help shows --snapshot-path option")
        self.assert_output_contains(output, "--oci-storage", "Help shows --oci-storage option")

    def _oci_oras_prereqs(self, test_name: str) -> str | None:
        """Return ``--oci-storage`` when ORAS e2e prerequisites are met; else skip."""
        if not self.real_server:
            self.skip_test(test_name, "DRY RUN")
            return None
        oci_storage = self.oci_storage
        if not oci_storage:
            self.skip_test(test_name, "--oci-storage not set")
            return None
        if shutil.which("oras") is None:
            self.skip_test(test_name, "oras CLI not in PATH")
            return None
        if shutil.which("select-oci-auth") is None:
            self.skip_test(test_name, "select-oci-auth not in PATH (needed for ORAS registry auth)")
            return None
        if shutil.which("get-reference-base") is None:
            self.skip_test(test_name, "get-reference-base not in PATH (required by select-oci-auth)")
            return None
        if shutil.which("yq") is None:
            self.skip_test(test_name, "yq not in PATH (required by select-oci-auth)")
            return None
        return oci_storage

    def side_tag_name_for_run(self) -> str:
        """Run-scoped ``--side-tag`` value (avoids Pulp distribution collisions across e2e runs)."""
        return side_tag_e2e_name(self.run_id)

    def _write_transfer_dest_config(self) -> Path:
        """Copy ``cli.toml`` for ``pull --transfer-dest`` (destination credentials + cluster label)."""
        path = self.test_dir / "transfer-cli.toml"
        base = self.config_file.read_text(encoding="utf-8")
        cluster_line = 'cluster = "e2e-cluster"'
        if "[cli]" in base:
            lines = base.splitlines()
            out: list[str] = []
            inserted = False
            for line in lines:
                out.append(line)
                if line.strip() == "[cli]" and not inserted:
                    out.append(cluster_line)
                    inserted = True
            if not inserted:
                out.append(cluster_line)
            path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
        else:
            path.write_text(f"[cli]\n{cluster_line}\n{base}", encoding="utf-8")
        return path

    def _oras_registry_config_file(self, oci_ref: str) -> Path:
        """Write Konflux-style registry config for ``oci_ref`` (import-to-quay pattern)."""
        auth_path = self.test_dir / "oras-registry-config.json"
        result = subprocess.run(
            ["select-oci-auth", oci_ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"select-oci-auth failed (exit {result.returncode}): {result.stderr or result.stdout or ''}"
            )
        auth_path.write_text(result.stdout or "", encoding="utf-8")
        return auth_path

    def _fetch_pulp_results_json_from_oci(self, oci_ref: str, dest_dir: Path) -> Path:
        """ORAS-pull ``pulp_results.json`` blob (update-build style OCI artifact input)."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        for existing in dest_dir.iterdir():
            if existing.is_file():
                existing.unlink()
        registry_config = self._oras_registry_config_file(oci_ref)
        result = subprocess.run(
            [
                "oras",
                "--registry-config",
                str(registry_config),
                "pull",
                oci_ref,
                "-o",
                str(dest_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"oras pull failed (exit {result.returncode}): {result.stderr or result.stdout or ''}"
            )
        json_files = sorted(dest_dir.glob("*.json"))
        if not json_files:
            raise RuntimeError(f"No .json file under {dest_dir} after oras pull of {oci_ref}")
        return json_files[0]

    def _oci_ref_from_konflux_results(self, image_url_path: Path, image_digest_path: Path) -> str:
        """Build ``repo@sha256:…`` from Tekton-style OCI result files."""
        url = image_url_path.read_text(encoding="utf-8").strip()
        digest = image_digest_path.read_text(encoding="utf-8").strip()
        if not digest.startswith("sha256:"):
            digest = f"sha256:{digest}"
        return f"{url}@{digest}"

    def _run_upload_build_oras(
        self,
        oci_storage: str,
        build_id: str,
        rpm_dir: Path,
        *,
        image_url_path: Path,
        image_digest_path: Path,
    ) -> str:
        """Run ``upload-build`` with ORAS publish; return OCI ref from Tekton ``--artifact-results`` files."""
        storage = scoped_oci_storage(oci_storage, build_id, self.run_id)
        upload_cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "--build-id",
            build_id,
            "--namespace",
            self.namespace,
            "upload-build",
            "--rpm-path",
            str(rpm_dir),
            "--oci-storage",
            storage,
            "--artifact-results",
            f"{image_url_path},{image_digest_path}",
        ]
        exit_code, output = self.run_command(upload_cmd)
        if not self.assert_exit_code(0, exit_code, "upload-build with ORAS completes successfully"):
            self.log_error(output)
            if "unauthorized" in output.lower() and "oras" in output.lower():
                self.log_error(
                    "ORAS registry push was rejected (not a Pulp API error). On Konflux, link a "
                    "dockerconfigjson secret with push access to the ociStorage repo to the e2e "
                    "PipelineRun service account; see e2e/README.md (ORAS registry auth)."
                )
            raise RuntimeError("upload-build ORAS failed")
        return self._oci_ref_from_konflux_results(image_url_path, image_digest_path)

    def _assert_konflux_oci_results_match_manifest(
        self,
        oci_manifest: str,
        image_url_path: Path,
        image_digest_path: Path,
        *,
        test_label: str,
    ) -> bool:
        """Assert Tekton-style result files match ``oci_manifest`` (``repo@sha256:…``)."""
        if not self.assert_file_exists(image_url_path, f"{test_label} Konflux OCI URL file"):
            return False
        if not self.assert_file_exists(image_digest_path, f"{test_label} Konflux OCI digest file"):
            return False
        konflux_url = image_url_path.read_text(encoding="utf-8").strip()
        konflux_digest = image_digest_path.read_text(encoding="utf-8").strip()
        expected_url, expected_digest = oci_manifest.rsplit("@", 1)
        if konflux_url != expected_url:
            self.stats.failed += 1
            self.log_error(f"Konflux OCI URL {konflux_url!r} != expected {expected_url!r}")
            return False
        if not konflux_digest.startswith("sha256:"):
            konflux_digest = f"sha256:{konflux_digest}"
        if expected_digest.startswith("sha256:"):
            expected_digest_norm = expected_digest
        else:
            expected_digest_norm = f"sha256:{expected_digest}"
        if konflux_digest != expected_digest_norm:
            self.stats.failed += 1
            self.log_error(f"Konflux OCI digest {konflux_digest!r} != expected {expected_digest_norm!r}")
            return False
        self.stats.passed += 1
        self.log_success(f"Konflux OCI results match manifest ({test_label})")
        return True

    def test_upload_build_oras_publish(self):
        """upload-build ORAS publish of pulp_results.json (requires --oci-storage)."""
        oci_storage = self._oci_oras_prereqs("upload-build ORAS publish")
        if not oci_storage:
            return

        build_id = self.bid(BUILD_ID_UPLOAD_ORAS)
        rpm_dir = self.rpm_dirs[2] / "noarch"
        image_url_path = self.output_dir / "oras_image_url"
        image_digest_path = self.output_dir / "oras_image_digest"

        self.run_test(
            "pulp-tool upload-build ORAS publish",
            detail=f"build_id={build_id} oci_storage={oci_storage}",
        )
        try:
            oci_ref = self._run_upload_build_oras(
                oci_storage,
                build_id,
                rpm_dir,
                image_url_path=image_url_path,
                image_digest_path=image_digest_path,
            )
        except RuntimeError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return

        self.last_oci_pulp_results_ref = oci_ref
        self.last_oci_build_id = build_id
        self.log_success(f"ORAS-published pulp_results oci_manifest: {oci_ref}")

        self.run_test("Konflux OCI artifact-results files", detail=f"url={image_url_path} digest={image_digest_path}")
        self._assert_konflux_oci_results_match_manifest(
            oci_ref,
            image_url_path,
            image_digest_path,
            test_label="upload-build ORAS",
        )

        self.defer_distribution_check(
            "upload-build ORAS pulp_results.json on pulp-content",
            lambda suite: suite._execute_upload_build_oras_pulp_distribution_verification(
                build_id=build_id,
                oci_ref=oci_ref,
            ),
            build_id=build_id,
        )

    def _execute_upload_build_oras_pulp_distribution_verification(self, *, build_id: str, oci_ref: str) -> None:
        client = distribution_client_from_config(self.config_file)
        pulp_results_url = (
            f"{self.base_url}/api/pulp-content/{self.namespace}/{build_id}/artifacts/pulp_results.json"
        )
        try:
            pulp_results_content = json.loads(
                fetch_bytes(client, pulp_results_url, label="pulp_results.json").decode("utf-8")
            )
        except DistributionFetchError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return
        version = pulp_results_content.get("version")
        schema_version = str(version).strip() if version is not None else ""
        if not schema_version:
            self.stats.failed += 1
            self.log_error(f"Expected version on pulp_results.json, got {version!r}")
            return
        if pulp_results_content.get("oci_manifest"):
            self.stats.failed += 1
            self.log_error(
                "pulp_results.json must not embed oci_manifest "
                "(OCI identity is registry digest + Tekton artifact-results)"
            )
            return
        self.stats.passed += 1
        self.log_success(f"Pulp pulp_results.json version {schema_version}; no embedded oci_manifest")

    def _load_pulp_results_from_distribution(self, build_id: str) -> dict | None:
        client = distribution_client_from_config(self.config_file)
        pulp_results_url = (
            f"{self.base_url}/api/pulp-content/{self.namespace}/{build_id}/artifacts/pulp_results.json"
        )
        try:
            return json.loads(fetch_bytes(client, pulp_results_url, label="pulp_results.json").decode("utf-8"))
        except DistributionFetchError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return None

    def _run_update_build_oras(
        self,
        oci_storage: str,
        build_id: str,
        results_json_ref: str,
        files_base_path: Path,
        *,
        image_url_path: Path,
        image_digest_path: Path,
        signed_by: str | None = None,
    ) -> str:
        """Run ``update-build`` with OCI ``--results-json``; return new ``oci_manifest`` from Pulp."""
        storage = scoped_oci_storage(oci_storage, build_id, self.run_id)
        update_cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "--build-id",
            build_id,
            "--namespace",
            self.namespace,
            "update-build",
            "--results-json",
            results_json_ref,
            "--artifact-results",
            f"{image_url_path},{image_digest_path}",
            "--oci-storage",
            storage,
            "--files-base-path",
            str(files_base_path),
            "--operation",
            "build_sign",
        ]
        if signed_by:
            update_cmd.extend(["--signed-by", signed_by])
        exit_code, output = self.run_command(update_cmd)
        if not self.assert_exit_code(0, exit_code, "update-build with OCI results-json completes successfully"):
            self.log_error(output)
            raise RuntimeError("update-build failed")
        return self._oci_ref_from_konflux_results(image_url_path, image_digest_path)

    def test_update_build_oras_live(self):
        """
        Live ``update-build``: ORAS-pull prior manifest, re-upload RPMs, bump version, republish OCI target.

        Requires ``--real-server``, ``--oci-storage``, and ``oras`` on PATH (same as upload-build ORAS cases).
        """
        oci_storage = self._oci_oras_prereqs("update-build live")
        if not oci_storage:
            return

        build_id = self.bid(BUILD_ID_UPDATE_BUILD)
        rpm_dir = self.rpm_dirs[2] / "noarch"
        image_url_path = self.output_dir / "update_build_image_url"
        image_digest_path = self.output_dir / "update_build_image_digest"
        e2e_signer = "e2e-update-build-signer@example.com"

        self.run_test(
            "upload-build (setup OCI target for update-build)",
            detail=f"build_id={build_id}",
        )
        try:
            oci_ref_before = self._run_upload_build_oras(
                oci_storage,
                build_id,
                rpm_dir,
                image_url_path=self.output_dir / "update_build_setup_url",
                image_digest_path=self.output_dir / "update_build_setup_digest",
            )
        except RuntimeError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return

        doc_before = self._load_pulp_results_from_distribution(build_id)
        if doc_before is None:
            return

        self.run_test(
            "pulp-tool update-build (OCI --results-json)",
            detail=f"build_id={build_id} ref={oci_ref_before}",
        )
        try:
            oci_ref_after = self._run_update_build_oras(
                oci_storage,
                build_id,
                oci_ref_before,
                rpm_dir,
                image_url_path=image_url_path,
                image_digest_path=image_digest_path,
                signed_by=e2e_signer,
            )
        except RuntimeError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return

        if oci_ref_before == oci_ref_after:
            self.stats.failed += 1
            self.log_error(f"Expected new OCI digest after update-build, still {oci_ref_after!r}")
            return

        self.run_test("Konflux OCI artifact-results after update-build", detail=str(image_url_path))
        if not self._assert_konflux_oci_results_match_manifest(
            oci_ref_after,
            image_url_path,
            image_digest_path,
            test_label="update-build",
        ):
            return

        doc_after = self._load_pulp_results_from_distribution(build_id)
        if doc_after is None:
            return

        rpm_key = "test.2-1.0.0-1.noarch.rpm"
        artifacts = doc_after.get("artifacts") or {}
        rpm_row = artifacts.get(rpm_key) if isinstance(artifacts, dict) else None
        if not isinstance(rpm_row, dict):
            self.stats.failed += 1
            self.log_error(f"Missing artifact {rpm_key!r} in pulp_results.json after update-build")
            return
        labels = rpm_row.get("pulp_labels") or rpm_row.get("labels") or {}
        if e2e_signer not in str(labels.get("signed_by") or ""):
            self.stats.failed += 1
            self.log_error(f"Expected signed_by to include {e2e_signer!r}, got {labels.get('signed_by')!r}")
            return
        history = rpm_row.get("href_history")
        if not isinstance(history, list) or not history:
            self.stats.failed += 1
            self.log_error("Expected href_history on RPM artifact after update-build")
            return
        if not any(str(entry.get("operation") or "") == "build_sign" for entry in history if isinstance(entry, dict)):
            self.stats.failed += 1
            self.log_error(f"Expected href_history operation build_sign, got {history!r}")
            return

        self.log_success(
            "update-build live: href_history recorded, OCI republished, signed_by set",
        )

        self.defer_distribution_check(
            "update-build pulp_results.json on pulp-content",
            lambda suite: suite._execute_update_build_pulp_distribution_verification(
                build_id=build_id,
                oci_ref=oci_ref_after,
            ),
            build_id=build_id,
        )

    def _execute_update_build_pulp_distribution_verification(
        self,
        *,
        build_id: str,
        oci_ref: str,
    ) -> None:
        doc = self._load_pulp_results_from_distribution(build_id)
        if doc is None:
            return
        artifacts = doc.get("artifacts")
        if not isinstance(artifacts, dict) or not any(
            isinstance(row, dict) and row.get("href_history") for row in artifacts.values()
        ):
            self.stats.failed += 1
            self.log_error("Deferred check: expected href_history on at least one artifact after update-build")
            return
        if doc.get("oci_manifest"):
            self.stats.failed += 1
            self.log_error("pulp_results.json must not embed oci_manifest after update-build")
            return
        self.stats.passed += 1
        self.log_success("update-build pulp_results.json reachable on pulp-content with mutation metadata")

    def _artifact_sha256_from_doc(self, doc: dict, artifact_key: str) -> str:
        artifacts = doc.get("artifacts")
        if not isinstance(artifacts, dict):
            return ""
        row = artifacts.get(artifact_key)
        if not isinstance(row, dict):
            return ""
        return normalize_sha256_hex(str(row.get("sha256") or ""))

    def _pull_rpm_via_artifact_location(
        self,
        artifact_location: str,
        pull_dir: Path,
        *,
        label: str,
        expected_rpm_key: str,
        expected_sha256: str,
    ) -> bool:
        """Run ``pull --artifact-location`` and verify the expected RPM checksum."""
        pull_dir.mkdir(parents=True, exist_ok=True)
        for path in pull_dir.iterdir():
            if path.is_file():
                path.unlink()
        self.run_test(label, detail=f"location={artifact_location}")
        pull_cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "pull",
            "--artifact-location",
            artifact_location,
            "--content-types",
            "rpm",
            "--archs",
            "noarch",
        ]
        exit_code, output = self.run_command(pull_cmd, cwd=pull_dir)
        if not self.assert_exit_code(0, exit_code, f"{label} completes"):
            self.log_error(output)
            return False
        rpm_path = pull_dir / expected_rpm_key
        if not self.assert_file_exists(rpm_path, f"{label} wrote {expected_rpm_key}"):
            self.log_error(output)
            return False
        with rpm_path.open("rb") as rpm_file:
            actual = normalize_sha256_hex(hashlib.file_digest(rpm_file, "sha256").hexdigest())
        if actual != expected_sha256:
            self.stats.failed += 1
            self.log_error(f"{label}: RPM SHA256 mismatch expected={expected_sha256} actual={actual}")
            return False
        self.stats.passed += 1
        self.log_success(f"{label}: downloaded {expected_rpm_key} with expected SHA256")
        return True

    def _execute_update_build_replaced_rpm_distribution_verification(
        self,
        *,
        build_id: str,
        artifact_key: str,
        expected_sha256: str,
    ) -> None:
        doc = self._load_pulp_results_from_distribution(build_id)
        if doc is None:
            return
        artifacts = doc.get("artifacts")
        if not isinstance(artifacts, dict):
            self.stats.failed += 1
            self.log_error("pulp_results.json missing artifacts for replaced RPM verify")
            return
        row = artifacts.get(artifact_key)
        if not isinstance(row, dict):
            self.stats.failed += 1
            self.log_error(f"Missing artifact {artifact_key!r} for distribution verify")
            return
        url = str(row.get("url") or "").strip()
        if not url.startswith("http"):
            self.stats.failed += 1
            self.log_error(f"Artifact {artifact_key!r} has no http(s) url for distribution verify")
            return
        client = distribution_client_from_config(self.config_file)
        try:
            fetch_and_verify_sha256(client, url, expected_sha256, label=f"RPM ({artifact_key}) after update-build")
        except DistributionFetchError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return
        self.stats.passed += 1
        self.log_success(f"Replaced RPM distribution URL matches SHA256 {expected_sha256}")

    def test_update_build_replaced_rpm_checksum(self):
        """
        Live ``update-build`` with a **new RPM payload** (same NEVRA filename, different SHA256).

        Ensures ``pulp_results.json`` updates checksum/href lineage and ``href_history`` records the prior state.
        """
        oci_storage = self._oci_oras_prereqs("update-build replaced RPM checksum")
        if not oci_storage:
            return

        build_id = self.bid(BUILD_ID_UPDATE_BUILD_REPLACED)
        original_rpm_dir = self.rpm_dirs[2] / "noarch"
        workspace = self.output_dir / "update-build-replaced-rpms"
        image_url_path = self.output_dir / "update_build_replaced_url"
        image_digest_path = self.output_dir / "update_build_replaced_digest"
        rpm_key = TEST2_NOARCH_RPM_NAME

        self.run_test("upload-build (baseline RPM for replaced checksum test)", detail=f"build_id={build_id}")
        try:
            oci_ref_before = self._run_upload_build_oras(
                oci_storage,
                build_id,
                original_rpm_dir,
                image_url_path=self.output_dir / "update_build_replaced_setup_url",
                image_digest_path=self.output_dir / "update_build_replaced_setup_digest",
            )
        except RuntimeError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return

        doc_before = self._load_pulp_results_from_distribution(build_id)
        if doc_before is None:
            return
        sha_before = self._artifact_sha256_from_doc(doc_before, rpm_key)
        if not sha_before:
            self.stats.failed += 1
            self.log_error(f"Missing baseline SHA256 for {rpm_key!r} in pulp_results.json")
            return

        self.run_test("Build modified RPM payload (same NEVRA filename)", detail=f"variant={build_id}")
        try:
            build_test2_noarch_rpm(workspace, variant=build_id)
        except RuntimeError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return
        modified_path = workspace / rpm_key
        with modified_path.open("rb") as rpm_file:
            sha_workspace = normalize_sha256_hex(hashlib.file_digest(rpm_file, "sha256").hexdigest())
        if sha_workspace == sha_before:
            self.stats.failed += 1
            self.log_error("Modified RPM workspace file must differ from baseline pulp_results SHA256")
            return

        self.run_test(
            "pulp-tool update-build with replaced RPM workspace",
            detail=f"build_id={build_id} ref={oci_ref_before}",
        )
        try:
            oci_ref_after = self._run_update_build_oras(
                oci_storage,
                build_id,
                oci_ref_before,
                workspace,
                image_url_path=image_url_path,
                image_digest_path=image_digest_path,
                signed_by="e2e-replaced-rpm@example.com",
            )
        except RuntimeError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return
        if oci_ref_before == oci_ref_after:
            self.stats.failed += 1
            self.log_error(f"Expected new OCI digest after replaced-RPM update-build, still {oci_ref_after!r}")
            return

        doc_after = self._load_pulp_results_from_distribution(build_id)
        if doc_after is None:
            return
        sha_after = self._artifact_sha256_from_doc(doc_after, rpm_key)
        if not sha_after or sha_after == sha_before:
            self.stats.failed += 1
            self.log_error(f"Expected new SHA256 after update-build, before={sha_before} after={sha_after!r}")
            return

        artifacts = doc_after.get("artifacts") or {}
        rpm_row = artifacts.get(rpm_key) if isinstance(artifacts, dict) else None
        if not isinstance(rpm_row, dict):
            self.stats.failed += 1
            self.log_error(f"Missing artifact row {rpm_key!r} after update-build")
            return
        history = rpm_row.get("href_history")
        if not isinstance(history, list) or not history:
            self.stats.failed += 1
            self.log_error("Expected href_history after replaced RPM update-build")
            return
        history_sha_values = {
            normalize_sha256_hex(str(entry.get("sha256") or ""))
            for entry in history
            if isinstance(entry, dict) and entry.get("sha256")
        }
        if sha_before not in history_sha_values:
            self.stats.failed += 1
            self.log_error(
                f"href_history should record prior SHA256 {sha_before}, got entries {history!r}",
            )
            return

        self.log_success(
            f"update-build replaced RPM: sha256 {sha_before} -> {sha_after}, href_history records prior digest",
        )

        self.defer_distribution_check(
            "update-build replaced RPM on pulp-content",
            lambda suite: suite._execute_update_build_replaced_rpm_distribution_verification(
                build_id=build_id,
                artifact_key=rpm_key,
                expected_sha256=sha_after,
            ),
            build_id=build_id,
        )

    def test_upload_build_update_build_pull_pipeline(self):
        """
        End-to-end Konflux flow: ``upload-build`` (ORAS push) → ``update-build`` (attach) → ``pull``.

        ``pull --artifact-location`` uses the **subject** digest from the initial upload (``oras discover``
        for attached ``pulp_results``), then the Tekton **artifact-results** digest from ``update-build``.
        """
        oci_storage = self._oci_oras_prereqs("upload-build → update-build → pull")
        if not oci_storage:
            return

        build_id = self.bid(BUILD_ID_UPDATE_BUILD_PULL)
        rpm_dir = self.rpm_dirs[2] / "noarch"
        rpm_key = "test.2-1.0.0-1.noarch.rpm"
        pipeline_signer = "e2e-pipeline-signer@example.com"
        setup_url = self.output_dir / "pipeline_setup_image_url"
        setup_digest = self.output_dir / "pipeline_setup_image_digest"
        update_url = self.output_dir / "pipeline_update_image_url"
        update_digest = self.output_dir / "pipeline_update_image_digest"

        self.run_test("upload-build (pipeline subject)", detail=f"build_id={build_id}")
        try:
            subject_ref = self._run_upload_build_oras(
                oci_storage,
                build_id,
                rpm_dir,
                image_url_path=setup_url,
                image_digest_path=setup_digest,
            )
        except RuntimeError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return

        self.run_test("update-build (attach referrer)", detail=f"subject={subject_ref}")
        try:
            artifact_ref = self._run_update_build_oras(
                oci_storage,
                build_id,
                subject_ref,
                rpm_dir,
                image_url_path=update_url,
                image_digest_path=update_digest,
                signed_by=pipeline_signer,
            )
        except RuntimeError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return

        if subject_ref == artifact_ref:
            self.stats.failed += 1
            self.log_error(f"Expected new artifact digest after update-build attach, still {artifact_ref!r}")
            return
        if not self._assert_konflux_oci_results_match_manifest(
            artifact_ref,
            update_url,
            update_digest,
            test_label="pipeline update-build",
        ):
            return

        doc = self._load_pulp_results_from_distribution(build_id)
        if doc is None:
            return
        artifacts = doc.get("artifacts")
        rpm_row = artifacts.get(rpm_key) if isinstance(artifacts, dict) else None
        if not isinstance(rpm_row, dict) or not rpm_row.get("href_history"):
            self.stats.failed += 1
            self.log_error("Expected href_history on RPM artifact after update-build pipeline")
            return
        expected_sha256 = self._artifact_sha256_from_doc(doc, rpm_key)
        if not expected_sha256:
            self.stats.failed += 1
            self.log_error(f"Missing SHA256 for {rpm_key!r} in pulp_results.json")
            return
        artifacts = doc.get("artifacts")
        rpm_row = artifacts.get(rpm_key) if isinstance(artifacts, dict) else None
        if isinstance(rpm_row, dict):
            pulp_labels = rpm_row.get("pulp_labels") or rpm_row.get("labels") or {}
            if pipeline_signer not in str(pulp_labels.get("signed_by") or ""):
                self.stats.failed += 1
                self.log_error(f"Expected signed_by to include {pipeline_signer!r} before pull")
                return

        subject_pull_dir = self.output_dir / "pipeline-pull-subject"
        if not self._pull_rpm_via_artifact_location(
            subject_ref,
            subject_pull_dir,
            label="pull --artifact-location (upload-build subject; oras discover)",
            expected_rpm_key=rpm_key,
            expected_sha256=expected_sha256,
        ):
            return

        artifact_pull_dir = self.output_dir / "pipeline-pull-artifact-results"
        if not self._pull_rpm_via_artifact_location(
            artifact_ref,
            artifact_pull_dir,
            label="pull --artifact-location (update-build Tekton digest)",
            expected_rpm_key=rpm_key,
            expected_sha256=expected_sha256,
        ):
            return

        self.log_success(
            "upload-build → update-build → pull: subject discover and artifact-results digest both download signed RPM",
        )

    def test_pull_artifact_location_oci_manifest_ref(self):
        """
        ``pull --artifact-location`` with an OCI manifest ref after **upload-build** only (no ``update-build``).

        pulp-tool ORAS-pulls the subject ``pulp_results.json``; see ``test_upload_build_update_build_pull_pipeline``
        for attach + discover after ``update-build``.
        """
        oci_storage = self._oci_oras_prereqs("pull --artifact-location OCI ref")
        if not oci_storage:
            return

        build_id = getattr(self, "last_oci_build_id", None) or self.bid(BUILD_ID_UPLOAD_ORAS)
        oci_ref = getattr(self, "last_oci_pulp_results_ref", None)
        if not oci_ref:
            rpm_dir = self.rpm_dirs[2] / "noarch"
            image_url_path = self.output_dir / "pull_oci_artloc_image_url"
            image_digest_path = self.output_dir / "pull_oci_artloc_image_digest"
            self.run_test("upload-build (setup OCI ref for pull)", detail=f"build_id={build_id}")
            try:
                oci_ref = self._run_upload_build_oras(
                    oci_storage,
                    build_id,
                    rpm_dir,
                    image_url_path=image_url_path,
                    image_digest_path=image_digest_path,
                )
            except RuntimeError as exc:
                self.stats.failed += 1
                self.log_error(str(exc))
                return

        pull_dir = self.output_dir / "pull-oci-artifact-location-output"
        pull_dir.mkdir(parents=True, exist_ok=True)
        self.run_test(
            "pulp-tool pull --artifact-location <oci_manifest@digest>",
            detail=f"ref={oci_ref}",
        )
        pull_cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "pull",
            "--artifact-location",
            oci_ref,
            "--content-types",
            "rpm",
            "--archs",
            "noarch",
        ]
        exit_code, output = self.run_command(pull_cmd, cwd=pull_dir)
        if not self.assert_exit_code(0, exit_code, "Pull with OCI manifest --artifact-location completes"):
            self.log_error(output)
            return
        expected_rpm = "test.2-1.0.0-1.noarch.rpm"
        if not self.assert_file_exists(pull_dir / expected_rpm, f"Pull directory contains {expected_rpm}"):
            self.log_error(output)
            return
        self.log_success("pull --artifact-location consumed OCI manifest ref directly")

    # Test: search-by command help
    def test_search_by_help(self):
        self.run_test("pulp-tool search-by --help")
        exit_code, output = self.run_command(["pulp-tool", "search-by", "--help"])
        self.assert_exit_code(0, exit_code, "Search-by help command")
        if exit_code > 0:
            self.log_error(output)
        self.assert_output_contains(output, "--checksums", "Help shows --checksums option")
        self.assert_output_contains(output, "--filenames", "Help shows --filenames option")
        self.assert_output_contains(output, "--signed-by", "Help shows --signed-by option")

    # Test: create-repository command help
    def test_create_repository_help(self):
        self.run_test("pulp-tool create-repository --help")
        exit_code, output = self.run_command(["pulp-tool", "create-repository", "--help"])
        self.assert_exit_code(0, exit_code, "Create-repository help command")
        if exit_code > 0:
            self.log_error(output)
        self.assert_output_contains(output, "--repository-name", "Help shows --repository-name option")
        self.assert_output_contains(output, "--packages", "Help shows --packages option")
        self.assert_output_contains(output, "--base-path", "Help shows --base-path option")

    # Test: global options
    def test_global_options(self):
        self.run_test("pulp-tool --config validation")
        exit_code, output = self.run_command(["pulp-tool", "--config", "/nonexistent/path.toml", "upload", "--help"])
        if "help" in output.lower() or "usage" in output.lower() or "rpm-path" in output.lower():
            self.log_success("Config path accepted (validated at command execution)")
            self.stats.passed += 1
        else:
            self.log_warn("Config validation may occur differently")
            self.stats.skipped += 1

        self.run_test("pulp-tool debug flags")
        exit_code, output = self.run_command(["pulp-tool", "-d", "upload", "--help"])
        self.assert_exit_code(0, exit_code, "Single -d flag works")
        if exit_code > 0:
            self.log_error(output)

        exit_code, output = self.run_command(["pulp-tool", "-dd", "upload", "--help"])
        self.assert_exit_code(0, exit_code, "Double -dd flag works")
        if exit_code > 0:
            self.log_error(output)

        exit_code, output = self.run_command(["pulp-tool", "-ddd", "upload", "--help"])
        self.assert_exit_code(0, exit_code, "Triple -ddd flag works")
        if exit_code > 0:
            self.log_error(output)

    def test_cli_validation_errors(self):
        """CLI validation smoke (no Pulp mutations)."""
        fixture_location = str(self.pulp_results)
        cfg = str(self.config_file)

        self.expect_cli_failure(
            "pull: --side-tag requires --transfer-dest",
            [
                "pulp-tool",
                "--config",
                cfg,
                "pull",
                "--side-tag",
                "e2e-side-tag-smoke",
                "--artifact-location",
                fixture_location,
            ],
            substring="--side-tag requires --transfer-dest",
        )
        self.expect_cli_failure(
            "pull: --artifact-location with --build-id/--namespace",
            [
                "pulp-tool",
                "--config",
                cfg,
                "--build-id",
                "x",
                "--namespace",
                self.namespace,
                "pull",
                "--artifact-location",
                fixture_location,
            ],
            substring="Cannot use --artifact-location with --build-id",
        )
        self.expect_cli_failure(
            "pull: missing artifact location",
            ["pulp-tool", "--config", cfg, "pull"],
            substring="Either --artifact-location OR",
        )
        transfer_no_oci = self._write_transfer_dest_config_no_oci()
        self.expect_cli_failure(
            "pull: side-tag without oci_storage on transfer-dest",
            [
                "pulp-tool",
                "--config",
                cfg,
                "pull",
                "--artifact-location",
                fixture_location,
                "--transfer-dest",
                str(transfer_no_oci),
                "--side-tag",
                "e2e-side-tag-smoke",
            ],
            substring="--oci-storage",
        )
        self.expect_cli_failure(
            "upload-build: missing --build-id",
            [
                "pulp-tool",
                "--config",
                cfg,
                "--namespace",
                self.namespace,
                "upload-build",
                "--rpm-path",
                str(self.rpm_dir_arg),
            ],
            substring="--build-id is required",
        )
        self.expect_cli_failure(
            "upload-build: missing --namespace",
            [
                "pulp-tool",
                "--config",
                cfg,
                "--build-id",
                "smoke-build",
                "upload-build",
                "--rpm-path",
                str(self.rpm_dir_arg),
            ],
            substring="--namespace is required",
        )
        self.expect_cli_failure(
            "upload-build: --files-base-path without --results-json",
            [
                "pulp-tool",
                "--config",
                cfg,
                "--build-id",
                "smoke-build",
                "--namespace",
                self.namespace,
                "upload-build",
                "--files-base-path",
                str(self.test_dir),
            ],
            substring="--files-base-path can only be used with --results-json",
        )
        self.expect_cli_failure(
            "upload-files: no file options",
            [
                "pulp-tool",
                "--config",
                cfg,
                "--build-id",
                "smoke-build",
                "--namespace",
                self.namespace,
                "upload-files",
                "--parent-package",
                "smoke-pkg",
            ],
            substring="At least one file must be specified",
        )
        self.expect_cli_failure(
            "search-by: missing --config",
            ["pulp-tool", "search-by", "--checksums", "a" * 64],
            substring="--config is required for search-by",
        )
        self.expect_cli_failure(
            "search-by: --checksum without --results-json",
            ["pulp-tool", "--config", cfg, "search-by", "--checksum"],
            substring="--checksum requires --results-json",
        )
        self.expect_cli_failure(
            "search-by: checksums and filenames mutually exclusive",
            [
                "pulp-tool",
                "--config",
                cfg,
                "search-by",
                "--checksums",
                "3eb28dc3c8beb2082fb12c894e8b8dc8af050869725f170871ff5b96cd88ca79",
                "--filenames",
                "test.rpm",
            ],
            substring="checksums and filenames cannot be combined",
        )

    def test_live_readonly_errors(self):
        """Live Pulp/registry failures without creating new repositories."""
        if not self.real_server:
            self.skip_test("live read-only CLI errors", "DRY RUN")
            return

        cfg = str(self.config_file)
        auth_config = self._write_minimal_pull_auth_config()
        https_fixture = (
            f"{self.base_url}/api/pulp-content/{self.namespace}/"
            f"{self.bid('nonexistent-build-e2e')}/artifacts/pulp_results.json"
        )
        self.expect_cli_failure(
            "pull: HTTPS artifact without distribution auth",
            [
                "pulp-tool",
                "--config",
                str(auth_config),
                "pull",
                "--artifact-location",
                https_fixture,
            ],
            substring="Authentication required",
        )
        self.expect_cli_failure(
            "pull: 404 pulp_results on pulp-content",
            [
                "pulp-tool",
                "--config",
                cfg,
                "pull",
                "--artifact-location",
                https_fixture,
            ],
        )
        self.expect_cli_failure(
            "search-by: invalid checksum hex",
            ["pulp-tool", "--config", cfg, "search-by", "--checksums", "not-a-hex"],
            substring="Invalid checksum format",
        )
        pull_dir = self.output_dir / "pull-filter-fail"
        pull_dir.mkdir(parents=True, exist_ok=True)
        self.expect_cli_failure(
            "pull: invalid --content-types",
            [
                "pulp-tool",
                "--config",
                cfg,
                "pull",
                "--artifact-location",
                str(self.pulp_results),
                "--content-types",
                "invalid",
            ],
            cwd=pull_dir,
            substring="Invalid content type",
        )
        bad_json = self.test_dir / "invalid-pulp-results.json"
        bad_json.write_text("{ not valid json", encoding="utf-8")
        self.expect_cli_failure(
            "pull: invalid local pulp_results JSON",
            [
                "pulp-tool",
                "--config",
                cfg,
                "pull",
                "--artifact-location",
                str(bad_json),
            ],
        )

        if self.oci_storage and shutil.which("oras"):
            repo = self.oci_storage.split(":")[0] if ":" in self.oci_storage else self.oci_storage
            bogus_ref = f"{repo}@sha256:{'0' * 64}"
            self.expect_cli_failure(
                "pull: bogus OCI manifest digest",
                [
                    "pulp-tool",
                    "--config",
                    cfg,
                    "pull",
                    "--artifact-location",
                    bogus_ref,
                ],
            )

    def test_live_mutating_errors(self):
        """Live failures that may touch Pulp; uses isolated names and cleanup."""
        if not self.real_server:
            self.skip_test("live mutating CLI errors", "DRY RUN")
            return

        cfg = str(self.config_file)
        build_id = self.bid(BUILD_ID_E2E_ERROR_EMPTY)
        empty_rpm_dir = self.test_dir / "empty-rpm-path"
        empty_rpm_dir.mkdir(parents=True, exist_ok=True)
        try:
            exit_code, output = self.run_command(
                [
                    "pulp-tool",
                    "--config",
                    cfg,
                    "--build-id",
                    build_id,
                    "--namespace",
                    self.namespace,
                    "upload",
                    "--rpm-path",
                    str(empty_rpm_dir),
                ]
            )
            self.run_test("upload: empty --rpm-path")
            if exit_code == 0:
                self.log_error("upload with empty rpm-path should fail (non-zero exit)")
                self.stats.failed += 1
            else:
                self.log_success(f"upload empty rpm-path rejected (exit {exit_code})")
                self.stats.passed += 1
        finally:
            self._cleanup_e2e_error_upload_repos(build_id)

        missing_results = self.test_dir / "missing-results.json"
        self.expect_cli_failure(
            "upload-build: --results-json path does not exist",
            [
                "pulp-tool",
                "--config",
                cfg,
                "--build-id",
                build_id,
                "--namespace",
                self.namespace,
                "upload-build",
                "--results-json",
                str(missing_results),
            ],
            substring="results JSON not found",
        )
        invalid_results = self.test_dir / "invalid-results.json"
        invalid_results.write_text("{ not valid json", encoding="utf-8")
        self.expect_cli_failure(
            "upload-build: invalid --results-json contents",
            [
                "pulp-tool",
                "--config",
                cfg,
                "--build-id",
                build_id,
                "--namespace",
                self.namespace,
                "upload-build",
                "--results-json",
                str(invalid_results),
            ],
            substring="Failed to read results JSON",
        )

        self.expect_cli_failure(
            "upload-files: missing --rpm file path",
            [
                "pulp-tool",
                "--config",
                cfg,
                "--build-id",
                self.bid("test-error-upload-files"),
                "--namespace",
                self.namespace,
                "upload-files",
                "--rpm",
                str(self.test_dir / "does-not-exist.rpm"),
            ],
        )

        repo_name = self.bid(REPO_E2E_ERROR_DUP)
        base_path = self.bpath(BASE_PATH_E2E_ERROR_DUP)
        package_href = f"/api/pulp/{self.namespace}/api/v3/content/rpm/packages/019e1c81-287e-70bb-8009-ff05bd35415a/"
        create_cmd = [
            "pulp-tool",
            "--config",
            cfg,
            "create-repository",
            "--repository-name",
            repo_name,
            "--packages",
            package_href,
            "--base-path",
            base_path,
        ]
        exit_code, output = self.run_command(create_cmd)
        self.run_test("create-repository: first create (setup for duplicate)")
        if exit_code != 0:
            self.log_error(f"First create-repository failed: {output[:500]}")
            self.stats.failed += 1
        else:
            self.stats.passed += 1
            self.log_success("First create-repository succeeded")
            self.run_test("create-repository: duplicate invoke reuses existing repo/distro")
            dup_exit, dup_output = self.run_command(create_cmd)
            if dup_exit != 0:
                self.log_error(f"Duplicate create-repository should be idempotent (exit 0), got {dup_exit}")
                self.stats.failed += 1
            elif "existing" not in dup_output.lower():
                self.log_error("Expected idempotent create-repository to log existing repo/distribution reuse")
                self.stats.failed += 1
            else:
                self.log_success("Duplicate create-repository reuses existing resources (exit 0)")
                self.stats.passed += 1
        self._destroy_pulp_rpm_repo(repo_name)

    # Test: upload command with minimal options
    def test_upload_minimal(self):
        if not self.real_server:
            self.skip_test("upload command (minimal)", "DRY RUN")
            return

        # Use RPM directory index 0
        rpm_dir = self.rpm_dirs[0]
        self.run_test(f"pulp-tool upload (minimal) - using {rpm_dir}")

        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "--build-id",
            self.bid(BUILD_ID_UPLOAD_MINIMAL),
            "--namespace",
            self.namespace,
            "upload",
            "--rpm-path",
            str(rpm_dir),
        ]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Upload minimal completes successfully")

        if exit_code > 0:
            self.log_error(output)

    # Test: upload command with all options
    def test_upload_full(self):
        if not self.real_server:
            self.skip_test("upload command (full options)", "DRY RUN")
            return

        oci_storage = self._oci_oras_prereqs("upload full (Konflux artifact-results)")
        if not oci_storage:
            return

        # Use RPM directory index 1
        rpm_dir = self.rpm_dirs[1]
        sbom_results = self.output_dir / "sbom_results.json"
        image_url_path = self.output_dir / "image_url"
        image_digest_path = self.output_dir / "image_digest"
        full_build_id = self.bid(BUILD_ID_UPLOAD_FULL)
        storage = scoped_oci_storage(oci_storage, full_build_id, self.run_id)

        self.run_test(
            "pulp-tool upload (full options)",
            detail=f"rpm_dir={rpm_dir} build_id={full_build_id} namespace={self.namespace} oci_storage={storage}",
        )

        cmd = [
            "pulp-tool",
            "-dd",
            "--config",
            str(self.config_file),
            "--build-id",
            self.bid(BUILD_ID_UPLOAD_FULL),
            "--namespace",
            self.namespace,
            "upload",
            "--parent-package",
            "test-parent",
            "--rpm-path",
            str(rpm_dir),
            "--sbom-path",
            str(self.sbom_file),
            "--artifact-results",
            f"{image_url_path},{image_digest_path}",
            "--oci-storage",
            storage,
            "--sbom-results",
            str(sbom_results),
            "--signed-by",
            "test-key-id",
        ]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Upload with all options completes successfully")
        if exit_code > 0:
            self.log_error(output)
            return

        if not self.assert_file_exists(sbom_results, "SBOM results file"):
            self.log_error(output)
            return

        sbom_results_content = sbom_results.read_text("utf-8")
        expected_sbom_results = f"{self.base_url}/api/pulp-content/{self.namespace}/{full_build_id}/sbom/sbom.json"
        self.run_test("validate SBOM results URL", detail=f"expected={expected_sbom_results}")
        if sbom_results_content != expected_sbom_results:
            self.stats.failed += 1
            self.log_error(f"Unexpected SBOM results: {sbom_results_content}")
        else:
            self.stats.passed += 1
            self.log_success("SBOM results match expected value")

        if not self.assert_file_exists(image_url_path, "Konflux image URL result file"):
            return
        if not self.assert_file_exists(image_digest_path, "Konflux image digest result file"):
            return

        oci_ref = self._oci_ref_from_konflux_results(image_url_path, image_digest_path)
        self._assert_konflux_oci_results_match_manifest(
            oci_ref,
            image_url_path,
            image_digest_path,
            test_label="upload full",
        )

        self.defer_distribution_check(
            "upload full (RPM, SBOM, pulp_results.json)",
            lambda suite: suite._execute_upload_full_distribution_verification(
                full_build_id=full_build_id,
                image_url_path=image_url_path,
                image_digest_path=image_digest_path,
                sbom_results_content=sbom_results_content,
                upload_output=output,
            ),
            build_id=full_build_id,
        )

    def _execute_upload_full_distribution_verification(
        self,
        *,
        full_build_id: str,
        image_url_path: Path,
        image_digest_path: Path,
        sbom_results_content: str,
        upload_output: str,
    ) -> None:
        """Deferred pulp-content checks for test_upload_full."""
        try:
            client = distribution_client_from_config(self.config_file)
            pulp_results_url = (
                f"{self.base_url}/api/pulp-content/{self.namespace}/{full_build_id}/artifacts/pulp_results.json"
            )
            pulp_results_raw = fetch_bytes(client, pulp_results_url, label="pulp_results.json")
            pulp_results_content = json.loads(pulp_results_raw.decode("utf-8"))
            pulp_results_file_digest = hashlib.sha256(pulp_results_raw).hexdigest()
            oci_ref = self._oci_ref_from_konflux_results(image_url_path, image_digest_path)
            self.log_info(f"Konflux OCI ref: {oci_ref}")
            self.log_info(f"pulp_results.json pulp-content SHA256: {pulp_results_file_digest}")
            expected_pulp_artifacts = {
                "test.1-1.0.0-1.x86_64.rpm",
                "test.1-1.0.0-1.aarch64.rpm",
                "test.1-1.0.0-1.noarch.rpm",
                f"{full_build_id}/sbom.json",
            }
            if not set(pulp_results_content["artifacts"].keys()) == expected_pulp_artifacts:
                self.stats.failed += 1
                self.log_error(f"Unexpected pulp artifacts: {pulp_results_content['artifacts'].keys()}")
                self.log_distribution_fetch_diagnostics(
                    pulp_results_content,
                    pulp_results_url=pulp_results_url,
                    pulp_results_digest=pulp_results_file_digest,
                    sbom_url=sbom_results_content,
                    failed_check="artifact keys",
                    upload_output=upload_output,
                )
            else:
                self.stats.passed += 1
                self.log_success("Pulp results artifacts match expected values")
            expected_pulp_distributions = {"artifacts", "rpms", "rpms_signed", "sbom"}
            if not set(pulp_results_content["distributions"].keys()) == expected_pulp_distributions:
                self.stats.failed += 1
                self.log_error(f"Unexpected pulp distributions: {pulp_results_content['distributions'].keys()}")
                self.log_distribution_fetch_diagnostics(
                    pulp_results_content,
                    pulp_results_url=pulp_results_url,
                    pulp_results_digest=pulp_results_file_digest,
                    sbom_url=sbom_results_content,
                    failed_check="distribution keys",
                    upload_output=upload_output,
                )
            else:
                self.stats.passed += 1
                self.log_success("Pulp results distributions match expected values")

            self.verify_distribution_downloads(
                client,
                pulp_results_content,
                sbom_results_content,
                pulp_results_url,
                pulp_results_file_digest,
            )

        except DistributionFetchError as exc:
            self.stats.failed += 1
            self.log_error(f"Distribution fetch setup failed: {exc}")
            client = distribution_client_from_config(self.config_file)
            sbom_status = probe_http_get_status(client, sbom_results_content)
            self.log_error(
                "Distribution probe (immediate GET, no retry): "
                f"SBOM status={sbom_status} url={sbom_results_content}"
            )
            if sbom_status == 200:
                self.log_error(
                    "SBOM is reachable via pulp-content but pulp_results.json is not — "
                    "likely artifacts-repo publish or pulp-content mapping for the artifacts "
                    "distribution (Pulp/platform), not e2e URL or build_id construction."
                )
            elif sbom_status in {404, 502, 503, 504}:
                self.log_error(
                    "SBOM URL also returned a non-success status — pulp-content may not be "
                    "serving this build's file distributions yet, or Basic Auth/path is wrong "
                    "for the whole build prefix."
                )
                self.log_error(
                    "post-test-validation uses the Pulp API (content in repo); distribution fetch "
                    "uses pulp-content HTTP, which can lag after upload — see "
                    "E2E_DISTRIBUTION_FETCH_MAX_WAIT_S (default 300s)."
                )
            pulp_results_url = (
                f"{self.base_url}/api/pulp-content/{self.namespace}/{full_build_id}/artifacts/pulp_results.json"
            )
            pulp_results_digest = image_digest_path.read_text(encoding="utf-8").strip()
            if "pulp_results_content" in locals():
                self.log_distribution_fetch_diagnostics(
                    pulp_results_content,
                    pulp_results_url=pulp_results_url,
                    pulp_results_digest=pulp_results_file_digest,
                    sbom_url=sbom_results_content,
                    failed_check=getattr(exc, "label", None) or "setup",
                    failed_url=getattr(exc, "url", None) or pulp_results_url,
                    upload_output=upload_output,
                )
        except json.JSONDecodeError as exc:
            self.stats.failed += 2
            self.log_error(f"Bad pulp_results.json file: {exc}")
            pulp_results_url = (
                f"{self.base_url}/api/pulp-content/{self.namespace}/{full_build_id}/artifacts/pulp_results.json"
            )
            self.log_error(f"pulp_results URL: {pulp_results_url}")
        except KeyError as e:
            self.stats.failed += 2
            self.log_error(f"pulp_results.json file missing key: {e}")
            if "pulp_results_content" in locals():
                pulp_results_url = (
                    f"{self.base_url}/api/pulp-content/{self.namespace}/{full_build_id}/artifacts/pulp_results.json"
                )
                pulp_results_digest = image_digest_path.read_text(encoding="utf-8").strip()
                self.log_distribution_fetch_diagnostics(
                    pulp_results_content,
                    pulp_results_url=pulp_results_url,
                    pulp_results_digest=pulp_results_file_digest,
                    sbom_url=sbom_results_content,
                    failed_check="structure validation",
                    upload_output=upload_output,
                )

    # Test: upload command with results-json
    def test_upload_results_json(self):
        if not self.real_server:
            self.skip_test("upload command (results-json)", "DRY RUN")
            return

        # Use RPM directory index 2
        rpm_dir = self.rpm_dirs[2] / "noarch"
        # Note: results-json mode reads artifacts from the JSON file's directory
        # so we don't pass --rpm-path, but the JSON should reference files in rpm_dirs[2]
        self.run_test(f"pulp-tool upload (--results-json) - using {rpm_dir}")

        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "upload",
            "--results-json",
            str(self.upload_results_json),
            "--files-base-path",
            str(rpm_dir),
        ]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Upload with results-json completes successfully")
        if exit_code > 0:
            self.log_error(output)

    # Test: upload command with target-arch-repo
    def test_upload_target_arch_repo(self):
        if not self.real_server:
            self.skip_test("upload command (target-arch-repo)", "DRY RUN")
            return

        # Use RPM directory index 3
        rpm_dir = self.rpm_dirs[3]
        self.run_test(f"pulp-tool upload (--target-arch-repo) - using {rpm_dir}")

        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "--build-id",
            self.bid(BUILD_ID_UPLOAD_TARGET_ARCH),
            "--namespace",
            self.namespace,
            "upload",
            "--rpm-path",
            str(rpm_dir),
            "--target-arch-repo",
        ]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Upload with target-arch-repo completes successfully")
        if exit_code > 0:
            self.log_error(output)

    def test_upload_large_rpm(self):
        """Upload a large RPM to Pulp and verify it is discoverable by checksum."""
        if not self.real_server:
            self.skip_test("upload command (large RPM)", "DRY RUN")
            return

        large_rpm_dir = self.rpm_dir / "large"
        large_rpm_path = large_rpm_dir / "x86_64" / LARGE_RPM_FILENAME
        if not large_rpm_path.is_file():
            self.skip_test("upload command (large RPM)", f"large RPM not found at {large_rpm_path}")
            return

        on_disk_bytes = large_rpm_path.stat().st_size
        if on_disk_bytes < LARGE_UPLOAD_MIN_SIZE_BYTES:
            self.stats.failed += 1
            self.log_error(
                f"Large RPM is {on_disk_bytes / (1024 * 1024):.1f} MiB on disk; "
                f"expected at least {LARGE_UPLOAD_MIN_SIZE_BYTES / (1024 * 1024):.0f} MiB"
            )
            return

        with open(large_rpm_path, "rb") as rpm_file:
            rpm_sha256 = hashlib.file_digest(rpm_file, "sha256").hexdigest()
        rpm_size_mb = large_rpm_path.stat().st_size / (1024 * 1024)
        self.run_test(f"pulp-tool upload (large RPM, {rpm_size_mb:.1f} MiB on disk) - {large_rpm_path}")

        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "--build-id",
            self.bid(BUILD_ID_UPLOAD_LARGE),
            "--namespace",
            self.namespace,
            "upload",
            "--rpm-path",
            str(large_rpm_dir),
        ]
        started = time.monotonic()
        exit_code, output = self.run_command(cmd)
        elapsed_s = time.monotonic() - started
        self.log_info(f"Large RPM upload elapsed: {elapsed_s:.1f}s")
        if not self.assert_exit_code(0, exit_code, "Large RPM upload completes successfully"):
            self.log_error(output)
            return

        self.run_test("pulp-tool search-by confirms large RPM upload by checksum")
        search_cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "search-by",
            "--checksums",
            rpm_sha256,
        ]
        exit_code, output = self.run_command(search_cmd)
        if not self.assert_exit_code(0, exit_code, "Search-by checksum for large RPM"):
            self.log_error(output)
            return
        self.assert_search_by_package(
            output,
            name=LARGE_RPM_PACKAGE,
            version=LARGE_RPM_VERSION,
            release=LARGE_RPM_RELEASE,
            arch=LARGE_RPM_ARCH,
            checksum=rpm_sha256,
            test_name="Large RPM discoverable in Pulp by checksum",
        )

    # Test: upload-files command
    def test_upload_files(self):
        if not self.real_server:
            self.skip_test("upload-files command", "DRY RUN")
            return

        # Use RPM directory index 4
        rpm_dir = self.rpm_dirs[4]
        self.run_test(f"pulp-tool upload-files - using {rpm_dir}")

        # Find first RPM file in the directory
        rpm_files = list(rpm_dir.rglob("*.rpm"))
        if not rpm_files:
            self.log_error(f"No RPM files found in {rpm_dir}")
            self.stats.failed += 1
            return

        rpm_file = rpm_files[0]
        log_file = self.log_dir / "x86_64" / "build.log"

        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "--build-id",
            self.bid(BUILD_ID_UPLOAD_FILES),
            "--namespace",
            self.namespace,
            "upload-files",
            "--parent-package",
            "test-package",
            "--rpm",
            str(rpm_file),
            "--log",
            str(log_file),
            "--sbom",
            str(self.sbom_file),
            "--file",
            str(self.test_file),
            "--arch",
            "x86_64",
        ]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Upload-files completes successfully")
        if exit_code > 0:
            self.log_error(output)

    # Test: pull command build-id/namespace
    def test_pull_by_build_id(self):
        if not self.real_server:
            self.skip_test("pull command", "DRY RUN")
            return

        self.run_test("pulp-tool pull (by build-id/namespace)")
        pull_dir = self.output_dir / "pull-build-id-output"
        pull_dir.mkdir(parents=True)

        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "--build-id",
            "test-fixture",
            "--namespace",
            self.namespace,
            "pull",
            "--content-types",
            "rpm,log",
            "--archs",
            "noarch",
        ]

        # Run from pull_dir
        exit_code, output = self.run_command(cmd, cwd=pull_dir)
        self.assert_exit_code(0, exit_code, "Pull command completes successfully")
        if exit_code > 0:
            self.log_error(output)
        else:
            # Verify expected files exist in pull directory
            self.assert_file_exists(pull_dir / "logs/noarch/build.log", "Pull directory contains logs/noarch/build.log")
            self.assert_file_exists(pull_dir / "logs/noarch/build.log", "Pull directory contains logs/noarch/root.log")
            self.assert_file_exists(pull_dir / "wolf-9.4-2.noarch.rpm", "Pull directory contains wolf-9.4-2.noarch.rpm")

    # Test: pull command --artifact-location
    def test_pull_by_artifact_location(self):
        if not self.real_server:
            self.skip_test("pull command", "DRY RUN")
            return

        self.run_test("pulp-tool pull (by --artifact-location)")
        pull_dir = self.output_dir / "pull-artifact-output"
        # artifact_results = self.output_dir / "pulp_results.json"
        pull_dir.mkdir(parents=True)

        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "pull",
            "--artifact-location",
            str(self.pulp_results),
            "--content-types",
            "rpm,sbom",
            "--archs",
            "noarch",
        ]

        # Run from pull_dir
        exit_code, output = self.run_command(cmd, cwd=pull_dir)
        self.assert_exit_code(0, exit_code, "Pull command completes successfully")
        if exit_code > 0:
            self.log_error(output)
        else:
            # Verify expected files exist in pull directory
            self.assert_file_exists(pull_dir / "sbom.json", "Pull directory contains sbom.json")
            self.assert_file_exists(pull_dir / "wolf-9.4-2.noarch.rpm", "Pull directory contains wolf-9.4-2.noarch.rpm")

    def _run_pull_side_tag_transfer(
        self,
        *,
        build_id: str,
        artifact_location: str,
        side_tag: str,
        image_url_path: Path,
        image_digest_path: Path,
        step_label: str,
    ) -> bool:
        """Shared side-tag pull + ORAS publish; returns True on success."""
        oci_storage = self._oci_oras_prereqs("pull side-tag transfer")
        if not oci_storage:
            return False

        transfer_config = self._write_transfer_dest_config()
        pull_dir = self.output_dir / "pull-side-tag-output"
        pull_dir.mkdir(parents=True, exist_ok=True)
        storage = scoped_oci_storage(oci_storage, build_id, self.run_id)

        self.run_test(step_label, detail=f"side_tag={side_tag} artifact_location={artifact_location[:80]}…")
        pull_cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "pull",
            "--artifact-location",
            artifact_location,
            "--transfer-dest",
            str(transfer_config),
            "--side-tag",
            side_tag,
            "--oci-storage",
            storage,
            "--artifact-results",
            f"{image_url_path},{image_digest_path}",
            "--content-types",
            "rpm",
            "--archs",
            "noarch",
        ]
        exit_code, output = self.run_command(pull_cmd, cwd=pull_dir)
        if not self.assert_exit_code(0, exit_code, "Pull side-tag transfer completes successfully"):
            self.log_error(output)
            return False

        client = distribution_client_from_config(self.config_file)
        pulp_results_url = (
            f"{self.base_url}/api/pulp-content/{self.namespace}/{build_id}/artifacts/pulp_results.json"
        )
        try:
            pulp_results_content = fetch_pulp_results_json(
                client,
                pulp_results_url,
                label="pulp_results.json (post side-tag transfer)",
                required_distribution_keys=frozenset({side_tag}),
            )
        except DistributionFetchError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return False
        oci_ref = self._oci_ref_from_konflux_results(image_url_path, image_digest_path)
        if pulp_results_content.get("oci_manifest"):
            self.stats.failed += 1
            self.log_error("Side-tag pulp_results.json must not embed oci_manifest")
            return False
        if not self._assert_konflux_oci_results_match_manifest(
            oci_ref,
            image_url_path,
            image_digest_path,
            test_label="side-tag transfer",
        ):
            return False
        self.stats.passed += 1
        self.log_success(
            "pulp_results.json version bumped, side-tag distribution, and Tekton OCI results"
        )
        return True

    def test_upload_side_tag_transfer_source(self):
        """Upload source build for HTTPS side-tag pull (distribution verify deferred)."""
        if not self.real_server:
            self.skip_test("upload (side-tag transfer source)", "DRY RUN")
            return

        build_id = self.bid(BUILD_ID_PULL_SIDE_TAG)
        rpm_dir = self.rpm_dirs[0]
        self.run_test(
            "pulp-tool upload (side-tag transfer setup)",
            detail=f"build_id={build_id} rpm_dir={rpm_dir}",
        )
        upload_cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "--build-id",
            build_id,
            "--namespace",
            self.namespace,
            "upload",
            "--rpm-path",
            str(rpm_dir / "noarch"),
        ]
        exit_code, output = self.run_command(upload_cmd)
        if not self.assert_exit_code(0, exit_code, "Upload before side-tag pull"):
            self.log_error(output)
            return

        pulp_results_url = (
            f"{self.base_url}/api/pulp-content/{self.namespace}/{build_id}/artifacts/pulp_results.json"
        )
        self._side_tag_source_pulp_results_url = pulp_results_url
        self.defer_distribution_check(
            "side-tag transfer source pulp_results.json",
            lambda suite: suite._execute_side_tag_source_pulp_results_reachable(pulp_results_url),
            build_id=build_id,
        )

    def _execute_side_tag_source_pulp_results_reachable(self, pulp_results_url: str) -> None:
        try:
            client = distribution_client_from_config(self.config_file)
            fetch_bytes(client, pulp_results_url, label="pulp_results.json")
        except DistributionFetchError as exc:
            self.stats.failed += 1
            self.log_error(f"Source pulp_results.json not available: {exc}")
            return
        self.stats.passed += 1
        self.log_success("Source pulp_results.json is reachable")

    def test_upload_side_tag_oci_source(self):
        """upload-build ORAS source for side-tag OCI pull (pull runs in a later phase)."""
        oci_storage = self._oci_oras_prereqs("upload side-tag OCI source")
        if not oci_storage:
            return

        build_id = self.bid(BUILD_ID_PULL_SIDE_TAG_OCI)
        rpm_dir = self.rpm_dirs[0] / "noarch"
        self.run_test(
            "upload-build (ORAS source for side-tag OCI pull)",
            detail=f"build_id={build_id}",
        )
        image_url_path = self.output_dir / "side_tag_oci_pull_image_url"
        image_digest_path = self.output_dir / "side_tag_oci_pull_image_digest"
        try:
            oci_ref = self._run_upload_build_oras(
                oci_storage,
                build_id,
                rpm_dir,
                image_url_path=image_url_path,
                image_digest_path=image_digest_path,
            )
        except RuntimeError as exc:
            self.stats.failed += 1
            self.log_error(str(exc))
            return

        self._side_tag_oci_ref = oci_ref
        self._side_tag_oci_build_id = build_id

    def test_pull_side_tag_transfer(self):
        """Pull --transfer-dest --side-tag with ORAS manifest push (requires prior source upload)."""
        oci_storage = self._oci_oras_prereqs("pull side-tag transfer")
        if oci_storage is None:
            return

        build_id = self.bid(BUILD_ID_PULL_SIDE_TAG)
        side_tag = self.side_tag_name_for_run()
        pulp_results_url = self._side_tag_source_pulp_results_url
        if not pulp_results_url:
            self.stats.failed += 1
            self.log_error("Missing side-tag source pulp_results URL; run upload phase first")
            return

        image_url_path = self.output_dir / "side_tag_oras_image_url"
        image_digest_path = self.output_dir / "side_tag_oras_image_digest"
        self._run_pull_side_tag_transfer(
            build_id=build_id,
            artifact_location=pulp_results_url,
            side_tag=side_tag,
            image_url_path=image_url_path,
            image_digest_path=image_digest_path,
            step_label="pulp-tool pull --transfer-dest --side-tag (HTTPS pulp_results)",
        )

    def test_pull_side_tag_transfer_from_oci_artifact_location(self):
        """Side-tag transfer with ``--artifact-location`` set to ORAS ``oci_manifest@digest``."""
        oci_storage = self._oci_oras_prereqs("pull side-tag transfer from OCI ref")
        if not oci_storage:
            return

        build_id = self._side_tag_oci_build_id or self.bid(BUILD_ID_PULL_SIDE_TAG_OCI)
        oci_ref = self._side_tag_oci_ref
        if not oci_ref:
            self.stats.failed += 1
            self.log_error("Missing OCI ref from upload side-tag OCI source; run upload phase first")
            return

        side_tag = self.side_tag_name_for_run()
        self._run_pull_side_tag_transfer(
            build_id=build_id,
            artifact_location=oci_ref,
            side_tag=side_tag,
            image_url_path=self.output_dir / "side_tag_transfer_oci_image_url",
            image_digest_path=self.output_dir / "side_tag_transfer_oci_image_digest",
            step_label="pulp-tool pull --transfer-dest --side-tag (OCI manifest ref)",
        )

    # Test: search-by command with checksums
    def test_search_by_checksums(self):
        if not self.real_server:
            self.skip_test("search-by command (checksums)", "DRY RUN")
            return

        self.run_test("pulp-tool search-by --checksums")
        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "search-by",
            "--checksums",
            (
                "3eb28dc3c8beb2082fb12c894e8b8dc8af050869725f170871ff5b96cd88ca79,"
                "b8e2a280ccb2a376237b0d8bff1313b0353d975fa4495e48ab46d01eb0b05154"
            ),
        ]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Search-by checksums completes successfully")
        if exit_code > 0:
            self.log_error(output)

        # Output should be JSON
        if "{" in output:
            self.log_success("Search-by returns JSON output")
            self.stats.passed += 1
        else:
            self.log_warn("Search-by output format unclear")
            self.stats.skipped += 1

    # Test: search-by command with filenames
    def test_search_by_filenames(self):
        if not self.real_server:
            self.skip_test("search-by command (filenames)", "DRY RUN")
            return

        self.run_test("pulp-tool search-by --filenames")
        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "search-by",
            "--filenames",
            "kangaroo-0.3-1.src.rpm,gorilla-0.62-1.src.rpm",
        ]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Search-by filenames completes successfully")
        if exit_code > 0:
            self.log_error(output)

    # Test: search-by command with signed-by
    def test_search_by_signed_by(self):
        if not self.real_server:
            self.skip_test("search-by command (signed-by)", "DRY RUN")
            return

        self.run_test("pulp-tool search-by --signed-by")
        cmd = ["pulp-tool", "--config", str(self.config_file), "search-by", "--signed-by", "test-key-id"]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Search-by signed-by completes successfully")
        if exit_code > 0:
            self.log_error(output)

    # Test: search-by command with results-json filtering
    def test_search_by_results_json(self):
        if not self.real_server:
            self.skip_test("search-by command (results-json)", "DRY RUN")
            return

        ext_pulp_results = self.test_dir / "pulp_resutls.json"
        shutil.copyfile(self.pulp_results, ext_pulp_results)

        with open(ext_pulp_results, "r") as epr:
            pulp_results_json = json.load(epr)
        pulp_results_json["artifacts"]["bear-4.1-1.noarch.rpm"] = {
            "pulp_labels": {
                "date": "2026-06-05 12:41:16",
                "build_id": "test-fixture",
                "arch": "noarch",
                "namespace": "konflux-artifact-storage-tenant",
                "parent_package": "test-fixture-parent",
            },
            "url": "https://test.url",
            "sha256": "c748d48ef1cfd38788afdcfc6ed825d0d1241ff98bfe094b618c388367228ba0",
        }
        with open(ext_pulp_results, "w") as epr:
            json.dump(pulp_results_json, epr, indent=2)

        self.run_test("pulp-tool search-by --results-json")
        filtered_output = self.output_dir / "filtered_results.json"

        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "search-by",
            "--results-json",
            str(ext_pulp_results),
            "--output-results",
            str(filtered_output),
        ]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Search-by results-json filtering completes successfully")
        if exit_code > 0:
            self.log_error(output)

        try:
            with open(filtered_output) as fo:
                json_output = json.load(fo)
                artifact_list = list(json_output["artifacts"])
                if len(artifact_list) != 1:
                    self.log_error(f'{filtered_output} "artifacts" should contain one item')
                    self.stats.failed += 1
                elif artifact_list[0] != "bear-4.1-1.noarch.rpm":
                    self.log_error(f'{filtered_output} "artifacts" should only contain "bear-4.1-1.noarch.rpm"')
                    self.stats.failed += 1
                else:
                    self.log_success(f"{filtered_output} contains correct artifacts")
                    self.stats.passed += 1
        except json.JSONDecodeError:
            self.log_error(f"{filtered_output} content validation failed")
            self.stats.failed += 1
        except KeyError:
            self.log_error(f"{filtered_output} content validation failed")
            self.stats.failed += 1

    # Test: create-repository command
    def test_create_repository(self):
        if not self.real_server:
            self.skip_test("create-repository command", "DRY RUN")
            return

        self.run_test("pulp-tool create-repository")
        repo_name = self.bid(REPO_CREATE_REPOSITORY)
        base_path = self.bpath(BASE_PATH_CREATE_REPOSITORY)
        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "create-repository",
            "--repository-name",
            repo_name,
            "--packages",
            f"/api/pulp/{self.namespace}/api/v3/content/rpm/packages/019e1c81-287e-70bb-8009-ff05bd35415a/",
            "--base-path",
            base_path,
            "--compression-type",
            "zstd",
            "--checksum-type",
            "sha256",
        ]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Create-repository command completes successfully")
        if exit_code > 0:
            self.log_error(output)

    # Test: create-repository with JSON data
    def test_create_repository_json(self):
        if not self.real_server:
            self.skip_test("create-repository command (JSON)", "DRY RUN")
            return

        self.run_test("pulp-tool create-repository --json-data")
        repo_name = self.bid(REPO_CREATE_REPOSITORY_JSON)
        base_path = self.bpath(BASE_PATH_CREATE_REPOSITORY_JSON)
        json_input = json.dumps(
            {
                "name": repo_name,
                "packages": [
                    {
                        "pulp_href": f"/api/pulp/{self.namespace}/api/v3/content/rpm/packages/019e1c81-1484-7e7c-86ca-d15f04a2fd0a/"  # noqa: E501
                    },
                    {
                        "pulp_href": f"/api/pulp/{self.namespace}/api/v3/content/rpm/packages/019e1c81-0c04-7fae-95af-b91bd0156139/"  # noqa: E501
                    },
                ],
                "repository_options": {"autopublish": True},
                "distribution_options": {"name": repo_name, "base_path": base_path},
            }
        )

        cmd = ["pulp-tool", "--config", str(self.config_file), "create-repository", "--json-data", json_input]
        exit_code, output = self.run_command(cmd)
        self.assert_exit_code(0, exit_code, "Create-repository with JSON completes successfully")
        if exit_code > 0:
            self.log_error(output)

    # Test: environment variable support
    def test_environment_variables(self):
        self.run_test("Environment: PULP_TOOL_JSON_LOG")
        env = os.environ.copy()
        env["PULP_TOOL_JSON_LOG"] = "1"

        exit_code = subprocess.run(
            ["pulp-tool", "upload", "--help"], capture_output=True, text=True, env=env
        ).returncode
        self.assert_exit_code(0, exit_code, "JSON logging env var accepted")

        self.run_test("Environment: SSL_CERT_FILE")
        ssl_cert_file = self.test_dir / "fake-cert.pem"
        ssl_cert_file.touch()
        env = os.environ.copy()
        env["SSL_CERT_FILE"] = str(ssl_cert_file)

        exit_code = subprocess.run(
            ["pulp-tool", "upload", "--help"], capture_output=True, text=True, env=env
        ).returncode
        self.assert_exit_code(0, exit_code, "SSL_CERT_FILE env var accepted")

    # Test: JSON output format
    def test_json_output(self):
        if not self.real_server:
            self.skip_test("JSON output validation", "DRY RUN")
            return

        self.run_test("JSON output format (search-by)")
        cmd = [
            "pulp-tool",
            "--config",
            str(self.config_file),
            "search-by",
            "--checksums",
            "3eb28dc3c8beb2082fb12c894e8b8dc8af050869725f170871ff5b96cd88ca79",
        ]
        exit_code, output = self.run_command(cmd)

        # Try to parse as JSON
        try:
            json.loads(output)
            self.log_success("Search-by outputs valid JSON")
            self.stats.passed += 1
        except json.JSONDecodeError:
            self.log_error("JSON validation failed")
            self.stats.failed += 1

    def run_all_tests(self):
        """Run all test methods"""
        print("=" * 60)
        print("  pulp-tool End-to-End Test Suite")
        print("=" * 60)
        print()

        # Check if pulp-tool is available
        if shutil.which("pulp-tool") is None:
            self.log_error("pulp-tool command not found. Install with: pip install -e .")
            sys.exit(1)

        self.log_info(f"pulp-tool location: {shutil.which('pulp-tool')}")
        self.log_info(f"Config file: {self.config_file}")
        self.log_info(f"RPM directory: {self.rpm_dir_arg}")
        self.log_info(f"Real server mode: {self.real_server}")
        self.log_info(f"Dry run mode: {self.dry_run}")
        if self.real_server:
            self.log_info(f"Skip distribution verify: {self.skip_distribution_verify}")
        print()

        # Setup
        if not self.skip_setup:
            self.setup_test_env()
        else:
            if self.test_dir_arg is not None:
                self.test_dir = self.test_dir_arg
            else:
                self.test_dir = Path.cwd()
            self.log_info("Skipping test environment setup")
        self.log_info(f"Test directory: {self.test_dir}")
        if self.run_id:
            self.log_info(f"E2e run id: {self.run_id} (build-scoped Pulp resources are suffixed)")
        else:
            self.log_info("E2e run id: (none — legacy unsuffixed build-scoped resource names)")

        print()
        print("Running tests...")
        print("=" * 60)

        self.begin_section("CLI help and usage", description="Smoke-test --help output for each command.")
        self.invoke_test_case(self.test_help_commands, "test_help_commands", "Verify pulp-tool --help and --version.")
        self.invoke_test_case(self.test_upload_help, "test_upload_help", "Verify pulp-tool upload --help.")
        self.invoke_test_case(
            self.test_upload_build_help,
            "test_upload_build_help",
            "Verify pulp-tool upload-build --help.",
        )
        self.invoke_test_case(
            self.test_upload_files_help,
            "test_upload_files_help",
            "Verify pulp-tool upload-files --help.",
        )
        self.invoke_test_case(self.test_pull_help, "test_pull_help", "Verify pulp-tool pull --help.")
        self.invoke_test_case(self.test_search_by_help, "test_search_by_help", "Verify pulp-tool search-by --help.")
        self.invoke_test_case(
            self.test_create_repository_help,
            "test_create_repository_help",
            "Verify pulp-tool create-repository --help.",
        )

        self.begin_section("Global CLI options", description="Config path and debug flag handling.")
        self.invoke_test_case(self.test_global_options, "test_global_options", "Validate --config and debug flags.")

        self.begin_section(
            "CLI validation (error paths)",
            description="Non-zero exits for invalid flags; no Pulp mutations.",
        )
        self.invoke_test_case(
            self.test_cli_validation_errors,
            "test_cli_validation_errors",
            "Pull/upload/search-by CLI guards and missing required options.",
        )

        self.begin_section(
            "Upload (pulp-tool upload)",
            description="RPM/SBOM upload paths; cases marked live Pulp mutate the shared test domain.",
        )
        self.invoke_test_case(
            self.test_upload_minimal,
            "test_upload_minimal",
            f"Minimal upload (RPM dir 0); build_id={self.bid(BUILD_ID_UPLOAD_MINIMAL)}.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_upload_full,
            "test_upload_full",
            f"Full upload with SBOM, signed RPMs, Konflux --artifact-results + --oci-storage "
            f"(pulp-content verify deferred); build_id={self.bid(BUILD_ID_UPLOAD_FULL)}.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_upload_results_json,
            "test_upload_results_json",
            f"Upload from --results-json (RPM dir 2/noarch); build_id={self.bid(BUILD_ID_UPLOAD_RESULTS)}.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_upload_target_arch_repo,
            "test_upload_target_arch_repo",
            f"Per-arch RPM repos (--target-arch-repo); build_id={self.bid(BUILD_ID_UPLOAD_TARGET_ARCH)}.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_upload_large_rpm,
            "test_upload_large_rpm",
            f"Large RPM upload (>300 MiB) and search-by checksum; build_id={self.bid(BUILD_ID_UPLOAD_LARGE)}.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_upload_build_oras_publish,
            "test_upload_build_oras_publish",
            f"upload-build ORAS publish (build_id={self.bid(BUILD_ID_UPLOAD_ORAS)}; requires --oci-storage and oras).",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_update_build_oras_live,
            "test_update_build_oras_live",
            f"update-build ORAS mutation (build_id={self.bid(BUILD_ID_UPDATE_BUILD)}; "
            "requires --oci-storage and oras).",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_update_build_replaced_rpm_checksum,
            "test_update_build_replaced_rpm_checksum",
            f"update-build with replaced RPM SHA256 (build_id={self.bid(BUILD_ID_UPDATE_BUILD_REPLACED)}; "
            "requires --oci-storage and oras).",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_upload_files,
            "test_upload_files",
            f"Upload RPM, logs, SBOM, and arbitrary file (RPM dir 4); build_id={self.bid(BUILD_ID_UPLOAD_FILES)}.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_upload_side_tag_transfer_source,
            "test_upload_side_tag_transfer_source",
            f"Upload source for side-tag HTTPS pull; build_id={self.bid(BUILD_ID_PULL_SIDE_TAG)}.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_upload_side_tag_oci_source,
            "test_upload_side_tag_oci_source",
            f"upload-build ORAS source for side-tag OCI pull; build_id={self.bid(BUILD_ID_PULL_SIDE_TAG_OCI)}.",
            requires_real_server=True,
        )

        self.run_distribution_verification_phase()

        self.begin_section("Pull (pulp-tool pull)", description="Download artifacts after pulp-content verification.")
        self.invoke_test_case(
            self.test_upload_build_update_build_pull_pipeline,
            "test_upload_build_update_build_pull_pipeline",
            f"upload-build → update-build → pull (build_id={self.bid(BUILD_ID_UPDATE_BUILD_PULL)}; "
            "subject discover + Tekton artifact-results; requires --oci-storage and oras).",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_pull_artifact_location_oci_manifest_ref,
            "test_pull_artifact_location_oci_manifest_ref",
            "pull --artifact-location OCI manifest@digest (no build-id/namespace; pulp-tool ORAS-pulls JSON).",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_pull_by_build_id,
            "test_pull_by_build_id",
            "Pull by --build-id test-fixture (fixture content in shared Pulp domain).",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_pull_side_tag_transfer_from_oci_artifact_location,
            "test_pull_side_tag_transfer_from_oci_artifact_location",
            "Side-tag pull with --artifact-location OCI ref + PULP-IMAGE_* Tekton result files.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_pull_side_tag_transfer,
            "test_pull_side_tag_transfer",
            f"Pull --transfer-dest --side-tag with ORAS (build_id={self.bid(BUILD_ID_PULL_SIDE_TAG)}; "
            "requires --oci-storage and oras in PATH).",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_pull_by_artifact_location,
            "test_pull_by_artifact_location",
            f"Pull via --artifact-location fixture ({self.pulp_results.name}).",
            requires_real_server=True,
        )

        self.begin_section(
            "Live read-only errors",
            description="Real auth/HTTP/registry failures without new Pulp repositories.",
        )
        self.invoke_test_case(
            self.test_live_readonly_errors,
            "test_live_readonly_errors",
            "404 pulp_results, missing pull auth, invalid search-by checksum, invalid pull content-types.",
            requires_real_server=True,
        )

        self.begin_section("Search (pulp-tool search-by)")
        self.invoke_test_case(
            self.test_search_by_checksums,
            "test_search_by_checksums",
            "Search RPM packages by SHA256 checksum list.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_search_by_filenames,
            "test_search_by_filenames",
            "Search RPM packages by filename list.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_search_by_signed_by,
            "test_search_by_signed_by",
            "Search RPM packages by signed_by label.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_search_by_results_json,
            "test_search_by_results_json",
            "Filter search-by output using --results-json.",
            requires_real_server=True,
        )

        self.begin_section("Create repository (pulp-tool create-repository)")
        self.invoke_test_case(
            self.test_create_repository,
            "test_create_repository",
            f"Create RPM repo from CLI flags; base_path={self.bpath(BASE_PATH_CREATE_REPOSITORY)}.",
            requires_real_server=True,
        )
        self.invoke_test_case(
            self.test_create_repository_json,
            "test_create_repository_json",
            f"Create RPM repo from --json-data; base_path={self.bpath(BASE_PATH_CREATE_REPOSITORY_JSON)}.",
            requires_real_server=True,
        )

        self.begin_section(
            "Live mutating errors",
            description="Isolated failure cases with in-test Pulp cleanup.",
        )
        self.invoke_test_case(
            self.test_live_mutating_errors,
            "test_live_mutating_errors",
            "Empty rpm-path upload, bad/missing results-json, missing upload-files path, idempotent create-repository.",
            requires_real_server=True,
        )

        self.begin_section("Environment and output format")
        self.invoke_test_case(
            self.test_environment_variables,
            "test_environment_variables",
            "PULP_TOOL_JSON_LOG and SSL_CERT_FILE env vars.",
        )
        self.invoke_test_case(
            self.test_json_output,
            "test_json_output",
            "search-by JSON output shape.",
            requires_real_server=True,
        )

        # Summary
        print()
        print("=" * 60)
        print("  Test Summary")
        print("=" * 60)
        print(f"Total tests run:    {Colors.BLUE}{self.stats.run}{Colors.NC}")
        print(f"Passed:             {Colors.GREEN}{self.stats.passed}{Colors.NC}")
        print(f"Failed:             {Colors.RED}{self.stats.failed}{Colors.NC}")
        print(f"Skipped:            {Colors.YELLOW}{self.stats.skipped}{Colors.NC}")
        print()

        if self.stats.failed == 0:
            print(f"{Colors.GREEN}✓ All tests passed!{Colors.NC}")

            if self.stats.skipped > 0:
                print()
                print(f"{Colors.YELLOW}Note: {self.stats.skipped} test(s) were skipped.{Colors.NC}")
                print("To run integration tests against a real server, use:")
                print("  python scripts/e2e-tests.py --config /path/to/cli.toml --real-server")

            return 0
        else:
            print(f"{Colors.RED}✗ Some tests failed{Colors.NC}")
            return 1


def configure_e2e_logging(real_server: bool) -> None:
    """Enable INFO logs from distribution fetch helpers during live e2e runs."""
    level = logging.INFO if real_server else logging.WARNING
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(name)s: %(message)s",
        force=True,
    )


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="End-to-end test suite for pulp-tool CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
RPM Directory Structure:
  The --rpm-dir must contain numbered subdirectories (0-4) with RPM files:
    rpm-dir/
      0/  (used by upload minimal test)
      1/  (used by upload full options test)
      2/  (used by upload results-json test)
      3/  (used by upload target-arch-repo test)
      4/  (used by upload-files test)

  Each subdirectory should contain RPM files for testing.

Examples:
  # Basic test with config file (dry-run mode by default)
  python scripts/e2e-tests.py --config ~/.config/pulp/cli.toml --rpm-dir /path/to/rpms

  # Test with RPM files in dry-run mode (explicit)
  python scripts/e2e-tests.py --config ~/.config/pulp/cli.toml --rpm-dir /path/to/rpms --dry-run

  # Test against real server (disables dry-run automatically)
  python scripts/e2e-tests.py --config ~/.config/pulp/cli.toml --rpm-dir /var/workdir/results --real-server

  # Skip environment setup (if already configured)
  python scripts/e2e-tests.py --config /etc/pulp/cli.toml --rpm-dir /path/to/rpms --skip-setup
        """,
    )

    parser.add_argument("--config", type=Path, required=True, help="Path to cli.toml configuration file")
    parser.add_argument("--rpm-dir", type=Path, required=True, help="Path to directory containing RPM files")
    parser.add_argument("--pulp-results", type=Path, required=True, help="Path to test pulp_results.json file")
    parser.add_argument("--test-dir", type=Path, help="Path to store test files and results")
    parser.add_argument(
        "--run-id",
        default=None,
        help="Unique suffix for build-scoped Pulp resources (default: E2E_RUN_ID env var)",
    )
    parser.add_argument(
        "--oci-storage",
        default=None,
        help="OCI registry for ORAS e2e (Konflux ociStorage; same as pulp-tool --oci-storage)",
    )
    parser.add_argument("--skip-setup", action="store_true", help="Skip test environment setup (files, dirs)")
    parser.add_argument(
        "--skip-distribution-verify",
        action="store_true",
        help="Skip deferred pulp-content HTTP verification phase (live server only)",
    )

    # Mutually exclusive group for server mode
    server_mode = parser.add_mutually_exclusive_group()
    server_mode.add_argument(
        "--real-server", action="store_true", help="Run against real Pulp server (disables dry-run)"
    )
    server_mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run in dry-run mode (default, mutually exclusive with --real-server)",
    )

    args = parser.parse_args()

    # Validate config file exists
    if not args.config.exists():
        print(f"{Colors.RED}[FAIL]{Colors.NC} Config file not found: {args.config}")
        sys.exit(1)

    # Validate RPM directory
    if not args.rpm_dir.is_dir():
        print(f"{Colors.RED}[FAIL]{Colors.NC} RPM directory not found: {args.rpm_dir}")
        sys.exit(1)

    if not args.pulp_results.exists():
        print(f"{Colors.RED}[FAIL]{Colors.NC} Pulp-results file not found: {args.config}")
        sys.exit(1)

    # Validate RPM directory if provided
    if args.test_dir and not args.test_dir.is_dir():
        print(f"{Colors.RED}[FAIL]{Colors.NC} Test directory not found: {args.test_dir}")
        sys.exit(1)

    # Determine dry-run mode: if --real-server is used, dry-run is False
    # Otherwise, use the --dry-run flag (which defaults to True)
    dry_run = not args.real_server
    configure_e2e_logging(args.real_server)

    # Create and run test suite
    suite = E2ETestSuite(
        config_file=args.config.resolve(),
        rpm_dir=args.rpm_dir.resolve(),
        pulp_results=args.pulp_results.resolve(),
        test_dir=args.test_dir.resolve() if args.test_dir else None,
        skip_setup=args.skip_setup,
        real_server=args.real_server,
        dry_run=dry_run,
        run_id=args.run_id,
        oci_storage=args.oci_storage,
        skip_distribution_verify=args.skip_distribution_verify,
    )

    try:
        exit_code = suite.run_all_tests()
    finally:
        if not args.test_dir:
            suite.cleanup_test_env()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
