# Agent Operating Guide

Project-specific context and commands are maintained in the managed section below. Custom guidance may be added outside that section and will be preserved during upgrades.

<!-- agent-bootstrap:start managed -->
## Project

- ID: `{{project_id}}`
- Profile: `{{profile}}`
- Primary language: `{{language}}`
- Bootstrap version: `{{bootstrap_version}}`

## Startup sequence

1. Read `.project/manifest.yaml`, `ARCHITECTURE.md`, and `.project/guardrails.yaml`.
2. Review relevant decision records.
3. Run the fastest applicable validation stage before changing code.
4. Keep the change scoped to the assigned task.

## Commands

- Install: `{{install_command}}`
- Test: `{{test_command}}`
- Validate: `{{validate_command}}`
- Verify harness: `python scripts/verify-agent-harness.py`

## Boundaries

### Always

- Add or update tests for behavior changes.
- Run deterministic validation before claiming completion.
- Update documentation and `.project/progress.yaml` after meaningful work.

### Ask

- Add runtime dependencies.
- Change public APIs, database schemas, authentication, authorization, or CI.
- Deploy to production or access customer systems.

### Never

- Commit secrets.
- Disable or weaken tests and security controls to force success.
- Force-push `main`, merge your own PR, or delete production data.
- Change portfolio priority, commercial role, or public visibility.

## Completion

Run validation, summarize files changed, report the exact checks executed, record durable decisions, and update project progress.
<!-- agent-bootstrap:end managed -->
