# Design references

Agent Project Bootstrap remains an independent implementation. The following public projects informed lifecycle patterns adopted in version 0.2.0:

- `synthnoosh/agentic-harness-bootstrap` — phased discovery/generation/verification, concise architecture maps, deterministic harness checks, fail-fast validation, and Always/Ask/Never boundaries.
- `vstorm-co/full-stack-ai-agent-template` — generator version manifests, dry-run upgrades, dedicated upgrade branches, and preservation of project customizations.
- `conorluddy/AgentLoadout` — environment readiness checks and profile-specific required/recommended/optional tooling.
- `alinaqi/maggy` — declarative protocols, durable handoffs, ADR context selection, and isolated parallel workspaces are tracked as later-stage ideas rather than part of the current bootstrap core.

No source code was copied from these projects. Concepts were adapted to this project's provider-neutral repository lifecycle scope.
