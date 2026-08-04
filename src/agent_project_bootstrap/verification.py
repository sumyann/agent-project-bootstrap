from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class VerificationFinding:
    level: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level, "path": self.path, "message": self.message}


REQUIRED_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "ARCHITECTURE.md",
    ".github/copilot-instructions.md",
    ".project/manifest.yaml",
    ".project/commands.yaml",
    ".project/guardrails.yaml",
    ".project/progress.yaml",
    ".project/validation.yaml",
    ".project/tooling.yaml",
    ".project/bootstrap-lock.yaml",
    "scripts/verify-agent-harness.py",
)


def _load_yaml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "expected a YAML mapping"
    return data, None


def verify_repository(repo_path: Path) -> list[VerificationFinding]:
    findings: list[VerificationFinding] = []
    for relative in REQUIRED_FILES:
        if not (repo_path / relative).is_file():
            findings.append(VerificationFinding("error", relative, "required harness file is missing"))

    yaml_paths = (
        ".project/manifest.yaml",
        ".project/commands.yaml",
        ".project/guardrails.yaml",
        ".project/progress.yaml",
        ".project/validation.yaml",
        ".project/tooling.yaml",
        ".project/bootstrap-lock.yaml",
    )
    loaded: dict[str, dict[str, Any]] = {}
    for relative in yaml_paths:
        path = repo_path / relative
        if not path.is_file():
            continue
        data, error = _load_yaml(path)
        if error:
            findings.append(VerificationFinding("error", relative, f"invalid YAML: {error}"))
        elif data is not None:
            loaded[relative] = data

    manifest_id = loaded.get(".project/manifest.yaml", {}).get("project", {}).get("id")
    progress_id = loaded.get(".project/progress.yaml", {}).get("project_id")
    registry_id = loaded.get(".project/manifest.yaml", {}).get("registry", {}).get("project_id")
    ids = {value for value in (manifest_id, progress_id, registry_id) if value}
    if len(ids) > 1:
        findings.append(
            VerificationFinding("error", ".project", f"project IDs do not match: {sorted(ids)}")
        )

    commands = loaded.get(".project/commands.yaml", {}).get("commands", {})
    if isinstance(commands, dict):
        for name, spec in commands.items():
            if not isinstance(spec, dict):
                findings.append(VerificationFinding("error", ".project/commands.yaml", f"{name} is not a mapping"))
                continue
            command = spec.get("command")
            if command:
                try:
                    if not shlex.split(str(command)):
                        raise ValueError("empty command")
                except ValueError as exc:
                    findings.append(
                        VerificationFinding("error", ".project/commands.yaml", f"{name} is not parseable: {exc}")
                    )

    architecture = repo_path / "ARCHITECTURE.md"
    if architecture.is_file() and len(architecture.read_text(encoding="utf-8").splitlines()) > 300:
        findings.append(
            VerificationFinding("warning", "ARCHITECTURE.md", "architecture map exceeds 300 lines")
        )

    if not findings:
        findings.append(VerificationFinding("ok", ".", "agent harness is internally consistent"))
    return findings
