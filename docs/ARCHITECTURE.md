# Architecture (pulp-tool)

Living overview of **system design, boundaries, and constraints**.

Complements [README.md](../README.md) (users), [AGENTS.md](../AGENTS.md) (agents: start with **Bootstrap**), and [CLAUDE.md](../CLAUDE.md) (Tekton flags and paths). Detailed CLI flags: [cli-reference.md](cli-reference.md).

Template inspiration: [architecture.md](https://architecture.md/) · examples: [awesome-architecture-md](https://github.com/noahbald/awesome-architecture-md).

---

## 1. Repository overview

**pulp-tool** is a Python **library and Click CLI** that talks to a **[Pulp](https://pulpproject.org/)** instance over HTTP (RPM/file content, repositories, uploads, pulls). It is used **interactively** and **inside Konflux** (Tekton) steps to push build artifacts and write metadata consumed by downstream automation.

**Where it fits:** Artifact storage and CI integration for builds that land in Pulp-backed distributions—not a Brew/dist-git/Errata Tool component. Those systems are outside this repo; this client assumes a reachable Pulp API and (in Konflux) Tekton-staged workspaces.

---

## 2. High-level diagram

```mermaid
flowchart TB
  subgraph s1["Entry"]
    CLI["pulp-tool CLI (Click)"]
    EP["Entry: pulp_tool.cli:main"]
  end
  subgraph s2["Orchestration"]
    PH["PulpHelper"]
    UO["UploadOrchestrator"]
    US["UploadService / upload_collect"]
  end
  subgraph s3["HTTP"]
    PC["PulpClient (httpx)"]
  end
  subgraph s4["External"]
    PulpAPI["Pulp REST API"]
  end
  subgraph s5["Konflux"]
    T1["import-to-quay"]
    T2["push-artifacts-to-storage"]
  end
  CLI --> EP --> PH
  PH --> UO
  UO --> US
  PH --> PC --> PulpAPI
  T1 --> CLI
  T2 --> CLI
```

**Upload data path:** CLI → `PulpHelper.setup_repositories` / `process_uploads` → `UploadOrchestrator` + `upload_service` / `upload_collect` → `PulpClient` → Pulp.

**Konflux:** Tasks invoke the same CLI with mounted config and `/var/workdir/results`; see [CLAUDE.md](../CLAUDE.md) for exact flags and guardrails.

---

## 3. Core components (code map)

| Layer | Path | Role |
|-------|------|------|
| CLI | `pulp_tool/cli/` | `upload`, `upload_files`, `pull`, `search_by`, `create_repository`; shared globals (`--config`, `--build-id`, `--namespace`, `--debug`, `--max-workers`) |
| HTTP client | `pulp_tool/api/pulp_client/` | Session, chunked GET, RPM/content queries, repository ops |
| Other API surface | `pulp_tool/api/` (`artifacts/`, `content/`, `distributions/`, `repositories/`, `tasks/`) | Typed calls aligned with Pulp endpoints |
| Orchestration | `pulp_tool/utils/pulp_helper.py`, `upload_orchestrator.py` | Repo setup, upload pipelines |
| Services | `pulp_tool/services/upload_service.py`, `upload_collect.py` | Same flows as CLI; Konflux results JSON, SBOM, artifact results |
| Pull | `pulp_tool/pull/` | Download / transfer helpers; optional `--side-tag` ROK promotion (`side_tag.py`, `publish.py`) |
| Results document | `pulp_tool/utils/pulp_results_document.py` | Versioned `pulp_results.json` merge (`version`, `href_history`, `oci_manifest_history`, per-artifact `distributions`) |
| Snapshot update | `pulp_tool/utils/snapshot_update.py` | Release snapshot `pulpResultsOciManifest` after side-tag ORAS publish (trusted-artifact workspace) |
| ORAS results sync | `pulp_tool/utils/pulp_results_oci_publish.py` | Shared Pulp + ORAS publish for `upload-build` and pull side-tag |
| Models | `pulp_tool/models/` | Pydantic: context, Pulp DTOs, results |
| Utils | `pulp_tool/utils/` | Validation, logging, RPM helpers, session retries |
| Container | `Dockerfile`, `.tekton/pulp-tool-container-build-*.yaml` | Konflux Tekton → upstream `docker-build-oci-ta` (`buildah-oci-ta`); **changing-pulp-container** skill + [reference.md](../skills/changing-pulp-container/reference.md) |
| Tests | `tests/` (see [tests/README.md](../tests/README.md)), `tests/support/` | Fixtures, TLS helpers |

**Invariant:** `UploadService` delegates to **`PulpHelper`**; do not maintain a second upload implementation.

---

## 4. Data and configuration

| Kind | Location / system |
|------|-------------------|
| **Remote content & metadata** | Pulp server (repositories, distributions, RPM/file units, tasks) |
| **Credentials & base URL** | **`pulp-access` secret** from [pulp-access-controller](https://github.com/pulp/pulp-access-controller) (primary in Konflux): `cli.toml` + auth material; controller-managed [terms-based registry](https://access.redhat.com/terms-based-registry/accounts) credentials (not user-provisioned). Local/manual `cli.toml` or base64 via `--config`; env: TLS, proxy vars (see [README § Setup](../README.md#setup)) |
| **Local inputs** | RPM trees, logs, SBOM files, `pulp_results.json` / results JSON for batch upload |
| **Tekton workspace** | `/var/workdir/results`, optional `oras-staging/` (SBOM merge path in import-to-quay) |

No application database: state is on Pulp and in generated JSON artifacts.

---

## 5. External integrations

| System | Role |
|--------|------|
| **Pulp** | Primary API; plugins (e.g. RPM) assumed per deployment |
| **[pulp-access-controller](https://github.com/pulp/pulp-access-controller)** | Konflux operator: `PulpAccessRequest` → `pulp-access` secret (`cli.toml`, domain `konflux-<namespace>`); uses [terms-based registry](https://access.redhat.com/terms-based-registry/accounts) for credentials (controller-generated, not manual user setup) |
| **Konflux / Tekton** | Runs `pulp-tool` in `import-to-quay` and `push-artifacts-to-storage` (different config mounts and flags) |
| **Container registry** | Quay image for tooling (`pulp-tool-container`); ORAS publish uses `select-oci-auth` + Tekton-injected `~/.docker/config.json` (same pattern as import-to-quay Quay push); details in [CLAUDE.md](../CLAUDE.md) |
| **OAuth / Basic** | Auth modes supported via client config (see [README](../README.md) / Pulp docs) |

---

## 6. Architecture invariants

1. **Single orchestration path** to production upload behavior: CLI and `UploadService` go through `PulpHelper` / shared helpers.
2. **Konflux contracts** (flags, paths, skip-vs-fail) must stay aligned with linked upstream task YAMLs when changing `upload` or the image.
3. **Labels and APIs:** Pulpcore forbids `,`, `(`, and `)` in label **values**; `signed_by` replaces `,` with `:` and maps parentheses to `[` / `]` before upload and before RPM queries, so `pulp_label_select` is usually applied server-side together with checksum or NVR filters. Client-side label matching remains a fallback when a query cannot be expressed safely.
4. **Merge gate:** PR diffs require **100% diff coverage** (`make test-diff-coverage`), not only line coverage in unchanged code.

---

## 7. Key design decisions

Formal records: [ADR 0000 — how we record decisions](adr/0000-record-architecture-decisions.md); other ADRs live under [docs/adr/](adr/). Examples in-repo: Python 3.12 (CI, container image on UBI 10), httpx. High level:

- **httpx** for HTTP (async-capable client, retries for transient errors in session layer).
- **Click** for CLI; optional plugin entry points for command discovery.
- **Pydantic v2** for models and validation.

---

## 8. Known concerns / technical debt

- **Upstream pipeline drift:** Tekton tasks and workspace layout (ORAS, `oras-staging/`) can change; [CLAUDE.md](../CLAUDE.md) must be refreshed when call sites move.
- **Pagination / broad queries:** Fallback paths that list RPM content and filter client-side can be heavier on large Pulp instances—monitor performance if extended.
- **Complex `q` filters:** Pulp enforces expression complexity limits; client code chunks queries accordingly.

---

## 9. Deployment and operations

| Mode | How it runs |
|------|----------------|
| **Local / automation** | `pip install` / `pip install -e .`; `pulp-tool` on PATH |
| **Konflux** | Container image from `.tekton/` build; read-only mounts for config and workspace |
| **Scale** | Client-side concurrency (`--max-workers`); bounded by Pulp API and network |

---

## 10. Security (high level)

- **Secrets:** Never commit; Konflux uses controller-generated **`pulp-access`** / **`rok-access`** mounts (see [pulp-access-controller](https://github.com/pulp/pulp-access-controller)); local dev uses `cli.toml` outside VCS.
- **TLS:** HTTPS with certificate verification enabled; cert/key or username/password for distribution pull; see [README § Setup](../README.md#setup) and [cli-reference.md](cli-reference.md).
- **RBAC:** Pulp server enforces access; content labeling may require `core.content_labeler` (Pulp docs).

---

## 11. Development and testing

- **Setup:** [CONTRIBUTING.md](../CONTRIBUTING.md); `make install-dev` and the full command list live in [README.md § Development](../README.md#development).
- **Tests:** `pytest`, `make test`, `make test-diff-coverage` (after `git fetch origin` for PR-style diff coverage).
- **Quality:** Ruff (lint + format, S ruleset), Pylint (errors only), Mypy; yamllint, ShellCheck, hadolint, codespell, pip-audit, and Checkton in CI; `make pre-commit-ci` or `pre-commit run --all-files` plus pre-push stage (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

---

## 12. Glossary

| Term | Meaning |
|------|---------|
| **Pulp** | Open-source repository management; REST API for content and publications |
| **Konflux** | Kubernetes-native CI/CD (Tekton) platform; see [konflux-ci.dev](https://konflux-ci.dev/docs/) |
| **PRN / pulp_href** | Pulp resource identifiers in API responses |
| **pkgId** | RPM content id (often SHA256) used in list filters |
| **pulp_label_select** | Pulp query parameter for JSON labels; commas in values have parser limitations |
| **SBOM** | Software bill of materials file path in upload flows |
| **`pulp_results.json`** | Aggregated artifact metadata JSON produced/consumed by uploads |

---

## 13. Project identification

**Repository:** pulp-tool · **Python package:** `pulp_tool` · **CLI:** `pulp-tool`

Keep this document current when adding major packages, changing Konflux boundaries, or revising upload/pull flows.
