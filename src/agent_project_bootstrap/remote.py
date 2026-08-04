from __future__ import annotations

import base64
import difflib
import json
import os
import re
import tempfile

import yaml
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import __version__
from .discovery import discover_repository, infer_profile
from .lifecycle import LOCK_PATH, build_plan, lock_content, merge_managed
from .models import RepositoryProfile


class GitHubAPIError(RuntimeError):
    pass


class StaleRepositoryError(RuntimeError):
    pass


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        api_url: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.token = token
        self.api_url = (api_url or os.getenv("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"agent-project-bootstrap/{__version__}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            f"{self.api_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.status
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubAPIError(f"GitHub API {exc.code} for {method} {path}: {detail}") from exc
        except URLError as exc:
            raise GitHubAPIError(f"GitHub API request failed for {method} {path}: {exc}") from exc
        if status not in expected:
            raise GitHubAPIError(f"Unexpected GitHub API status {status} for {method} {path}")
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def get_repository(self, repository: str) -> dict[str, Any]:
        return self._request("GET", f"/repos/{repository}")

    def get_branch_sha(self, repository: str, branch: str) -> str:
        data = self._request("GET", f"/repos/{repository}/branches/{quote(branch, safe='')}")
        return str(data["commit"]["sha"])

    def get_tree(self, repository: str, sha: str) -> list[dict[str, Any]]:
        query = urlencode({"recursive": "1"})
        data = self._request("GET", f"/repos/{repository}/git/trees/{sha}?{query}")
        if data.get("truncated"):
            raise GitHubAPIError("Repository tree is truncated; remote migration refuses incomplete inventory")
        return list(data.get("tree", []))

    def get_file(self, repository: str, path: str, ref: str) -> str:
        encoded_path = quote(path, safe="/")
        query = urlencode({"ref": ref})
        data = self._request("GET", f"/repos/{repository}/contents/{encoded_path}?{query}")
        if data.get("encoding") != "base64" or "content" not in data:
            raise GitHubAPIError(f"Unsupported GitHub content response for {path}")
        raw = base64.b64decode(str(data["content"]).replace("\n", ""))
        return raw.decode("utf-8")

    def create_commit_on_branch(
        self,
        repository: str,
        branch: str,
        base_sha: str,
        files: dict[str, str],
        message: str,
    ) -> str:
        base_commit = self._request("GET", f"/repos/{repository}/git/commits/{base_sha}")
        base_tree_sha = str(base_commit["tree"]["sha"])
        entries: list[dict[str, str]] = []
        for path, content in sorted(files.items()):
            blob = self._request(
                "POST",
                f"/repos/{repository}/git/blobs",
                {"content": content, "encoding": "utf-8"},
                expected=(201,),
            )
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": str(blob["sha"])})
        tree = self._request(
            "POST",
            f"/repos/{repository}/git/trees",
            {"base_tree": base_tree_sha, "tree": entries},
            expected=(201,),
        )
        commit = self._request(
            "POST",
            f"/repos/{repository}/git/commits",
            {"message": message, "tree": tree["sha"], "parents": [base_sha]},
            expected=(201,),
        )
        self._request(
            "POST",
            f"/repos/{repository}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": commit["sha"]},
            expected=(201,),
        )
        return str(commit["sha"])

    def create_pull_request(
        self,
        repository: str,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{repository}/pulls",
            {"title": title, "body": body, "head": head, "base": base, "draft": draft},
            expected=(201,),
        )


@dataclass(slots=True)
class RemoteSnapshot:
    repository: str
    default_branch: str
    source_sha: str
    root: Path
    tree_paths: list[str]


@dataclass(slots=True)
class RemotePlanItem:
    path: str
    action: str
    reason: str
    diff: str | None = None
    proposed_content: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"path": self.path, "action": self.action, "reason": self.reason}
        if self.diff:
            data["diff"] = self.diff
        return data


@dataclass(slots=True)
class RemoteMigrationPlan:
    repository: str
    default_branch: str
    source_sha: str
    project_id: str
    profile: str
    profile_confidence: str
    discovered: RepositoryProfile
    branch: str
    items: list[RemotePlanItem]
    manual_review: list[str] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return any(item.action == "conflict" for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "default_branch": self.default_branch,
            "source_sha": self.source_sha,
            "project_id": self.project_id,
            "profile": self.profile,
            "profile_confidence": self.profile_confidence,
            "branch": self.branch,
            "has_conflicts": self.has_conflicts,
            "detected": self.discovered.to_dict(),
            "required_permissions": {
                "inspect": ["contents:read", "metadata:read"],
                "open_pr": ["contents:write", "pull_requests:write"],
            },
            "manual_review": self.manual_review,
            "items": [item.to_dict() for item in self.items],
        }


