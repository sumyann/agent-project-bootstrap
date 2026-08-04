#!/usr/bin/env python3
"""Perform dependency-light checks on the repository's agent harness."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def _top_level_value(text: str, key: str) -> str | None:
    prefix = f"{key}:"
    for raw_line in text.splitlines():
        if raw_line.startswith(prefix):
            value = raw_line.split(":", 1)[1].strip().strip("\"'")
            return value or None
    return None


def _nested_value(text: str, section: str, key: str) -> str | None:
    section_prefix = f"{section}:"
    in_section = False
    section_indent = 0

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())
        if not in_section:
            if raw_line.startswith(section_prefix):
                in_section = True
                section_indent = indent
            continue

        if indent <= section_indent:
            break

        if stripped.startswith(f"{key}:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            return value or None

    return None


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing:
        for path in missing:
            print(f"ERROR missing required harness file: {path}")
        return 1

    manifest = (ROOT / ".project/manifest.yaml").read_text(encoding="utf-8")
    progress = (ROOT / ".project/progress.yaml").read_text(encoding="utf-8")

    manifest_id = _nested_value(manifest, "project", "id")
    progress_id = _top_level_value(progress, "project_id")

    if not manifest_id:
        print("ERROR project.id is missing from manifest")
        return 1
    if not progress_id:
        print("ERROR project_id is missing from progress")
        return 1
    if manifest_id != progress_id:
        print(
            "ERROR project IDs do not match: "
            f"manifest={manifest_id!r}, progress={progress_id!r}"
        )
        return 1

    print("Agent harness verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
