# Roadmap

## Milestone 1 — Repository-local bootstrap

- [x] Generate common agent instructions and structured project files.
- [x] Support Python service, TypeScript web, and browser extension profiles.
- [x] Audit missing files without modifying the repository.
- [x] Preserve existing files by default.

## Milestone 2 — Repository intelligence and harness lifecycle

- [x] Discover languages, frameworks, package managers, CI, instructions, and entry points.
- [x] Generate a concise architecture map.
- [x] Provide deterministic harness verification.
- [x] Add environment readiness diagnostics.
- [x] Record bootstrap version and managed-file hashes.
- [x] Preview and apply safe upgrades with managed-section merging.
- [x] Inspect repositories through the GitHub API.
- [x] Generate migration branches and draft pull requests.
- [x] Infer commands with confidence scoring and conflict evidence.
- [ ] Validate remote migration against representative repositories for every supported profile.

## Milestone 3 — Optional integrations

- [ ] Define a provider-neutral progress event format.
- [ ] Support opt-in publishing to project trackers, registries, webhooks, or artifact stores.
- [ ] Document field-level trust and conflict policies for external integrations.
- [ ] Keep the core fully functional when no external integration is configured.

## Milestone 4 — Sustained agent operation

- [ ] Declarative task protocols.
- [ ] Session handoff checkpoints.
- [ ] ADR topic index and context selection.
- [ ] Optional worktree isolation helpers.
