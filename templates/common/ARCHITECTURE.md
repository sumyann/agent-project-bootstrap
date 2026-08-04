# Architecture Map

This file is a concise navigation aid for coding agents. Keep it current as the project grows; record historical rationale in ADRs instead.

<!-- agent-bootstrap:start managed -->
## Project identity

- Project ID: `{{project_id}}`
- Profile: `{{profile}}`
- Primary language: `{{language}}`

## Detected stack

{{detected_stack}}

## Detected top-level directories

{{detected_directories}}

## Detected entry points

{{detected_entry_points}}

## Detected CI workflows

{{detected_ci}}

## Verification map

- Install: `{{install_command}}`
- Test: `{{test_command}}`
- Full validation: `{{validate_command}}`
<!-- agent-bootstrap:end managed -->

## Project-specific dependency direction

Document the allowed dependency flow between layers. Identify packages that must not import one another.

## Project-specific data flow

Document the primary request, event, or processing flow at a high level.

## External systems

Document external APIs, databases, queues, identity providers, model providers, and deployment platforms.

## Protected boundaries

Document security-critical modules, public interfaces, generated files, and other areas requiring explicit approval.
