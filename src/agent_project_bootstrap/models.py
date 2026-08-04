from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CommandInference:
    command: str
    confidence: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RepositoryProfile:
    root: str
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    task_runners: list[str] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    instruction_files: list[str] = field(default_factory=list)
    ci_workflows: list[str] = field(default_factory=list)
    commands: dict[str, str] = field(default_factory=dict)
    command_inference: dict[str, CommandInference] = field(default_factory=dict)
    entry_points: list[str] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanItem:
    path: str
    action: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class MigrationPlan:
    project_id: str
    profile: str
    items: list[PlanItem] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return any(item.action == "conflict" for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "profile": self.profile,
            "has_conflicts": self.has_conflicts,
            "items": [item.to_dict() for item in self.items],
        }
