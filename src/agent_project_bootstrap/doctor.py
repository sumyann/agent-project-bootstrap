from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ToolStatus:
    name: str
    category: str
    installed: bool
    path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "installed": self.installed,
            "path": self.path,
        }


def inspect_tools(profile: dict | None = None) -> list[ToolStatus]:
    tooling = (profile or {}).get("tooling", {})
    required = tooling.get("required", ["git", "python"])
    recommended = tooling.get("recommended", ["gh", "rg", "jq", "yq", "gitleaks"])
    optional = tooling.get("optional", ["fd", "ast-grep", "difft", "semgrep", "trivy", "act"])

    statuses: list[ToolStatus] = []
    seen: set[str] = set()
    for category, tools in (
        ("required", required),
        ("recommended", recommended),
        ("optional", optional),
    ):
        for name in tools:
            if name in seen:
                continue
            seen.add(name)
            path = shutil.which(name)
            statuses.append(ToolStatus(name=name, category=category, installed=path is not None, path=path))
    return statuses
