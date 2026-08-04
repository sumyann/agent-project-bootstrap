#!/usr/bin/env python3
"""Perform dependency-light checks on the repository's agent harness."""
from pathlib import Path

REQUIRED = (
    "AGENTS.md",
    "ARCHITECTURE.md",
    ".project/manifest.yaml",
    ".project/commands.yaml",
    ".project/guardrails.yaml",
    ".project/progress.yaml",
    ".project/validation.yaml",
    ".project/tooling.yaml",
    ".project/bootstrap-lock.yaml",
)


def main() -> int:
    missing = [path for path in REQUIRED if not Path(path).is_file()]
    if missing:
        for path in missing:
            print(f"ERROR missing required harness file: {path}")
        return 1

    manifest = Path(".project/manifest.yaml").read_text(encoding="utf-8")
    progress = Path(".project/progress.yaml").read_text(encoding="utf-8")
    marker = "project_id:"
    if marker not in manifest or marker not in progress:
        print("ERROR project_id is missing from manifest or progress")
        return 1

    print("Agent harness verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
