# Pulp Tool

[![codecov](https://codecov.io/gh/konflux/pulp-tool/branch/main/graph/badge.svg)](https://codecov.io/gh/konflux/pulp-tool)

A Python client for Pulp API operations including RPM and file management.

## Overview

Pulp Tool provides a comprehensive, modern Python client for interacting with Pulp API to manage RPM repositories, file repositories, and content uploads with OAuth2 authentication. Built on a foundation of httpx, Pydantic, and Click, this package delivers type-safe, robust operations for Red Hat's Pulp infrastructure with support for uploading, downloading, and managing various types of artifacts.

The package emphasizes developer experience with comprehensive type safety, intuitive CLI commands, and a modular architecture that makes it easy to integrate into automated workflows.

## Installation
```

### From Source

```bash
git clone https://github.com/konflux/pulp-tool.git
cd pulp-tool
pip install -e .
```

### Development Installation

```bash
git clone https://github.com/konflux/pulp-tool.git
cd pulp-tool
pip install -e ".[dev]"
```

## Quick Start

### Using the CLI

The `pulp-tool` command provides a modern Click-based CLI with subcommands:

#### Upload RPMs and Artifacts

```bash
pulp-tool upload \
  --build-id my-build-123 \
  --namespace my-namespace \
  --parent-package my-package \
  --rpm-path /path/to/rpms \
  --sbom-path /path/to/sbom.json \
  --config ~/.config/pulp/cli.toml
```

#### Download Artifacts

```bash
pulp-tool transfer \
  --artifact-location /path/to/artifacts.json \
  --cert-path /path/to/cert.pem \
  --key-path /path/to/key.pem \
  --config ~/.config/pulp/cli.toml
```

#### Download Repository Configuration File

```bash
# No config file needed! Use base_url and namespace directly
pulp-tool get-repo-md \
  --base-url https://pulp.example.com \
  --namespace my-tenant \
  --build-id my-build-123 \
  --repo_type rpms
```

#### Get Help

```bash
pulp-tool --help              # General help
pulp-tool upload --help       # Upload command help
pulp-tool transfer --help     # Transfer command help
pulp-tool get-repo-md --help  # Get repo config help
pulp-tool --version           # Show version
```

### Using the Python API

#### Direct Client Usage

```python
from pulp_tool import PulpClient, PulpHelper
from pulp_tool.models import RepositoryRefs

# Create a client from configuration file (uses httpx under the hood)
client = PulpClient.create_from_config_file(path="~/.config/pulp/cli.toml")

try:
    # Use the helper for high-level operations
    helper = PulpHelper(client)
    repositories: RepositoryRefs = helper.setup_repositories("my-build-123")

    # Upload content - client handles authentication automatically
    artifact_href = client.upload_content(
        "/path/to/package.rpm",
        {"build_id": "my-build-123", "arch": "x86_64"},
        file_type="rpm",
        arch="x86_64"
    )

    # Add to repository using Pydantic-validated data
    client.add_content(repositories.rpms_href, [artifact_href])
finally:
    # Always close the client to clean up resources
    client.close()
```

#### Working with Pydantic Models

The package uses Pydantic for type-safe data handling:

```python
from pulp_tool.models import (
    RepositoryRefs,
    UploadContext,
    TransferContext,
    ArtifactMetadata,
    PulpResultsModel
)

# Context objects for type-safe parameter passing
upload_ctx = UploadContext(
    build_id="my-build-123",
    namespace="my-namespace",
    parent_package="my-package",
    rpm_path="/path/to/rpms",
    sbom_path="/path/to/sbom.json",
    config="~/.config/pulp/cli.toml",
    debug=1
)

# Models provide validation and IDE autocomplete
print(upload_ctx.build_id)  # Type-safe access
```

#### Distribution Client for Downloads

```python
from pulp_tool import DistributionClient

# Initialize with certificate authentication
dist_client = DistributionClient(
    cert_path="/path/to/cert.pem",
    key_path="/path/to/key.pem"
)

# Download artifacts from Pulp distributions
response = dist_client.pull_artifact("https://pulp.example.com/path/to/artifact.rpm")
with open("artifact.rpm", "wb") as f:
    f.write(response.content)
```

#### Programmatic CLI Usage

You can invoke the Click-based CLI programmatically:

```python
from pulp_tool import cli_main

# Call with custom arguments (uses Click command parsing)
import sys
sys.argv = ['pulp-tool', 'upload',
            '--build-id', 'test',
            '--namespace', 'ns',
            '--parent-package', 'pkg',
            '--rpm-path', '/path',
            '--sbom-path', '/path/sbom.json']
cli_main()
```

## Configuration

### Pulp CLI Configuration

Create a configuration file at `~/.config/pulp/cli.toml`:

```toml
[cli]
base_url = "https://your-pulp-instance.com"
api_root = "/pulp/api/v3"
client_id = "your-client-id"
client_secret = "your-client-secret"
domain = "your-domain"
verify_ssl = true
format = "json"
dry_run = false
timeout = 0
verbose = 0
```

### Certificate Configuration (Optional)

For distribution access, you may need a certificate configuration file:

```toml
[cli]
base_url = "https://your-pulp-instance.com"
api_root = "/pulp/api/v3"
cert = "path/to/cert"
key = "path/to/key"
domain = "your-domain"
verify_ssl = true
format = "json"
dry_run = false
timeout = 0
verbose = 0
```

## CLI Reference

The `pulp-tool` command provides a modern Click-based interface with three main subcommands: `upload`, `transfer`, and `get-repo-md`.

### Upload Command

Upload RPM packages, logs, and SBOM files to Pulp repositories.

**Required Arguments:**
- `--build-id`: Unique build identifier for organizing content
- `--namespace`: Namespace for the build (e.g., organization or project name)
- `--parent-package`: Parent package name
- `--rpm-path`: Path to directory containing RPM files
- `--sbom-path`: Path to SBOM file

**Optional Arguments:**
- `--config`: Path to Pulp CLI config file (default: `~/.config/pulp/cli.toml`)
- `--cert-config`: Path to certificate config file for base URL construction
- `--artifact-results`: Comma-separated paths for Konflux artifact results (url_path,digest_path)
- `--sbom-results`: Path to write SBOM results
- `-d, --debug`: Increase verbosity (use `-d` for INFO, `-dd` for DEBUG, `-ddd` for DEBUG with HTTP logs)

**Example:**
```bash
# Basic upload
pulp-tool upload \
  --build-id konflux-build-12345 \
  --namespace konflux-team \
  --parent-package my-application \
  --rpm-path ./build/rpms \
  --sbom-path ./build/sbom.json \
  -dd  # DEBUG level logging

# With result file outputs
pulp-tool upload \
  --build-id konflux-build-12345 \
  --namespace konflux-team \
  --parent-package my-application \
  --rpm-path ./build/rpms \
  --sbom-path ./build/sbom.json \
  --sbom-results ./sbom_url.txt \
  --artifact-results ./artifact_url.txt,./artifact_digest.txt
```

### Transfer Command

Download artifacts from Pulp distributions and optionally re-upload to Pulp repositories.

**Required Arguments:**
- `--artifact-location`: Path to local artifact metadata JSON file or HTTP URL

**Optional Arguments (conditionally required):**
- `--cert-path`: Path to SSL certificate file for authentication (required for remote URLs)
- `--key-path`: Path to SSL private key file for authentication (required for remote URLs)
- `--config`: Path to Pulp CLI config file (if supplied, will transfer to this config domain)
- `--build-id`: Build ID for naming repositories (default: extracted from artifact labels)
- `--max-workers`: Maximum number of concurrent download threads (default: 4)
- `-d, --debug`: Increase verbosity (use `-d` for INFO, `-dd` for DEBUG, `-ddd` for DEBUG with HTTP logs)

**Example:**
```bash
pulp-tool transfer \
  --artifact-location https://example.com/artifacts.json \
  --cert-path /etc/pki/tls/certs/client.crt \
  --key-path /etc/pki/tls/private/client.key \
  --config ~/.config/pulp/cli.toml \
  --max-workers 4 \
  -dd  # DEBUG level logging
```

### Get Repo Config Command

Download `.repo` configuration file(s) from Pulp distribution(s) for use with `dnf` or `yum`. Supports downloading multiple files by providing comma-separated lists for `--build-id` and/or `--repo_type`.

**Required Arguments:**
- `--build-id`: Build identifier(s) for the repository (comma-separated for multiple)
- `--repo_type`: Repository type(s): `rpms`, `logs`, `sbom`, `artifacts` (comma-separated for multiple)

**Configuration (choose one):**
- **Option 1**: `--config` - Path to Pulp CLI config file (default: `~/.config/pulp/cli.toml`)
- **Option 2**: `--base-url` AND `--namespace` - Specify Pulp connection directly
  - `--base-url`: Pulp base URL (e.g., `https://pulp.example.com`)
  - `--namespace`: Pulp namespace/domain (e.g., `my-tenant`)

**Optional Arguments:**
- `--cert-path`: Path to SSL certificate file for authentication
- `--key-path`: Path to SSL private key file for authentication
- `--output`: Output directory for `.repo` files (default: current directory). Files named `{build_id}-{repo_type}.repo`
- `-d, --debug`: Increase verbosity (use `-d` for INFO, `-dd` for DEBUG, `-ddd` for DEBUG with HTTP logs)

**Example:**
```bash
# Using config file (default: ~/.config/pulp/cli.toml)
pulp-tool get-repo-md \
  --build-id my-build-123 \
  --repo_type rpms

# Using direct base_url and namespace (no config file needed)
pulp-tool get-repo-md \
  --base-url https://pulp.example.com \
  --namespace my-tenant \
  --build-id my-build-123 \
  --repo_type rpms

# Download multiple .repo files for one build (all repo types)
pulp-tool get-repo-md \
  --base-url https://pulp.example.com \
  --namespace my-tenant \
  --build-id my-build-123 \
  --repo_type rpms,logs,sbom

# Download .repo files for multiple builds (same repo type)
pulp-tool get-repo-md \
  --base-url https://pulp.example.com \
  --namespace my-tenant \
  --build-id build-123,build-456,build-789 \
  --repo_type rpms

# Download all combinations (3 builds × 2 repo types = 6 files)
pulp-tool get-repo-md \
  --base-url https://pulp.example.com \
  --namespace my-tenant \
  --build-id build-123,build-456,build-789 \
  --repo_type rpms,logs \
  --output /tmp/repo-files

# With certificate authentication
pulp-tool get-repo-md \
  --base-url https://pulp.example.com \
  --namespace my-tenant \
  --build-id my-build-123 \
  --repo_type rpms \
  --cert-path /path/to/cert.pem \
  --key-path /path/to/key.pem

# Install the repository configuration
sudo cp *.repo /etc/yum.repos.d/
sudo dnf install <package-name>
```

### Environment Variables

The commands respect standard environment variables for SSL/TLS and HTTP configuration:

**SSL/TLS:**
- `SSL_CERT_FILE`: Path to CA bundle for verifying SSL certificates (httpx standard)
- `SSL_CERT_DIR`: Directory containing CA certificates
- `REQUESTS_CA_BUNDLE`: Also supported for compatibility
- `CURL_CA_BUNDLE`: Alternative CA bundle path

**HTTP Configuration:**
- `HTTP_PROXY` / `HTTPS_PROXY`: Proxy server URLs (supported by httpx)
- `NO_PROXY`: Comma-separated list of hosts to exclude from proxying

**Debug:**
- Use `-d`, `-dd`, or `-ddd` flags for progressive verbosity levels

### Logging

All commands support progressive verbosity levels with the `-d` / `--debug` flag:

**Verbosity Levels:**
- No flag: `WARNING` level (errors and warnings only)
- `-d`: `INFO` level (general progress information)
- `-dd`: `DEBUG` level (detailed operation information)
- `-ddd`: `DEBUG` level with HTTP request/response logging

**Log Format:**
- Timestamp
- Log level (INFO, DEBUG, WARNING, ERROR)
- Message with context
- Progress indicators for long-running operations
- Detailed error tracebacks in debug modes

**Example:**
```bash
# Minimal output
pulp-tool upload --build-id test ...

# Progress information
pulp-tool upload --build-id test ... -d

# Detailed debugging
pulp-tool upload --build-id test ... -dd

# Full HTTP debugging
pulp-tool upload --build-id test ... -ddd
```

### Troubleshooting

#### Command not found

Ensure the package is installed and your PATH includes the installation location:

```bash
pip install -e .
# or
pip install pulp-tool
```

#### Authentication errors

Check your Pulp CLI configuration file and ensure credentials are correct:

```bash
cat ~/.config/pulp/cli.toml
```

#### SSL/TLS errors

Verify certificate paths and permissions:

```bash
ls -la /path/to/cert.pem /path/to/key.pem
```

#### Permission denied

Ensure the user has read access to source files and write access to destination:

```bash
chmod 644 /path/to/artifacts.json
chmod 600 /path/to/key.pem
```

## API Reference

### Core Components

#### PulpClient

The main client class for interacting with Pulp API. Built with httpx for modern async-capable HTTP operations and composed of specialized mixins for different operations.

**Architecture:**
- Uses mixin pattern for modular functionality
- Inherits from: `ContentManagerMixin`, `ContentQueryMixin`, `RepositoryManagerMixin`, `TaskManagerMixin`
- Automatic OAuth2 authentication with token refresh
- Context manager support for proper resource cleanup

**Key Methods:**
- `upload_content()`: Upload files to Pulp with automatic deduplication
- `create_file_content()`: Create file content artifacts
- `add_content()`: Add content to repositories
- `wait_for_finished_task()`: Wait for async operations to complete with progress tracking
- `find_content()`: Search for existing content with flexible filters
- `close()`: Clean up HTTP session and resources

**Usage:**
```python
client = PulpClient.create_from_config_file()
try:
    # Client operations
    pass
finally:
    client.close()
```

#### PulpHelper

High-level helper class for common workflow operations. Orchestrates multiple PulpClient operations.

**Key Methods:**
- `setup_repositories()`: Create or get repositories and distributions (returns `RepositoryRefs`)
- `process_uploads()`: Handle complete upload workflows with progress tracking
- `get_distribution_urls()`: Get distribution URLs for repositories

#### DistributionClient

Specialized client for downloading artifacts from Pulp distributions using certificate authentication.

**Key Methods:**
- `pull_artifact()`: Download artifacts with certificate-based authentication
- Handles SSL/TLS with client certificates
- Returns httpx Response objects

### Data Models (Pydantic)

#### API Response Models (`pulp_tool.models.pulp_api`)

- `TaskResponse`: Pulp task status and results
- `RepositoryResponse`: Repository metadata
- `DistributionResponse`: Distribution configuration
- `ContentResponse`: Content unit information
- `RpmPackageResponse`: RPM-specific metadata
- `FileResponse`: File content metadata
- `OAuthTokenResponse`: OAuth token data

#### Domain Models (`pulp_tool.models`)

- `RepositoryRefs`: References to repositories (rpms_href, logs_href, sbom_href, etc.)
- `UploadContext`: Type-safe context for upload operations
- `TransferContext`: Type-safe context for transfer operations
- `ArtifactMetadata`: Artifact metadata with labels and digests
- `PulpResultsModel`: Unified upload tracking and results building
- `PulledArtifacts`: Downloaded artifact organization

### Mixins

The PulpClient is composed of specialized mixins for different operations:

- `ContentManagerMixin`: Content upload and management operations
- `ContentQueryMixin`: Content search and filtering
- `RepositoryManagerMixin`: Repository and distribution management
- `TaskManagerMixin`: Asynchronous task monitoring and management

## Development

### Setting Up Development Environment

```bash
git clone https://github.com/konflux/pulp-tool.git
cd pulp-tool
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/test_cli.py

# Run with verbose output
pytest -v

# Run specific test markers
pytest -m unit
pytest -m integration
```

### Code Coverage

Code coverage is tracked using [Codecov](https://codecov.io/gh/konflux/pulp-tool). Coverage reports are automatically uploaded to Codecov when tests run in CI.

- **Coverage Target**: 85% overall coverage
- **Diff Coverage**: 100% coverage required for new/changed lines in pull requests
- **View Coverage**: Check the [Codecov dashboard](https://codecov.io/gh/konflux/pulp-tool) for detailed coverage reports

```bash
# Generate coverage report locally
pytest --cov=pulp_tool --cov-report=html --cov-report=term

# View HTML report
open htmlcov/index.html
```

### Code Formatting

```bash
# Format code with Black
black pulp_tool/

# Check formatting without changes
black --check pulp_tool/
```

### Linting

```bash
# Pylint (should be 10.00/10)
pylint pulp_tool/

# Flake8
flake8 pulp_tool/

# Type checking with mypy
mypy pulp_tool/
```

### Building the Package

```bash
# Build distribution packages
python -m build

# Install locally for testing
pip install -e .
```

### Dependencies

**Core:**
- `httpx>=0.24.0` - Modern HTTP client
- `pydantic>=2.0.0` - Data validation
- `click>=8.0.0` - CLI framework

**Development:**
- `pytest>=6.0` - Testing framework
- `pytest-cov>=2.0` - Coverage reporting
- `black>=21.0` - Code formatting
- `flake8>=3.8` - Linting
- `mypy>=0.800` - Type checking
- `pylint>=2.8` - Code analysis

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

This project is licensed under the Apache License 2.0. See the LICENSE file for details.
