# CLI reference

Detailed command-line documentation for **pulp-tool**. For installation, configuration, and the Python API, see [README.md](../README.md). For system design and module layout, see [ARCHITECTURE.md](ARCHITECTURE.md). Maintainers: [releasing.md](releasing.md).

## Global options

These options are on the root `pulp-tool` group and apply before subcommands (see `pulp-tool --help`):

| Option | Description |
|--------|-------------|
| `--config` | Path to Pulp CLI config TOML or base64-encoded config (default: `~/.config/pulp/cli.toml`) |
| `--build-id` | Build identifier (required for some commands) |
| `--namespace` | Namespace for the build (required for some commands) |
| `-d`, `--debug` | Verbosity: `-d` INFO, `-dd` DEBUG, `-ddd` HTTP logs |
| `--max-workers` | Maximum concurrent workers for parallel operations (default: 4) |
| `--version` | Print version and exit |

## upload-build

Upload RPM packages, logs, and SBOM files for a build. When **`--oci-storage`** is passed (Tekton pipeline param `ociStorage`, as in [build-rpm-package](https://github.com/konflux-ci/rpmbuild-pipeline/blob/main/pipeline/build-rpm-package.yaml)) or `cli.oci_storage` is in `--config`, the tool ORAS-publishes `pulp_results.json` (with `oci_manifest` and `version`) so downstream `pull` / **update-build** flows share the same OCI target. With **`--artifact-results`** `url_path,digest_path` (import-to-quay `PULP-IMAGE_URL` / `PULP-IMAGE_DIGEST`), ORAS publish writes the OCI image reference **without** digest to `url_path` and `sha256:…` to `digest_path` (same pattern as Quay `IMAGE_URL` + digest in that task). Without `--oci-storage`, Konflux result files use the Pulp artifacts distribution URL and file digest (legacy). In Tekton, ORAS uses the same registry credentials as the Quay push step: service-account-linked secrets merged into `~/.docker/config.json`, adapted via **`select-oci-auth`** (shipped in **`pulp-tool-container`**).

The **`upload`** command is a deprecated alias for **`upload-build`** (Tekton tasks still call `upload` until pipelines migrate).

Requires global `--build-id` and `--namespace` unless `--results-json` is used (labels in the JSON supply context).

| Argument | Required | Description |
|----------|----------|-------------|
| `--parent-package` | No | Parent package name |
| `--rpm-path` | No | Path to RPM directory (default: current dir) |
| `--sbom-path` | No | Path to SBOM file |
| `--results-json` | No | Path to `pulp_results.json`; upload artifacts from this file (files resolved from its directory or `--files-base-path`). When used, `--build-id` and `--namespace` are optional (extracted from artifact labels in the JSON) |
| `--files-base-path` | No | Base path for resolving artifact keys to file paths (default: directory of `--results-json`; requires `--results-json`) |
| `--signed-by` | No | Add `signed_by` pulp_label and upload to separate signed repos/distributions. Pulp rejects `,`, `(`, and `)` in label values; the tool replaces `,` with `:` and `(` / `)` with `[` / `]`. Pass the same raw `--signed-by` string when using `search-by`. |
| `--overwrite` | No | RPM only: before upload, find packages in the target RPM repo by each local RPM’s NVRA filename (and `signed_by` when set) and remove them via `remove_content_units` |
| `--target-arch-repo` | No | RPM only: use each architecture as the RPM repo/distribution base path (e.g. `…/pulp-content/{namespace}/x86_64/`) instead of `{build}/rpms`; logs, SBOM, and generic artifacts stay `{build}/…`. With `--signed-by`, paths stay `{arch}/` only (`signed_by` is a label). Repos are created per arch at upload time. Works with `--results-json` |
| `--artifact-results` | No | Comma-separated paths or folder for local `pulp_results.json` |
| `--oci-storage` | No | OCI registry for ORAS publish (Konflux `ociStorage`); overrides `cli.oci_storage` in config |
| `--sbom-results` | No | Path to write SBOM results |

**Upload from results JSON:** When `--results-json` is used, artifact keys from the JSON are resolved to file paths (default: same directory as the JSON; override with `--files-base-path`). Files are classified by extension (`.rpm` → rpms, `.log` → logs, SBOM extensions → sbom, else → artifacts) and uploaded to the appropriate repository. `--rpm-path` and `--sbom-path` are ignored in this mode.

**Signed-by:** When `--signed-by` is set, a `signed_by` label is added to RPMs only, and RPMs are stored in a separate `rpms-signed` repository with its own distribution. Logs and SBOMs are never signed and always go to the standard repositories. For Pulpcore’s label rules, `,` is replaced with `:` and parentheses with `[` / `]` so typical GnuPG-style strings can be stored. Use the same raw string for `search-by --signed-by`. Quote the argument in the shell if it contains spaces.

**Overwrite:** When `--overwrite` is set, for each RPM about to be uploaded the tool searches Pulp by NVRA filename derived from the basename (same basis as `search-by --filenames`), scoped with `signed_by` when `--signed-by` is set. It keeps only matches that exist in the target RPM repository’s latest version, then calls the repository modify API with `remove_content_units` before uploading and adding the new RPMs.

**Target-arch-repo:** When `--target-arch-repo` is set, RPM repositories and distributions are named by architecture only (`{arch}`), including when `--signed-by` is set (no separate `rpms-signed` path). Published paths look like `…/pulp-content/{namespace}/{arch}/`. The aggregate `{build}/rpms` repo is not created; RPM repos are created when each arch is uploaded. `pulp_results.json` `distributions` maps string names to base URLs (sorted keys when serialized); per-arch RPM bases use keys `rpm_<arch>` (e.g. `rpm_x86_64`). Logs, SBOM, and generic artifacts still use `{build}/logs`, `{build}/sbom`, and `{build}/artifacts`.

## upload-files

Upload individual files (RPMs, logs, SBOMs, generic files).

Requires global `--build-id` and `--namespace`.

| Argument | Required | Description |
|----------|----------|-------------|
| `--parent-package` | Yes | Parent package name |
| `--rpm` / `--file` / `--log` / `--sbom` | At least one | File paths (repeatable) |
| `--arch` | No | Architecture (e.g. x86_64) |
| `--artifact-results` | No | Output paths or folder |
| `--oci-storage` | No | OCI registry for ORAS publish (Konflux `ociStorage`) |
| `--sbom-results` | No | SBOM output path |

**update-build:** Planned Konflux command for promoting builds; it will use the same **`--oci-storage`** / `ociStorage` wiring as `upload-build` to read and publish versioned `pulp_results.json` OCI targets.

## pull

Download artifacts from Pulp distributions.

Global `--build-id` and `--namespace` are required when using `--build-id` + `--namespace` instead of `--artifact-location`. Use global `--max-workers` for concurrent downloads (default: 4).

| Argument | Required | Description |
|----------|----------|-------------|
| `--artifact-location` | Yes* | Path or URL to artifact metadata JSON |
| `--build-id` + `--namespace` | Yes* | Alternative to `--artifact-location` (global options) |
| `--transfer-dest` | Conditional | Pulp config for destination upload: creates repos/distributions and re-uploads downloaded content when set |
| `--distribution-config` | No | Config file for distribution download auth (cert/key or username/password); overrides `--transfer-dest` / `--config` for auth |
| `--cert-path` / `--key-path` | Conditional | SSL cert/key (or from config) |
| `--content-types` | No | Filter: rpm, log, sbom (comma-separated) |
| `--archs` | No | Filter: x86_64, aarch64, etc. |
| `--side-tag` | Conditional | Side-tag test promotion: extra ROK RPM repo/distribution; requires `--transfer-dest` |
| `--artifact-results` | No | Optional legacy Konflux `url_path,digest_path` Tekton result files (not required for ORAS publish) |
| `--oci-storage` | Conditional | OCI registry for ORAS publish (Konflux `ociStorage`); overrides `cli.oci_storage` in `--transfer-dest` |
| `--snapshot-path` | No | Konflux release snapshot JSON in the trusted-artifact workspace; sets `pulpResultsOciManifest` after ORAS publish |

\* Use `--artifact-location` OR global `--build-id` + `--namespace`. For remote URLs, provide cert/key **or** username/password via `--distribution-config`, `--transfer-dest`, `--config`, or explicit cert/key flags.

**ORAS-published `pulp_results.json`:** After **`upload-build`** (or side-tag transfer) with **`--oci-storage`**, the authoritative metadata lives in the registry as an OCI artifact (`oci_manifest` on the Pulp copy, or Konflux **`PULP-IMAGE_URL`** + **`PULP-IMAGE_DIGEST`** Tekton results from **`--artifact-results`**). **`pull --artifact-location`** accepts:

- a local file path,
- a Pulp content **HTTPS** URL, or
- an **OCI manifest ref** (`quay.io/org/repo@sha256:…` or Konflux-style `oci:…@sha256:…`).

For OCI refs, **`pulp-tool`** ORAS-pulls `pulp_results.json` internally ( **`select-oci-auth`** + **`oras --registry-config`**, same as [import-to-quay](https://github.com/konflux-ci/rpmbuild-pipeline/blob/main/task/import-to-quay.yaml); shipped in **`pulp-tool-container`**). RPM/SBOM downloads inside the JSON still use Pulp distribution auth from **`--config`** / **`--distribution-config`**.

```bash
# update-build style: pass the manifest ref from oci_manifest or Tekton PULP-IMAGE_* results
OCI_REF='quay.io/org/build-artifacts@sha256:abc…'

pulp-tool --config /pulp-access/cli.toml pull \
  --artifact-location "${OCI_REF}" \
  --content-types rpm,sbom \
  --archs x86_64,noarch
```

You can still ORAS-pull manually and pass the local `pulp_results.json` path if preferred.

For transfer to another Pulp domain, add **`--transfer-dest`** (and **`--side-tag`** / **`--oci-storage`** when promoting test builds).

**Transfer behavior:** Destination repository creation and re-upload run **only** when `--transfer-dest` is set. Group-level `--config` alone supplies auth (and `base_url` for `--build-id` + `--namespace`) but does not create destination repos or upload.

**Side-tag transfer (`--side-tag`):** Mainline transfer is unchanged. When `--side-tag` is set, RPMs are also uploaded to an extra repository with distribution base path `side-tag-<name>`, `pulp_results.json` is versioned (href/distribution lineage), ORAS-pushed using **`--oci-storage`** or `cli.oci_storage` in **`--transfer-dest`** (including a second push after `oci_manifest` is set, then a final Pulp upload aligned with the registry digest). **`--artifact-results`** writes Tekton OCI URL/digest files (ORAS manifest ref split like `PULP-IMAGE_*`); optional **`--snapshot-path`** updates release snapshot JSON with `pulpResultsOciManifest` so a following Tekton **`create-trusted-artifact`** step can push the workspace to `ociStorage` (same pattern as [upload-src-rpm-sbom-attestation](https://github.com/konflux-ci/release-service-catalog/blob/development/tasks/managed/upload-src-rpm-sbom-attestation/upload-src-rpm-sbom-attestation.yaml)). Also set `cli.cluster` in that config for `origin_cluster` labels when absent from source JSON. The Konflux **`pulp-tool-container`** image includes the **`oras`** CLI; local environments need `oras` on `PATH` for this path.

**File layout:** RPMs/SBOMs → current folder; logs → `logs/<arch>/`.

## create-repository

Create a repository with specified packages.

| Argument | Required | Description |
|----------|----------|-------------|
| `--repository-name` | Yes* | Repository name |
| `--packages` | Yes* | Comma-separated Pulp content HREFs |
| `--base-path` | Yes* | Base path for published URL |
| `--compression-type` | No | `zstd` or `gz` |
| `--checksum-type` | No | sha256, sha384, etc. |
| `--skip-publish` | No | Disable autopublish |
| `--generate-repo-config` | No | Generate .repo files |
| `-j, --json-data` | No | JSON input (overrides CLI options) |

**JSON example:**

```bash
pulp-tool create-repository --json-data '{
  "name": "my-repo",
  "packages": [{"pulp_href": "/api/pulp/.../"}],
  "repository_options": {"autopublish": true, "checksum_type": "sha256", "compression_type": "zstd"},
  "distribution_options": {"name": "my-repo", "base_path": "my-repo/path", "generate_repo_config": true}
}'
```

## search-by

Search RPM packages in Pulp by checksum, filename, or `signed_by` label.

| Argument | Required | Description |
|----------|----------|-------------|
| `--checksums` | Conditional* | Comma-separated SHA256 checksums |
| `--filenames` | Conditional* | Comma-separated RPM filenames (e.g. `pkg-1.0-1.x86_64.rpm`) |
| `--signed-by` | No | Filter by `signed_by` label value (same substitution as `upload`) |
| `--results-json` | No | Path to `pulp_results.json` to filter (remove RPMs found in Pulp) |
| `--output-results` | Yes** | Output path for filtered `pulp_results.json` (requires `--results-json`) |
| `--checksum` | No | Extract checksums from `--results-json` (requires `--results-json`) |
| `--filename` | No | Extract filenames from `--results-json` (requires `--results-json`) |
| `--keep-files` | No | Keep logs and SBOMs in `--output-results` (default: RPM artifacts only) |

\* Direct mode: at least one of `--checksums`, `--filenames`, or `--signed-by` is required. `--checksums` and `--filenames` are mutually exclusive.

\** Required when `--results-json` is used.

Requires `--config`.

**Direct search:** Prints a JSON array of matching RPMs to stdout.

**Results-json mode:** Loads `--results-json`, searches Pulp, removes found RPMs from the artifact map, and writes `--output-results`. When neither `--checksum`/`--checksums` nor `--filename`/`--filenames` is given and `--signed-by` is absent, checksums are extracted from the file by default.

**Signed-by:** Same label substitution as `upload` (`,` → `:`, parentheses → square brackets). Quote the value in the shell if it contains spaces.

**Examples:**

```bash
pulp-tool --config ~/.config/pulp/cli.toml search-by --checksums <sha256>
pulp-tool --config ~/.config/pulp/cli.toml search-by --filenames pkg-1.0-1.x86_64.rpm
pulp-tool --config ~/.config/pulp/cli.toml search-by --signed-by key-id-123
pulp-tool --config ~/.config/pulp/cli.toml search-by \
  --results-json /path/to/pulp_results.json \
  --output-results /path/to/filtered_results.json
```

## Pulp access and credentials

### Konflux (primary)

Red Hat Pulp access in Konflux is created with the **[pulp-access-controller](https://github.com/pulp/pulp-access-controller)** operator:

1. Create a `PulpAccessRequest` in your namespace; see the [operator README](https://github.com/pulp/pulp-access-controller/blob/main/README.md) and [Konflux Pulp access guide](https://konflux-ci.dev/docs/building/pulp-access/).
2. The controller writes the **`pulp-access`** secret (`cli.toml`, TLS or Basic Auth material, and `domain` such as `konflux-<namespace>`). It integrates with Red Hat's [terms-based registry](https://access.redhat.com/terms-based-registry/accounts) for credentials—**you do not create terms-based registry credentials yourself**; the controller will generate and manage them.

Mount `cli.toml` from that secret as `--config` (Tekton often uses `/pulp-access/cli.toml`). pulp-tool reads the same `[cli]` shape the operator generates.

### Local / manual `cli.toml`

For development outside Konflux, create `~/.config/pulp/cli.toml` yourself or extract files from a `pulp-access` secret (`oc extract secret/pulp-access …`). See [Accessing Pulp content](https://konflux-ci.dev/docs/building/accessing-pulp-content/) for extracting cluster secrets.

## Environment and logging

**Environment:** `SSL_CERT_FILE`, `SSL_CERT_DIR`, `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, and `PULP_TOOL_CORRELATION_ID` are supported. Correlation ID resolution: `cli.correlation_id` in config > `PULP_TOOL_CORRELATION_ID` > `{namespace}/{build_id}` from global CLI options > `build_id` alone.

**Configuration (`[cli]`):** `base_url`, `api_root`, `domain`, OAuth (`client_id`, `client_secret`) or Basic Auth (`username`, `password`), optional client cert (`cert`, `key`), and optional `correlation_id`. SSL verification is always enabled; pulp-tool does not read pulp-cli keys such as `verify_ssl`, `dry_run`, or `timeout` from config today. Built-in HTTP timeouts: 120 seconds for most API calls; 30 minutes for multipart content uploads (RPMs, logs, SBOM files).

**Verbosity:** `-d` INFO, `-dd` DEBUG, `-ddd` HTTP logs. Default: WARNING.

**JSON logs (structured):** set `PULP_TOOL_JSON_LOG=1` (or `true` / `yes`) for newline-delimited JSON on stdout (via [python-json-logger](https://github.com/madzak/python-json-logger)); useful for aggregators. Default remains plain text.
