# Agent Project Bootstrap

Turn new and existing repositories into safe, navigable, upgradeable environments for AI coding agents.

Agent Project Bootstrap generates repository-neutral instructions, architecture maps, deterministic commands, executable guardrails, harness verification, optional progress metadata, and versioned lifecycle state. It is designed for Claude Code, Codex, GitHub Copilot, Gemini, and other coding agents.

## Lifecycle

```text
Discover → Analyze → Plan → Generate → Verify → Publish PR → Optional integrations
```

Version 0.3 implements local and remote discovery, evidence-backed command inference, dry-run migration planning, and draft migration pull requests. External project-management, registry, and reporting integrations are optional and remain outside the core.

## Profiles

- `python-service`
- `typescript-web`
- `browser-extension`

## Installation

Agent Project Bootstrap requires Python 3.12 or newer. Install a supported Python version using your operating system package manager or the official Python installer.

From the cloned repository:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Verify the installation:

```bash
python --version
agent-bootstrap --help
agent-bootstrap doctor --profile python-service
```

A virtual environment keeps the interpreter version used when it was created. Recreate an older environment with Python 3.12 rather than expecting an in-place interpreter upgrade.

## Local commands

```bash
agent-bootstrap doctor --profile python-service
agent-bootstrap inspect --repo-path ./project
agent-bootstrap plan --repo-path ./project --project-id example-service --profile python-service
agent-bootstrap init --repo-path ./project --project-id example-service --profile python-service
agent-bootstrap verify --repo-path ./project
agent-bootstrap upgrade --repo-path ./project --project-id example-service --profile python-service --dry-run
agent-bootstrap upgrade --repo-path ./project --project-id example-service --profile python-service --apply
```

## Remote GitHub workflow

Read-only inspection works for public repositories without a token. Set `GITHUB_TOKEN` for private repositories and all write operations.

```bash
# Inspect repository metadata, stack, CI, entry points, and commands
agent-bootstrap inspect --repo acme/example-service

# Produce an evidence-backed plan and unified diffs without writing
agent-bootstrap plan \
  --repo acme/example-service \
  --project-id example-service \
  --profile python-service

# Equivalent migration dry run
agent-bootstrap migrate \
  --repo acme/example-service \
  --project-id example-service \
  --dry-run

# Recheck the inspected SHA, create one migration commit, and open a draft PR
GITHUB_TOKEN=... agent-bootstrap migrate \
  --repo acme/example-service \
  --project-id example-service \
  --open-pr
```

Remote writes require `contents:write` and `pull_requests:write`. The tool never pushes to the default branch, never merges its own pull request, and refuses to proceed if the repository changed after inspection.

Use `--output json` on structured commands when another agent or automation will consume the result. Use `--base-branch`, `--token-env`, or `--api-url` when the GitHub defaults do not apply.

## Evidence and confidence

Commands are reported with their source evidence and one of four confidence levels:

- `high` — confirmed by CI
- `medium` — found in project configuration or package scripts
- `low` — inferred from weaker documentation or conventions
- `unknown` — no defensible command evidence

Competing command claims are preserved as conflicts rather than silently reconciled.

## Generated foundation

- `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`
- `.github/copilot-instructions.md`
- `ARCHITECTURE.md`
- `.project/manifest.yaml`
- `.project/commands.yaml`
- `.project/guardrails.yaml`
- `.project/progress.yaml`
- `.project/validation.yaml`
- `.project/tooling.yaml`
- `.project/bootstrap-lock.yaml`
- `scripts/verify-agent-harness.py`
- `.github/workflows/publish-progress.yml`

The generated progress workflow validates repository-local metadata and contains a neutral integration placeholder. Adopters decide whether to connect it to a project tracker, internal registry, webhook, artifact store, or nothing at all.

## Safe migrations and upgrades

Planning classifies each file as:

- `create` — missing file
- `unchanged` — already current
- `safe-update` — unchanged since a previous bootstrap and safe to replace
- `managed-merge` — only a marked managed section will be updated
- `conflict` — customized content requires human review and is skipped

Remote migration branches use `agent-bootstrap/<project-id>-v<version>`. Pull requests are drafts by default; pass `--ready` only when a ready-for-review PR is explicitly desired.

## Project neutrality

The repository contains no product-specific profiles, customer data, deployment URLs, or assumptions about a particular portfolio. Examples use fictional organizations and repositories. Project-specific policies should live in the target repository, not in Agent Project Bootstrap.
