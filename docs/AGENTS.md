# Agent context (pulp-tool)

Canonical **README for AI agents** in this repo. Human-oriented setup and user docs live in [README.md](../README.md).

## Bootstrap (read first; fewer wasted context round-trips)

Do this **in order** when starting work in a **new thread** or with a **new** model:

1. **This file** — commands, conventions, and links below. In Cursor, attach **`@docs/AGENTS.md`** at session start when practical.
2. **[ARCHITECTURE.md](ARCHITECTURE.md)** — code map, mermaid flow, invariants, glossary (open if you will touch more than one area or are unfamiliar with the layout).
3. **changing-pulp-upload** + **[CLAUDE.md](CLAUDE.md)** — if changing `upload`, global CLI flags, SBOM/artifact results, or Tekton tasks that *run* pulp-tool ([`skills/changing-pulp-upload/SKILL.md`](../skills/changing-pulp-upload/SKILL.md)). **changing-pulp-container** — if changing `container/Dockerfile` or `.tekton/` image build PipelineRuns ([`skills/changing-pulp-container/SKILL.md`](../skills/changing-pulp-container/SKILL.md)).
4. **On-demand skills** — see [`.cursor/rules/llm-development-guidelines-deep.mdc`](../.cursor/rules/llm-development-guidelines-deep.mdc) (skill index) and [`skills/README.md`](../skills/README.md): PR drafting, CI troubleshooting (lint, pre-commit, diff-cover).

Do **not** read all of [CONTRIBUTING.md](../CONTRIBUTING.md) up front unless you are changing process, dependencies, or release workflow.

**Konflux (Tekton) contracts** (same as item 3): [CLAUDE.md](CLAUDE.md).

---

## Build, test, lint

Copy-paste **`make` / pre-commit** flow (`make pre-commit-ci` matches GitHub PR CI), **`make lock`** for dependencies, and PR reminders: **[README.md § Development](../README.md#development)**.

---

## Key conventions (do not skip)

1. **GitHub merge:** every changed line in a PR needs executing test coverage — run `make test-diff-coverage` (same as CI diff-cover), not only `make test`.
2. **Konflux:** never change `upload` / artifact paths / Tekton assumptions without the **changing-pulp-upload** skill, [CLAUDE.md](CLAUDE.md), and the linked task YAMLs there.
3. **Documentation:** Keep **relevant** in-repo docs and core `.md` files in sync with your change in the **same PR** (do not leave stale references):
   - **CLI** (`pulp_tool/cli/`): [cli-reference.md](cli-reference.md) — flags, behavior, examples; should match `pulp-tool <command> --help`.
   - **Architecture** (layout, data flow, boundaries, integrations): [ARCHITECTURE.md](ARCHITECTURE.md).
   - **Konflux / Tekton contracts** (upload paths, flags, container): [CLAUDE.md](CLAUDE.md) — together with item 2 above.
   - **User-facing** install, config, overview: [README.md](../README.md); deeper CLI detail stays in `cli-reference.md`.
   - **Contributor workflow** (checks, deps, process): [CONTRIBUTING.md](../CONTRIBUTING.md).
   - **PyPI releases** (maintainers): [releasing.md](releasing.md).
   - **Tests / layout:** [tests/README.md](../tests/README.md) when test organization or conventions change.
   - **Konflux live e2e** (`e2e/`): [e2e/README.md](../e2e/README.md) — harness layout, Tekton wiring, and **deferred pulp-content verification** conventions for new tests.
   - **ADRs:** [adr/](adr/) when you record a new architectural decision (see [0000-record-architecture-decisions.md](adr/0000-record-architecture-decisions.md)).
   - **Agent skills** (`skills/`): [skills/README.md](../skills/README.md) — index and cross-tool discovery; update when adding or renaming skills.
   - **Cross-links:** If you move or rename files, update links in other `.md` and Cursor rules that pointed at the old path.
4. **Types:** prefer hints; `mypy` covers `pulp_tool/` and `tests/` (see `pyproject.toml` overrides).
5. **Changelog / PR text:** always-on [`.cursor/rules/llm-development-guidelines.mdc`](../.cursor/rules/llm-development-guidelines.mdc); on confirmation load **drafting-pulp-tool-pr** skill ([`skills/drafting-pulp-tool-pr/`](../skills/drafting-pulp-tool-pr/)). Skill index: [`llm-development-guidelines-deep.mdc`](../.cursor/rules/llm-development-guidelines-deep.mdc). Ask before drafting PR boilerplate; update `CHANGELOG.md` when preparing the PR, not every debug iteration.
6. **Live Konflux e2e (`--real-server`):** follow the three-phase harness in [e2e/README.md § Conventions for new live e2e tests](../e2e/README.md#conventions-for-new-live-e2e-tests)—upload mutations first, queue pulp-content HTTP checks via `defer_distribution_check()` / [`distribution_verify_queue.py`](../e2e/distribution_verify_queue.py), run pulls only after `run_distribution_verification_phase()`. Do not HTTP GET `pulp-content` immediately after an upload in the same test case.

---

## PR and commit

- PR body: use [.github/PULL_REQUEST_TEMPLATE.md](../.github/PULL_REQUEST_TEMPLATE.md) **as-is**—same section headings and checklist items; fill in content under each section only.
- **One commit per PR** on the branch before merge ([CONTRIBUTING.md § One commit per pull request](../CONTRIBUTING.md#one-commit-per-pull-request)): fold follow-ups into that commit; avoid a chain of small commits on the PR branch.
- AI-assisted commits: [.github/commit-message-template.txt](../.github/commit-message-template.txt), `Assisted-By:` + `Signed-off-by:` — details in [CONTRIBUTING.md](../CONTRIBUTING.md#ai-assisted-commits).
- Essentials (always-on): [`.cursor/rules/llm-development-guidelines.mdc`](../.cursor/rules/llm-development-guidelines.mdc); on-demand skills: [`skills/`](../skills/) ([`skills/README.md`](../skills/README.md), [skill index](../.cursor/rules/llm-development-guidelines-deep.mdc)); [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Where things live

High-level **structure, diagrams, invariants, and glossary:** [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Optional

- Full CLI flags: [cli-reference.md](cli-reference.md).
- Test patterns: [tests/README.md](../tests/README.md).
- Live Konflux e2e harness: [e2e/README.md](../e2e/README.md).
- Agent skills (portable): [skills/README.md](../skills/README.md) — Cursor/Claude Code/Codex discover via [`.cursor/skills/`](../.cursor/skills/) and [`.agents/skills/`](../.agents/skills/) symlinks.