CORE_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "uv.lock",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Justfile",
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "ARCHITECTURE.md",
    "docs/architecture.md",
    ".github/copilot-instructions.md",
}
ENTRY_POINTS = {
    "src/main.py",
    "src/app.py",
    "app/main.py",
    "main.py",
    "src/index.ts",
    "src/index.tsx",
    "src/main.ts",
    "src/main.tsx",
    "src/app/page.tsx",
}
EXCLUDED_PARTS = {"node_modules", ".git", ".venv", "dist", "build", "coverage", "__pycache__"}


def _selected_path(path: str, managed_paths: set[str]) -> bool:
    parts = set(Path(path).parts)
    if parts & EXCLUDED_PARTS:
        return False
    if path in CORE_FILES or path in ENTRY_POINTS or path in managed_paths:
        return True
    if re.fullmatch(r"src/[^/]+/(?:cli|main|__main__)\.py", path):
        return True
    if path.startswith(".github/workflows/") and Path(path).suffix in {".yml", ".yaml"}:
        return True
    if Path(path).name == "manifest.json" and not path.startswith("benchmark/servers/"):
        return True
    return False


@contextmanager
def materialize_remote_repository(
    client: GitHubClient,
    repository: str,
    managed_paths: set[str] | None = None,
    base_branch: str | None = None,
) -> Iterator[RemoteSnapshot]:
    metadata = client.get_repository(repository)
    branch = base_branch or str(metadata["default_branch"])
    source_sha = client.get_branch_sha(repository, branch)
    tree = client.get_tree(repository, source_sha)
    blobs = [entry for entry in tree if entry.get("type") == "blob"]
    paths = sorted(str(entry["path"]) for entry in blobs)
    selected = [path for path in paths if _selected_path(path, managed_paths or set())]

    with tempfile.TemporaryDirectory(prefix="agent-bootstrap-remote-") as temporary:
        root = Path(temporary)
        top_directories = sorted({path.split("/", 1)[0] for path in paths if "/" in path})
        for directory in top_directories:
            if directory not in EXCLUDED_PARTS:
                (root / directory).mkdir(parents=True, exist_ok=True)
        for path in selected:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                content = client.get_file(repository, path, source_sha)
            except UnicodeDecodeError:
                continue
            target.write_text(content, encoding="utf-8")
        yield RemoteSnapshot(
            repository=repository,
            default_branch=branch,
            source_sha=source_sha,
            root=root,
            tree_paths=paths,
        )


def inspect_remote_snapshot(snapshot: RemoteSnapshot) -> dict[str, Any]:
    profile = discover_repository(snapshot.root)
    detected_profile, confidence = infer_profile(profile)
    return {
        "repository": snapshot.repository,
        "default_branch": snapshot.default_branch,
        "source_sha": snapshot.source_sha,
        "detected_profile": detected_profile,
        "profile_confidence": confidence,
        "profile": profile.to_dict(),
    }


def _unified_diff(path: str, existing: str, proposed: str) -> str:
    return "".join(
        difflib.unified_diff(
            existing.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=f"a/{path}" if existing else "/dev/null",
            tofile=f"b/{path}",
        )
    )


