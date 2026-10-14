# Skill verification (RED/GREEN)

Baseline failure modes and how each skill addresses them. Re-run when editing skills.

## changing-pulp-upload

| RED (without skill) | GREEN (with skill) |
|---------------------|-------------------|
| Change `--sbom-path` default without checking release pipeline | Checklist requires both Tekton YAMLs; table shows flag differences |
| Duplicate upload logic in CLI layer | Red flag: keep logic in `PulpHelper` → `pulp_tool.upload` |
| Assume upstream tasks are frozen | Rationalization row + step 2 re-open GitHub YAML |

## changing-pulp-container

| RED (without skill) | GREEN (with skill) |
|---------------------|-------------------|
| Add GitHub Actions `docker build` as merge gate | Skill states Konflux Tekton builds on PR/push; red flag against duplicate GHA |
| Edit Dockerfile without checking `.tekton/` PipelineRuns | Workflow + reference.md list PipelineRuns and `docker-build-oci-ta` task chain |
| Dockerfile failure only visible in GHA | Debug tip: failures surface in Konflux `build-container` task, not unit-test workflow |
| Confuse image *build* with Tekton tasks that *run* pulp-tool | Points to changing-pulp-upload for downstream consumers |

## drafting-pulp-tool-pr

| RED (without skill) | GREEN (with skill) |
|---------------------|-------------------|
| Paste full PR body after every code change | Ask-first gate; `disable-model-invocation: true` |
| Custom PR outline omitting checklist | templates.md reproduces template verbatim |
| CHANGELOG edit on every debug fix | Red flag + templates.md timing rules |
| PR body only in chat, lost between sessions | Writes gitignored `pr-description.md` at repo root |

## troubleshooting-pulp-tool-ci

| RED (without skill) | GREEN (with skill) |
|---------------------|-------------------|
| Single pre-commit run after partial fix | Loop until zero failures (commit + pre-push stages) |
| Stop after `make test` without diff-cover | Diff coverage section requires `make test-diff-coverage` |
| Rely on high overall coverage | Explicit: merge gate is 100% on the diff only |
| Expect Black/Flake8 or `.flake8` | Points to CONTRIBUTING / deep guidelines for Ruff layout |
| `hadolint` not found on PATH | `scripts/run-hadolint.sh`; checkton needs docker/podman |
| `pip-audit` hook rewrites `_version.py` | `make audit` uses `uv export` (no editable install) |

## Structural checks

- [x] Each `SKILL.md` has `name` matching directory
- [x] Descriptions start with "Use when" (trigger-only, no workflow summary)
- [x] Body word counts under 500 where practical (`wc -w skills/*/SKILL.md`)
- [x] Heavy templates in `drafting-pulp-tool-pr/templates.md`, not duplicated in CLAUDE.md
- [x] No one-time setup skills — lint onboarding lives in CONTRIBUTING.md, not skills/
