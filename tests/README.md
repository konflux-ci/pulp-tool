# Testing Best Practices

## Layout (mirrors `pulp_tool/`)

Tests are grouped by package area. Prefer adding new tests next to the code they exercise.

| Directory | Purpose |
|-----------|---------|
| `tests/support/` | Shared factories, TLS helpers, constants (import as `tests.support`) |
| `tests/api/` | `PulpClient` and API-layer behavior |
| `tests/cli/` | Click CLI commands (`upload`, `pull`, `search-by`, …) |
| `tests/pull/` | Pull/download flow and reporting |
| `tests/upload/` | Upload pipeline, batch JSON, artifacts, results, layout/DTO models |
| `tests/services/` | Non-upload services (pull helpers, update-build, …) |
| `tests/utils/` | Utilities, capabilities, small pure helpers |
| `tests/models/` | Pydantic models |
| `tests/e2e/` | Unit tests for [`e2e/`](../e2e/) helpers (e.g. `distribution_fetch`, `distribution_verify_queue`) |

**Konflux live e2e** (mutating Pulp in Tekton) is implemented under [`e2e/`](../e2e/), not under `tests/`. New `--real-server` cases must follow the upload → deferred pulp-content verification → pull structure documented in [e2e/README.md § Conventions for new live e2e tests](../e2e/README.md#conventions-for-new-live-e2e-tests).

## Hypothesis (property-based tests)

[Hypothesis](https://hypothesis.readthedocs.io/) is an optional dev dependency. Use it for **small, pure** functions (string parsing, mapping JSON to dicts, correlation ID rules) where randomized inputs catch edge cases without network or heavy I/O.

- **Good fit:** `resolve_correlation_id`, `sanitize_build_id_for_repository`, RPM filename parsers.
- **Avoid (for now):** Full `PulpClient` HTTP flows—model the API tightly first or tests become slow and flaky.

Property tests live alongside other tests (for example `tests/utils/test_hypothesis_properties.py`). Cap examples with `@settings(max_examples=…)`; mark unusually slow cases with `@pytest.mark.slow` if needed.

### Ghostwriter (`hypothesis write`)

Hypothesis can **generate** initial pytest-style property tests via the CLI. See the [Ghostwriter](https://hypothesis.readthedocs.io/en/latest/reference/integrations.html#ghostwriter) section of the Hypothesis docs (`hypothesis write --help` for options such as `--roundtrip`, `--equivalent`, `--idempotent`, `--except`).

- Requires **Ruff format** (the ghostwriter invokes it); run from an environment with `pip install -e ".[dev]"` so Hypothesis and dev tooling match CI.
- Example: `hypothesis write pulp_tool.utils.validation.build_id.strip_namespace_from_build_id` prints starter tests you copy into an appropriate `tests/utils/` (or similar) module, then edit.
- **Always** review output: adjust imports, strategies, and settings; do not use pytest **function-scoped** fixtures as `@given` parameters (Hypothesis will warn—use explicit setup/teardown or module-scoped fixtures per Hypothesis guidance); keep the **100% PR diff coverage** merge gate in mind.

## Temporary File Handling

All tests that create temporary files **must** clean them up properly. Follow these guidelines:

### 1. Use Built-in Fixtures (Recommended)

The easiest and safest approach is to use pytest's built-in `tmp_path` fixture or our custom fixtures:

```python
def test_with_temp_files(tmp_path):
    """pytest's tmp_path automatically cleans up."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[cli]\nbase_url = "https://pulp.example.com"')

    # File is automatically cleaned up after test
```

### 2. Use Our Custom Fixtures

Use the fixtures provided in `conftest.py`:

```python
def test_with_fixture(temp_files):
    """Uses our temp_files fixture (wraps tmp_path)."""
    my_file = temp_files / "data.json"
    my_file.write_text('{"test": true}')
    # Automatic cleanup


def test_with_factory(create_temp_file):
    """Factory fixture for multiple files."""
    config = create_temp_file("config.toml", "[cli]\nkey = value")
    data = create_temp_file("data.bin", b"binary data", binary=True)
    # Automatic cleanup
```

Available fixtures:
- `temp_files` - Provides a temporary directory (pathlib.Path)
- `create_temp_file` - Factory to create multiple temp files
- `temp_file` - Creates a single temporary text file
- `temp_rpm_file` - Creates a temporary RPM file
- `temp_dir` - Creates a temporary directory
- `temp_config` - Creates a temporary TOML config file

### 3. Manual Cleanup (When Necessary)

If you must create temp files manually (e.g., testing specific file paths), **always** use try/finally:

```python
def test_manual_cleanup():
    """Manual temp file with proper cleanup."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("test content")
        temp_path = f.name

    try:
        # Your test code here
        assert Path(temp_path).exists()
    finally:
        # Always clean up
        Path(temp_path).unlink(missing_ok=True)
```

### 4. Multiple Files Cleanup

For multiple temp files, track them in a list:

```python
def test_multiple_files():
    """Cleanup multiple temp files."""
    temp_files = []

    try:
        for i in range(3):
            with tempfile.NamedTemporaryFile(delete=False) as f:
                temp_files.append(f.name)
                f.write(f"file {i}".encode())

        # Your test code here
    finally:
        for path in temp_files:
            Path(path).unlink(missing_ok=True)
```

### 5. Safety Net

The `temp_file_cleanup` fixture (autouse, session-scoped) provides a safety net for any orphaned temp files. It automatically runs at the end of the test session.

You can also manually register files for automatic cleanup:

```python
from tests.conftest import register_temp_file, unregister_temp_file


def test_with_registration():
    temp_path = tempfile.mktemp()
    register_temp_file(temp_path)  # Safety net

    try:
        # Test code
        pass
    finally:
        Path(temp_path).unlink(missing_ok=True)
        unregister_temp_file(temp_path)  # Remove from registry
```

## CLI Testing

Use Click's `CliRunner` for testing CLI commands:

```python
from click.testing import CliRunner
from pulp_tool.cli import cli


def test_cli_command(tmp_path):
    """Test CLI with automatic cleanup."""
    runner = CliRunner()

    config_file = tmp_path / "config.toml"
    config_file.write_text('[cli]\nbase_url = "https://pulp.example.com"')

    result = runner.invoke(cli, ["upload", "--config", str(config_file), ...])
    assert result.exit_code == 0
    # tmp_path automatically cleaned up
```

## Common Pitfalls

❌ **DON'T** create temp files without cleanup:
```python
# BAD: No cleanup!
def test_bad():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        temp_path = f.name
    # File is orphaned!
```

❌ **DON'T** forget cleanup in error paths:
```python
# BAD: No cleanup if assertion fails!
def test_bad():
    temp_path = create_temp_file()
    assert something()
    cleanup(temp_path)  # Never reached if assertion fails!
```

✅ **DO** use try/finally or fixtures:
```python
# GOOD: Cleanup always happens
def test_good():
    temp_path = create_temp_file()
    try:
        assert something()
    finally:
        cleanup(temp_path)


# BETTER: Use fixtures
def test_better(tmp_path):
    temp_file = tmp_path / "test.txt"
    assert something()
    # Automatic cleanup
```

## Running Tests

```bash
# Run all tests with coverage
pytest tests/ --cov=pulp_tool --cov-report=term-missing

# Run specific test file (examples)
pytest tests/cli/test_cli_core.py -v
pytest tests/utils/test_hypothesis_properties.py -v

# Run with verbose output
pytest tests/ -vv

# Show print statements
pytest tests/ -s
```