def _branch_name(project_id: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", project_id.lower()).strip("-")
    return f"agent-bootstrap/{slug}-v{__version__}"


def build_remote_plan(
    snapshot: RemoteSnapshot,
    project_id: str,
    profile_name: str,
    rendered_files: dict[Path, str],
) -> RemoteMigrationPlan:
    discovered = discover_repository(snapshot.root)
    inferred_profile, profile_confidence = infer_profile(discovered)
    if inferred_profile != profile_name:
        profile_confidence = "medium" if inferred_profile else "low"

    initial_plan = build_plan(snapshot.root, project_id, profile_name, rendered_files)
    initial_actions = {item.path: item.action for item in initial_plan.items}
    final_managed: dict[Path, str] = {}
    for relative, rendered in rendered_files.items():
        target = snapshot.root / relative
        action = initial_actions[str(relative)]
        if action == "conflict":
            continue
        if action == "merge":
            merged = merge_managed(target.read_text(encoding="utf-8"), rendered)
            if merged is not None:
                final_managed[relative] = merged
        elif action == "unchanged":
            final_managed[relative] = target.read_text(encoding="utf-8")
        else:
            final_managed[relative] = rendered

    rendered_with_lock = dict(rendered_files)
    rendered_with_lock[LOCK_PATH] = lock_content(profile_name, final_managed)
    local_plan = build_plan(snapshot.root, project_id, profile_name, rendered_with_lock)

    action_names = {
        "create": "create",
        "unchanged": "unchanged",
        "update": "safe-update",
        "merge": "managed-merge",
        "conflict": "conflict",
    }
    items: list[RemotePlanItem] = []
    for local_item in local_plan.items:
        relative = Path(local_item.path)
        target = snapshot.root / relative
        existing = target.read_text(encoding="utf-8") if target.is_file() else ""
        rendered = rendered_with_lock[relative]
        effective_action = local_item.action
        effective_reason = local_item.reason
        if relative == LOCK_PATH and target.is_file() and local_item.action == "conflict":
            try:
                current_lock = yaml.safe_load(existing)
            except yaml.YAMLError:
                current_lock = None
            if isinstance(current_lock, dict) and current_lock.get("generator") == "sumyann/agent-project-bootstrap":
                effective_action = "update"
                effective_reason = "recognized bootstrap lock can be refreshed safely"
        proposed: str | None
        if effective_action == "merge":
            proposed = merge_managed(existing, rendered)
        elif effective_action == "unchanged":
            proposed = existing
        else:
            proposed = rendered
        diff = None
        if effective_action != "unchanged" and proposed is not None:
            diff = _unified_diff(local_item.path, existing, proposed)
        items.append(
            RemotePlanItem(
                path=local_item.path,
                action=action_names[effective_action],
                reason=effective_reason,
                diff=diff,
                proposed_content=proposed,
            )
        )

    manual_review = [
        f"Resolve customized file conflict: {item.path}"
        for item in items
        if item.action == "conflict"
    ]
    if profile_confidence != "high":
        manual_review.append(f"Confirm selected profile {profile_name!r}; detection confidence is {profile_confidence}")
    for name, inference in discovered.command_inference.items():
        if inference.confidence in {"low", "unknown"}:
            manual_review.append(f"Confirm {name} command: {inference.command}")

    return RemoteMigrationPlan(
        repository=snapshot.repository,
        default_branch=snapshot.default_branch,
        source_sha=snapshot.source_sha,
        project_id=project_id,
        profile=profile_name,
        profile_confidence=profile_confidence,
        discovered=discovered,
        branch=_branch_name(project_id),
        items=items,
        manual_review=manual_review,
    )


def pull_request_body(plan: RemoteMigrationPlan) -> str:
    applied = [item for item in plan.items if item.action in {"create", "safe-update", "managed-merge"}]
    conflicts = [item for item in plan.items if item.action == "conflict"]
    command_lines = []
    for name, inference in sorted(plan.discovered.command_inference.items()):
        evidence = ", ".join(inference.evidence)
        command_lines.append(f"- `{name}`: `{inference.command}` ({inference.confidence}; {evidence})")
    return "\n".join(
        [
            "## Summary",
            "",
            f"Bootstraps `{plan.repository}` for safe AI-agent development using Agent Project Bootstrap v{__version__}.",
            "",
            "## Source evidence",
            "",
            f"- Base branch: `{plan.default_branch}`",
            f"- Inspected commit: `{plan.source_sha}`",
            f"- Selected profile: `{plan.profile}` ({plan.profile_confidence} confidence)",
            "",
            "## Proposed changes",
            "",
            *([f"- `{item.path}` — {item.action}" for item in applied] or ["- No safe file changes detected."]),
            "",
            "## Verified or inferred commands",
            "",
            *(command_lines or ["- No commands could be inferred with repository evidence."]),
            "",
            "## Preserved for manual review",
            "",
            *([f"- `{item.path}` — existing customization was not modified" for item in conflicts] or ["- No unmergeable conflicts detected."]),
            *([f"- {item}" for item in plan.manual_review] if plan.manual_review else []),
            "",
            "## Safety",
            "",
            "- No application source code is modified.",
            "- Existing unmarked custom files are never overwritten.",
            "- This pull request is created as a draft and is never merged automatically.",
        ]
    )


def open_remote_migration_pr(
    client: GitHubClient,
    plan: RemoteMigrationPlan,
    draft: bool = True,
) -> dict[str, Any]:
    current_sha = client.get_branch_sha(plan.repository, plan.default_branch)
    if current_sha != plan.source_sha:
        raise StaleRepositoryError(
            f"Repository changed after inspection: expected {plan.source_sha}, found {current_sha}. Re-run inspection."
        )
    files = {
        item.path: item.proposed_content
        for item in plan.items
        if item.action in {"create", "safe-update", "managed-merge"}
        and item.proposed_content is not None
    }
    if not files:
        raise GitHubAPIError("Migration plan contains no safe changes to commit")
    commit_sha = client.create_commit_on_branch(
        plan.repository,
        plan.branch,
        plan.source_sha,
        files,
        f"Bootstrap repository for AI-agent development with v{__version__}",
    )
    pr = client.create_pull_request(
        plan.repository,
        "Bootstrap repository for AI-agent development",
        pull_request_body(plan),
        plan.branch,
        plan.default_branch,
        draft=draft,
    )
    return {
        "repository": plan.repository,
        "branch": plan.branch,
        "commit_sha": commit_sha,
        "pull_request_number": pr.get("number"),
        "pull_request_url": pr.get("html_url"),
        "draft": bool(pr.get("draft", draft)),
        "conflicts_skipped": [item.path for item in plan.items if item.action == "conflict"],
    }
