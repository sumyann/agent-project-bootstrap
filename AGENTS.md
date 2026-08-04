# Agent Operating Guide

## Purpose

Build and maintain a repository lifecycle system that prepares projects for safe AI-agent work.

## Required validation

Run:

```bash
python -m pytest
python -m agent_project_bootstrap --help
```

## Change rules

- Keep templates tool-neutral; tool-specific files should delegate to `AGENTS.md`.
- Default to inspection, planning, and dry-run behavior before writes.
- Never overwrite unmergeable repository customizations.
- Treat deployment, credential, authorization, database, and CI changes as approval-required.
- Keep generated project IDs stable.
- Add tests for discovery, planning, rendering, verification, and upgrade safety.
