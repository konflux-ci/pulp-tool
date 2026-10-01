# Pulp Tool

[![Unit tests](https://github.com/konflux-ci/pulp-tool/actions/workflows/gh-action-testsuite.yaml/badge.svg)](https://github.com/konflux-ci/pulp-tool/actions/workflows/gh-action-testsuite.yaml)
[![codecov](https://codecov.io/gh/konflux-ci/pulp-tool/branch/main/graph/badge.svg)](https://codecov.io/gh/konflux-ci/pulp-tool)

A Python client for Pulp API operations including RPM and file management.

**Overview:** [Setup](#setup) · [Usage and API](#usage-and-api) · [Development](#development) · [License](#license)

## Setup

### Konflux / Red Hat Pulp access (primary)

In Konflux, Pulp access is provisioned by the **[pulp-access-controller](https://github.com/pulp/pulp-access-controller)** operator—not by hand-editing `cli.toml` or creating [terms-based registry](https://access.redhat.com/terms-based-registry/accounts) credentials yourself.

1. Create a `PulpAccessRequest` in your namespace (see the [operator README](https://github.com/pulp/pulp-access-controller/blob/main/README.md) and [Konflux: Getting access to Pulp storage](https://konflux-ci.dev/docs/building/pulp-access/)).
2. The controller creates a **`pulp-access`** secret with `cli.toml`, authentication material, and domain name (`konflux-<namespace>`). It uses Red Hat's [terms-based registry](https://access.redhat.com/terms-based-registry/accounts) for credentials—you do not create those credentials yourself; the controller generates and manages them.

Tekton tasks mount that secret (for example `/pulp-access/cli.toml`) and run `pulp-tool --config …`. See **[CLAUDE.md](docs/CLAUDE.md)** for downstream flag and path contracts.

### Local install and manual config

Clone and install:

```bash
git clone https://github.com/konflux-ci/pulp-tool.git
cd pulp-tool
pip install -e .
```

For development (dev dependencies and pre-commit):

```bash
pip install -e ".[dev]"
```

Create `~/.config/pulp/cli.toml` for **local** use when you are not consuming a controller-generated `pulp-access` secret. Use the `[cli]` keys pulp-tool reads: `base_url`, `api_root`, `domain`, OAuth (`client_id`, `client_secret`) or Basic Auth (`username`, `password`), optional client cert (`cert`, `key`), and optional `correlation_id` for `X-Correlation-ID` (or set `PULP_TOOL_CORRELATION_ID`). See [docs/cli-reference.md](docs/cli-reference.md) for access provisioning and command flags.

When `--build-id` and `--namespace` are set and no correlation id is configured, the client sends `X-Correlation-ID: {namespace}/{build_id}` (or the build id alone if namespace is omitted), similar to [pulp-cli](https://github.com/pulp/pulp-cli).

**packages.redhat.com (manual / non-Konflux):** use Basic Auth; `[cli]` can set `base_url = "https://packages.redhat.com"`, `api_root = "/api/pulp/"`, `username`, `password`, and `domain`. OAuth2 (`client_id` / `client_secret`) is also supported. For distribution pull, add `cert` and `key` paths or use username/password via `--distribution-config`. Konflux namespaces should use [pulp-access-controller](https://github.com/pulp/pulp-access-controller) instead of ad hoc config.

## Usage and API

```bash
pulp-tool --config ~/.config/pulp/cli.toml \
  --build-id my-build-123 \
  --namespace my-namespace \
  upload \
  --parent-package my-package \
  --rpm-path /path/to/rpms \
  --sbom-path /path/to/sbom.json
```

```bash
pulp-tool --config ~/.config/pulp/cli.toml \
  upload \
  --results-json /path/to/pulp_results.json \
  --signed-by key-id-123
```

```bash
pulp-tool pull \
  --artifact-location /path/to/artifacts.json \
  --transfer-dest ~/.config/pulp/cli.toml

pulp-tool --config ~/.config/pulp/cli.toml search-by --checksums <sha256>
```

```bash
pulp-tool --config ~/.config/pulp/cli.toml \
  update-build \
  --results-json quay.io/org/repo@sha256:… \
  --artifact-results /tekton/results/pulp-image-url,/tekton/results/pulp-image-digest \
  --oci-storage quay.io/org/repo:tag \
  --signed-by key-id-123
```

```bash
pulp-tool --help
pulp-tool upload --help
pulp-tool update-build --help
pulp-tool search-by --help
```

Full command tables, examples, and logging: **[docs/cli-reference.md](docs/cli-reference.md)**. The **`upload`** subcommand is a compatibility alias for **`upload-build`** (preferred in new docs and examples).

```python
from pulp_tool import PulpClient, PulpHelper
from pulp_tool.models import RepositoryRefs

client = PulpClient.create_from_config_file(path="~/.config/pulp/cli.toml")
try:
    helper = PulpHelper(client)
    repos: RepositoryRefs = helper.setup_repositories("my-build-123")

    response = client.upload_rpm_package(
        "/path/to/package.rpm",
        labels={"build_id": "my-build-123"},
        arch="x86_64",
    )
finally:
    client.close()
```

```python
from pulp_tool import DistributionClient

dist = DistributionClient(cert="/path/to/cert.pem", key="/path/to/key.pem")
dist = DistributionClient(username="user", password="pass")

metadata = dist.pull_artifact("https://pulp.example.com/artifacts.json").json()
dist.pull_data(filename="pkg.rpm", file_url="...", arch="x86_64", artifact_type="rpm")
```

**Models:** `RepositoryRefs`, `UploadContext`, `PullContext`, `ArtifactMetadata`, `PulpResultsDocument`, `PulledArtifacts`.

## Development

**Konflux / Tekton:** pulp-tool runs in RPM build (`import-to-quay`) and release (`push-artifacts-to-storage`) tasks. If you change `upload`, SBOM/artifact behavior, or the container image, read **[CLAUDE.md](docs/CLAUDE.md)** for contracts and regression checks; re-verify **konflux-ci/rpmbuild-pipeline** (`task/import-to-quay.yaml`) and **konflux-ci/release-service-catalog** (`tasks/managed/push-artifacts-to-storage/`). Pipelines evolve (e.g. ORAS or `oras-staging/`); update **CLAUDE.md** when upstream staging changes. Architecture overview: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

```bash
make install-dev          # editable install + pre-commit (+ pre-push) hooks
make format               # ruff format + ruff check --fix
make lint                 # ruff, pylint, mypy (same as CI python-lint job)
make pre-commit-ci        # all pre-commit hooks: lint + pip-audit + diff-cover + checkton
pre-commit run --all-files   # commit-stage hooks only; loop until green
make test                 # full suite + coverage (85%+ project threshold)
make test-container       # optional local Dockerfile smoke-test (Konflux Tekton builds the image on PR/push)
git fetch origin
make test-diff-coverage   # PR gate: 100% diff vs COMPARE_BRANCH (default origin/main)
make check                # lint + test
```

**Dependency lockfile:** **`uv.lock`** is generated from **`pyproject.toml`**; after changing dependencies, run `make lock`.

Before a PR, ensure `make pre-commit-ci` (or commit + pre-push pre-commit stages) and `make test` are green. For AI-assisted work see **[AGENTS.md](docs/AGENTS.md)** (start with § **Bootstrap**), **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**, and **[CLAUDE.md](docs/CLAUDE.md)** (Konflux contracts); also [CONTRIBUTING.md](CONTRIBUTING.md) and [tests/README.md](tests/README.md). **Maintainers:** release with **`make release-please`** → **`make release-publish`** → Konflux release — see **[docs/releasing.md](docs/releasing.md)**. Optional [AgentReady](https://github.com/ambient-code/agentready): `pip install agentready && agentready assess .` ([.agentready-config.yaml](.agentready-config.yaml); reports under `.agentready/`, gitignored).

**Troubleshooting**

| Issue | Check |
|-------|-------|
| Command not found | `pip install -e .` or `pip install pulp-tool` |
| Authentication errors | Verify `~/.config/pulp/cli.toml` credentials |
| SSL/TLS errors | Verify cert/key paths and permissions |
| Permission denied | Check file permissions on artifacts and key |

**Contributing:** fork, branch, change with tests, then `make test` and `make pre-commit-ci` (or `make test-diff-coverage` after `git fetch origin`), and open a pull request.

## License

Apache License 2.0. See [LICENSE](LICENSE).
