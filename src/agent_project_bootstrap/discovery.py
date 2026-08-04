from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

from .models import CommandInference, RepositoryProfile

INSTRUCTION_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
)
CONFIDENCE_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _record_command(
    profile: RepositoryProfile,
    name: str,
    command: str,
    confidence: str,
    evidence: str,
) -> None:
    current = profile.command_inference.get(name)
    if current is None:
        profile.commands[name] = command
        profile.command_inference[name] = CommandInference(
            command=command,
            confidence=confidence,
            evidence=[evidence],
        )
        return

    if command == current.command:
        if evidence not in current.evidence:
            current.evidence.append(evidence)
        if CONFIDENCE_RANK[confidence] > CONFIDENCE_RANK[current.confidence]:
            current.confidence = confidence
        profile.commands[name] = current.command
        return

    # Prefer stronger evidence. Preserve the competing claim for review.
    current.evidence.append(f"conflict: {evidence} -> {command}")
    if CONFIDENCE_RANK[confidence] > CONFIDENCE_RANK[current.confidence]:
        current.command = command
        current.confidence = confidence
        profile.commands[name] = command


def _workflow_commands(text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    patterns = (
        ("test", r"(?m)^\s*(?:-\s*)?(?:run:\s*)?(python\s+-m\s+pytest(?:\s+[^\n#]+)?|pytest(?:\s+[^\n#]+)?)\s*$"),
        ("lint", r"(?m)^\s*(?:-\s*)?(?:run:\s*)?(ruff\s+check(?:\s+[^\n#]+)?)\s*$"),
        ("typecheck", r"(?m)^\s*(?:-\s*)?(?:run:\s*)?(mypy(?:\s+[^\n#]+)?)\s*$"),
        ("build", r"(?m)^\s*(?:-\s*)?(?:run:\s*)?((?:npm|pnpm|yarn|bun)\s+run\s+build(?:\s+[^\n#]+)?)\s*$"),
        ("lint", r"(?m)^\s*(?:-\s*)?(?:run:\s*)?((?:npm|pnpm|yarn|bun)\s+run\s+lint(?:\s+[^\n#]+)?)\s*$"),
        ("typecheck", r"(?m)^\s*(?:-\s*)?(?:run:\s*)?((?:npm|pnpm|yarn|bun)\s+run\s+typecheck(?:\s+[^\n#]+)?)\s*$"),
        ("test", r"(?m)^\s*(?:-\s*)?(?:run:\s*)?((?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test(?:\s+[^\n#]+)?)\s*$"),
    )
    for name, pattern in patterns:
        for match in re.finditer(pattern, text):
            command = " ".join(match.group(1).strip().split())
            candidates.append((name, command))
    return candidates


def infer_profile(profile: RepositoryProfile) -> tuple[str | None, str]:
    if "browser-extension" in profile.frameworks:
        return "browser-extension", "high"
    if profile.languages == ["python"]:
        return "python-service", "high"
    if any(language in profile.languages for language in ("typescript", "javascript")):
        confidence = "high" if profile.frameworks else "medium"
        return "typescript-web", confidence
    if "python" in profile.languages:
        return "python-service", "medium"
    return None, "low"


def discover_repository(repo_path: Path) -> RepositoryProfile:
    root = repo_path.resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path does not exist: {repo_path}")

    profile = RepositoryProfile(root=str(root))
    evidence: dict[str, list[str]] = {}

    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"
    package_json = root / "package.json"
    cargo = root / "Cargo.toml"
    go_mod = root / "go.mod"

    if pyproject.is_file() or requirements.is_file():
        profile.languages.append("python")
        evidence["python"] = [p.name for p in (pyproject, requirements) if p.is_file()]
        profile.package_managers.append("uv" if (root / "uv.lock").is_file() else "pip")
        if pyproject.is_file():
            try:
                pyproject_data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError):
                pyproject_data = {}
            tools = pyproject_data.get("tool", {}) if isinstance(pyproject_data, dict) else {}
            project_scripts = pyproject_data.get("project", {}).get("scripts", {}) if isinstance(pyproject_data, dict) else {}
            if isinstance(project_scripts, dict):
                for script_target in project_scripts.values():
                    if not isinstance(script_target, str) or ":" not in script_target:
                        continue
                    module = script_target.split(":", 1)[0]
                    candidate = "src/" + module.replace(".", "/") + ".py"
                    if (root / candidate).is_file() and candidate not in profile.entry_points:
                        profile.entry_points.append(candidate)
            if "pytest" in tools:
                _record_command(profile, "test", "python -m pytest", "medium", "pyproject.toml:tool.pytest")
            if "ruff" in tools:
                _record_command(profile, "lint", "ruff check .", "medium", "pyproject.toml:tool.ruff")
            if "mypy" in tools:
                _record_command(profile, "typecheck", "mypy src", "medium", "pyproject.toml:tool.mypy")

    if package_json.is_file():
        package = _read_json(package_json)
        profile.languages.append("typescript" if any(root.rglob("*.ts")) else "javascript")
        for lock, manager in (
            ("pnpm-lock.yaml", "pnpm"),
            ("bun.lock", "bun"),
            ("bun.lockb", "bun"),
            ("yarn.lock", "yarn"),
            ("package-lock.json", "npm"),
        ):
            if (root / lock).is_file():
                profile.package_managers.append(manager)
                break
        else:
            profile.package_managers.append("npm")

        dependencies = {
            **(package.get("dependencies") or {}),
            **(package.get("devDependencies") or {}),
        }
        framework_map = {
            "next": "nextjs",
            "react": "react",
            "@angular/core": "angular",
            "vue": "vue",
            "vite": "vite",
            "expo": "expo",
        }
        profile.frameworks.extend(
            framework for dependency, framework in framework_map.items() if dependency in dependencies
        )
        scripts = package.get("scripts") or {}
        manager = profile.package_managers[-1]
        for name in ("install", "test", "lint", "typecheck", "build", "validate"):
            if name in scripts:
                _record_command(
                    profile,
                    name,
                    f"{manager} run {name}",
                    "medium",
                    f"package.json:scripts.{name}",
                )
        evidence["package.json"] = sorted(scripts)

    if cargo.is_file():
        profile.languages.append("rust")
        profile.package_managers.append("cargo")
    if go_mod.is_file():
        profile.languages.append("go")
        profile.package_managers.append("go")

    if (root / "Makefile").is_file():
        profile.task_runners.append("make")
    if (root / "Justfile").is_file():
        profile.task_runners.append("just")

    manifest_candidates = list(root.glob("manifest.json")) + list(root.glob("**/manifest.json"))
    for manifest in manifest_candidates[:20]:
        data = _read_json(manifest)
        if "manifest_version" in data:
            if "browser-extension" not in profile.frameworks:
                profile.frameworks.append("browser-extension")
            evidence.setdefault("browser-extension", []).append(str(manifest.relative_to(root)))

    ignored_directories = {".git", ".venv", "node_modules", "dist", "build", "coverage", "__pycache__"}
    profile.directories = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name not in ignored_directories and not path.name.startswith(".")
    )[:30]

    profile.instruction_files = [path for path in INSTRUCTION_FILES if (root / path).is_file()]

    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        workflow_paths = sorted(
            path for path in workflows.iterdir() if path.suffix in {".yml", ".yaml"}
        )
        profile.ci_workflows = [str(path.relative_to(root)) for path in workflow_paths]
        for path in workflow_paths:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for name, command in _workflow_commands(text):
                _record_command(profile, name, command, "high", str(path.relative_to(root)))

    entry_candidates = (
        "src/main.py",
        "src/app.py",
        "app/main.py",
        "main.py",
        "src/index.ts",
        "src/index.tsx",
        "src/main.ts",
        "src/main.tsx",
        "src/app/page.tsx",
    )
    profile.entry_points.extend(path for path in entry_candidates if (root / path).is_file() and path not in profile.entry_points)
    profile.entry_points = sorted(set(profile.entry_points))

    manifest = root / ".project" / "manifest.yaml"
    if manifest.is_file():
        data = _read_yaml(manifest)
        evidence["project-manifest"] = [str(data.get("project", {}).get("id", "unknown"))]

    profile.languages = sorted(set(profile.languages))
    profile.frameworks = sorted(set(profile.frameworks))
    profile.package_managers = sorted(set(profile.package_managers))
    profile.task_runners = sorted(set(profile.task_runners))
    for inference in profile.command_inference.values():
        inference.evidence = sorted(set(inference.evidence))
    profile.evidence = evidence
    return profile
