from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import yaml

from . import __version__
from .discovery import discover_repository, infer_profile
from .doctor import inspect_tools
from .lifecycle import LOCK_PATH, apply_plan, build_plan, write_lock
from .remote import (
    GitHubClient,
    build_remote_plan,
    inspect_remote_snapshot,
    materialize_remote_repository,
    open_remote_migration_pr,
)
from .verification import verify_repository

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = PACKAGE_ROOT / "profiles"
TEMPLATES_DIR = PACKAGE_ROOT / "templates" / "common"


def load_profile(name: str) -> dict:
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in PROFILES_DIR.glob("*.yaml")))
        raise SystemExit(f"Unknown profile {name!r}. Available: {available}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"Profile {name!r} must contain a YAML mapping")
    return data


def target_files() -> Iterable[Path]:
    for path in TEMPLATES_DIR.rglob("*"):
        if path.is_file():
            yield path


def render(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _indent_yaml(value: object, spaces: int = 2) -> str:
    prefix = " " * spaces
    dumped = yaml.safe_dump(value, sort_keys=False).rstrip()
    return "\n".join(prefix + line if line else line for line in dumped.splitlines())


def _architecture_values(repo_path: Path | None) -> dict[str, str]:
    if repo_path is None or not repo_path.is_dir():
        return {
            "detected_stack": "- No repository stack detected yet.",
            "detected_directories": "- No source directories detected yet.",
            "detected_entry_points": "- No entry points detected yet.",
            "detected_ci": "- No CI workflows detected yet.",
        }
    discovered = discover_repository(repo_path)
    stack = discovered.languages + discovered.frameworks + discovered.package_managers
    return {
        "detected_stack": "\n".join(f"- `{item}`" for item in stack) or "- No stack evidence detected.",
        "detected_directories": "\n".join(f"- `{item}/`" for item in discovered.directories) or "- No source directories detected yet.",
        "detected_entry_points": "\n".join(f"- `{item}`" for item in discovered.entry_points) or "- No entry points detected yet.",
        "detected_ci": "\n".join(f"- `{item}`" for item in discovered.ci_workflows) or "- No CI workflows detected yet.",
    }


def render_target_files(
    project_id: str,
    profile_name: str,
    repo_path: Path | None = None,
) -> dict[Path, str]:
    profile = load_profile(profile_name)
    values = {
        "project_id": project_id,
        "project_name": project_id.replace("-", " ").title(),
        "profile": profile_name,
        "language": profile["runtime"]["language"],
        "install_command": profile["commands"]["install"],
        "test_command": profile["commands"]["test"],
        "validate_command": profile["commands"]["validate"],
        "bootstrap_version": __version__,
        "validation_stages": _indent_yaml(profile.get("validation", {}).get("stages", [])),
        "validation_order": yaml.safe_dump(
            [stage.get("id") for stage in profile.get("validation", {}).get("stages", [])],
            default_flow_style=True,
        ).strip(),
        "tooling": _indent_yaml(profile.get("tooling", {})),
        **_architecture_values(repo_path),
    }
    return {
        source.relative_to(TEMPLATES_DIR): render(source.read_text(encoding="utf-8"), values)
        for source in target_files()
    }


def init_repo(repo_path: Path, project_id: str, profile_name: str, force: bool) -> int:
    rendered_files = render_target_files(project_id, profile_name, repo_path)
    created: list[str] = []
    skipped: list[str] = []
    for relative, content in rendered_files.items():
        target = repo_path / relative
        if target.exists() and not force:
            skipped.append(str(relative))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(str(relative))

    created_set = set(created)
    final_rendered = render_target_files(project_id, profile_name, repo_path)
    for relative, content in final_rendered.items():
        if str(relative) in created_set:
            (repo_path / relative).write_text(content, encoding="utf-8")

    managed_snapshot = {
        relative: (repo_path / relative).read_text(encoding="utf-8")
        for relative, rendered in final_rendered.items()
        if (repo_path / relative).is_file()
        and (
            str(relative) in created_set
            or (repo_path / relative).read_text(encoding="utf-8") == rendered
        )
    }
    write_lock(repo_path, profile_name, managed_snapshot)

    print(f"Created or updated {len(created)} files.")
    for item in created:
        print(f"  + {item}")
    if skipped:
        print(
            f"Skipped {len(skipped)} existing files. "
            "Use 'upgrade --dry-run' to assess managed updates."
        )
        for item in skipped:
            print(f"  = {item}")
    return 0


def audit_repo(repo_path: Path, profile_name: str) -> int:
    load_profile(profile_name)
    missing = []
    for source in target_files():
        relative = source.relative_to(TEMPLATES_DIR)
        if not (repo_path / relative).is_file():
            missing.append(str(relative))
    if not missing:
        print("Repository satisfies the minimum bootstrap file set.")
        return 0
    print("Missing bootstrap files:")
    for item in missing:
        print(f"  - {item}")
    return 1


def _print_data(data: object, output: str) -> None:
    if output == "json":
        print(json.dumps(data, indent=2, sort_keys=False))
    else:
        print(yaml.safe_dump(data, sort_keys=False).rstrip())


def inspect_local_repo(repo_path: Path, output: str) -> int:
    profile = discover_repository(repo_path)
    detected_profile, confidence = infer_profile(profile)
    _print_data(
        {
            "detected_profile": detected_profile,
            "profile_confidence": confidence,
            "profile": profile.to_dict(),
        },
        output,
    )
    return 0


def plan_local_repo(repo_path: Path, project_id: str, profile_name: str, output: str) -> int:
    rendered = render_target_files(project_id, profile_name, repo_path)
    plan = build_plan(repo_path, project_id, profile_name, rendered)
    _print_data(plan.to_dict(), output)
    return 2 if plan.has_conflicts else 0


def upgrade_repo(
    repo_path: Path,
    project_id: str,
    profile_name: str,
    dry_run: bool,
    output: str,
) -> int:
    rendered = render_target_files(project_id, profile_name, repo_path)
    plan = build_plan(repo_path, project_id, profile_name, rendered)
    if dry_run:
        _print_data(plan.to_dict(), output)
        return 2 if plan.has_conflicts else 0

    applied = apply_plan(repo_path, plan, rendered)
    actions = {item.path: item.action for item in plan.items}
    snapshot = {
        relative: (repo_path / relative).read_text(encoding="utf-8")
        for relative in rendered
        if (repo_path / relative).is_file()
        and actions.get(str(relative)) != "conflict"
    }
    write_lock(repo_path, profile_name, snapshot)
    _print_data(
        {
            "applied": applied,
            "conflicts": [item.path for item in plan.items if item.action == "conflict"],
        },
        output,
    )
    return 2 if plan.has_conflicts else 0


def verify_repo(repo_path: Path, output: str) -> int:
    findings = verify_repository(repo_path)
    _print_data([finding.to_dict() for finding in findings], output)
    return 1 if any(finding.level == "error" for finding in findings) else 0


def doctor(profile_name: str | None, output: str) -> int:
    profile = load_profile(profile_name) if profile_name else None
    statuses = inspect_tools(profile)
    _print_data([status.to_dict() for status in statuses], output)
    return 1 if any(
        status.category == "required" and not status.installed for status in statuses
    ) else 0


def _remote_client(args: argparse.Namespace, require_token: bool = False) -> GitHubClient:
    token = os.getenv(args.token_env)
    if require_token and not token:
        raise SystemExit(f"{args.token_env} must be set for repository writes")
    return GitHubClient(token=token, api_url=args.api_url)


def _managed_paths() -> set[str]:
    return {str(path.relative_to(TEMPLATES_DIR)) for path in target_files()} | {str(LOCK_PATH)}


def inspect_remote(args: argparse.Namespace) -> int:
    client = _remote_client(args)
    with materialize_remote_repository(
        client,
        args.repo,
        managed_paths=_managed_paths(),
        base_branch=args.base_branch,
    ) as snapshot:
        _print_data(inspect_remote_snapshot(snapshot), args.output)
    return 0


def _remote_plan(args: argparse.Namespace, require_token: bool = False):
    client = _remote_client(args, require_token=require_token)
    with materialize_remote_repository(
        client,
        args.repo,
        managed_paths=_managed_paths(),
        base_branch=args.base_branch,
    ) as snapshot:
        discovered = discover_repository(snapshot.root)
        inferred, _ = infer_profile(discovered)
        profile_name = args.profile or inferred
        if not profile_name:
            raise SystemExit("Unable to infer a bootstrap profile; pass --profile explicitly")
        load_profile(profile_name)
        rendered = render_target_files(args.project_id, profile_name, snapshot.root)
        plan = build_remote_plan(snapshot, args.project_id, profile_name, rendered)
        if getattr(args, "open_pr", False):
            return client, plan, open_remote_migration_pr(client, plan, draft=not args.ready)
        return client, plan, None


def plan_remote(args: argparse.Namespace) -> int:
    _, plan, _ = _remote_plan(args)
    _print_data(plan.to_dict(), args.output)
    return 2 if plan.has_conflicts else 0


def migrate_remote(args: argparse.Namespace) -> int:
    if args.dry_run:
        _, plan, _ = _remote_plan(args)
        _print_data(plan.to_dict(), args.output)
        return 2 if plan.has_conflicts else 0
    _, plan, result = _remote_plan(args, require_token=True)
    _print_data({"plan": plan.to_dict(), "result": result}, args.output)
    return 0


def add_output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", choices=("yaml", "json"), default="yaml")


def add_remote_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-branch")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--api-url", default=os.getenv("GITHUB_API_URL", "https://api.github.com"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap repository lifecycles for AI coding agents"
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Add bootstrap files to a repository")
    init.add_argument("--repo-path", type=Path, required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--profile", required=True)
    init.add_argument("--force", action="store_true")

    audit = subparsers.add_parser("audit", help="Audit required bootstrap files")
    audit.add_argument("--repo-path", type=Path, required=True)
    audit.add_argument("--profile", required=True)

    inspect = subparsers.add_parser(
        "inspect", help="Discover local or remote repository structure and tooling"
    )
    inspect_source = inspect.add_mutually_exclusive_group(required=True)
    inspect_source.add_argument("--repo-path", type=Path)
    inspect_source.add_argument("--repo")
    add_remote_arguments(inspect)
    add_output_argument(inspect)

    plan = subparsers.add_parser("plan", help="Create a non-writing migration plan")
    plan_source = plan.add_mutually_exclusive_group(required=True)
    plan_source.add_argument("--repo-path", type=Path)
    plan_source.add_argument("--repo")
    plan.add_argument("--project-id", required=True)
    plan.add_argument("--profile")
    add_remote_arguments(plan)
    add_output_argument(plan)

    upgrade = subparsers.add_parser(
        "upgrade", help="Plan or apply a local managed harness upgrade"
    )
    upgrade.add_argument("--repo-path", type=Path, required=True)
    upgrade.add_argument("--project-id", required=True)
    upgrade.add_argument("--profile", required=True)
    mode = upgrade.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    add_output_argument(upgrade)

    migrate = subparsers.add_parser(
        "migrate", help="Preview or open a remote repository migration pull request"
    )
    migrate.add_argument("--repo", required=True)
    migrate.add_argument("--project-id", required=True)
    migrate.add_argument("--profile")
    migrate_mode = migrate.add_mutually_exclusive_group(required=True)
    migrate_mode.add_argument("--dry-run", action="store_true")
    migrate_mode.add_argument("--open-pr", action="store_true")
    migrate.add_argument("--ready", action="store_true", help="Open a ready PR instead of a draft")
    add_remote_arguments(migrate)
    add_output_argument(migrate)

    verify = subparsers.add_parser("verify", help="Verify generated harness integrity")
    verify.add_argument("--repo-path", type=Path, required=True)
    add_output_argument(verify)

    doctor_parser = subparsers.add_parser(
        "doctor", help="Check local agent-tool readiness"
    )
    doctor_parser.add_argument("--profile")
    add_output_argument(doctor_parser)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init":
        return init_repo(args.repo_path, args.project_id, args.profile, args.force)
    if args.command == "audit":
        return audit_repo(args.repo_path, args.profile)
    if args.command == "inspect":
        return inspect_remote(args) if args.repo else inspect_local_repo(args.repo_path, args.output)
    if args.command == "plan":
        if args.repo:
            return plan_remote(args)
        if not args.profile:
            raise SystemExit("--profile is required with --repo-path")
        return plan_local_repo(args.repo_path, args.project_id, args.profile, args.output)
    if args.command == "upgrade":
        return upgrade_repo(
            args.repo_path,
            args.project_id,
            args.profile,
            args.dry_run,
            args.output,
        )
    if args.command == "migrate":
        return migrate_remote(args)
    if args.command == "verify":
        return verify_repo(args.repo_path, args.output)
    return doctor(args.profile, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
