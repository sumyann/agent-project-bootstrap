from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from . import __version__
from .models import MigrationPlan, PlanItem

MANAGED_START = "<!-- agent-bootstrap:start managed -->"
MANAGED_END = "<!-- agent-bootstrap:end managed -->"
LOCK_PATH = Path(".project/bootstrap-lock.yaml")


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def managed_block(content: str) -> str | None:
    start = content.find(MANAGED_START)
    end = content.find(MANAGED_END)
    if start == -1 or end == -1 or end < start:
        return None
    return content[start : end + len(MANAGED_END)]


def merge_managed(existing: str, rendered: str) -> str | None:
    current = managed_block(existing)
    replacement = managed_block(rendered)
    if current is None or replacement is None:
        return None
    return existing.replace(current, replacement, 1)


def read_lock(repo_path: Path) -> dict:
    path = repo_path / LOCK_PATH
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def lock_content(profile: str, rendered_files: dict[Path, str]) -> str:
    lock = {
        "schema_version": 1,
        "generator": "sumyann/agent-project-bootstrap",
        "generator_version": __version__,
        "profile": profile,
        "managed_files": {
            str(path): {"sha256": sha256_text(content)}
            for path, content in sorted(rendered_files.items(), key=lambda item: str(item[0]))
            if path != LOCK_PATH
        },
    }
    return yaml.safe_dump(lock, sort_keys=False)


def write_lock(repo_path: Path, profile: str, rendered_files: dict[Path, str]) -> None:
    target = repo_path / LOCK_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(lock_content(profile, rendered_files), encoding="utf-8")


def build_plan(
    repo_path: Path,
    project_id: str,
    profile_name: str,
    rendered_files: dict[Path, str],
) -> MigrationPlan:
    lock = read_lock(repo_path)
    managed_files = lock.get("managed_files", {}) if isinstance(lock, dict) else {}
    plan = MigrationPlan(project_id=project_id, profile=profile_name)

    for relative, rendered in sorted(rendered_files.items(), key=lambda item: str(item[0])):
        target = repo_path / relative
        if not target.exists():
            plan.items.append(PlanItem(str(relative), "create", "bootstrap file is missing"))
            continue

        existing = target.read_text(encoding="utf-8")
        if existing == rendered:
            plan.items.append(PlanItem(str(relative), "unchanged", "already matches current template"))
            continue

        if merge_managed(existing, rendered) is not None:
            plan.items.append(PlanItem(str(relative), "merge", "managed section can be updated safely"))
            continue

        recorded = managed_files.get(str(relative), {}) if isinstance(managed_files, dict) else {}
        recorded_hash = recorded.get("sha256") if isinstance(recorded, dict) else None
        if recorded_hash and sha256_text(existing) == recorded_hash:
            plan.items.append(PlanItem(str(relative), "update", "unchanged since previous bootstrap"))
        else:
            plan.items.append(PlanItem(str(relative), "conflict", "existing customization cannot be merged safely"))

    return plan


def apply_plan(
    repo_path: Path,
    plan: MigrationPlan,
    rendered_files: dict[Path, str],
) -> list[str]:
    applied: list[str] = []
    actions = {item.path: item.action for item in plan.items}
    for relative, rendered in rendered_files.items():
        action = actions[str(relative)]
        target = repo_path / relative
        if action in {"unchanged", "conflict"}:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if action == "merge":
            merged = merge_managed(target.read_text(encoding="utf-8"), rendered)
            if merged is None:
                continue
            target.write_text(merged, encoding="utf-8")
        else:
            target.write_text(rendered, encoding="utf-8")
        applied.append(str(relative))
    return applied
