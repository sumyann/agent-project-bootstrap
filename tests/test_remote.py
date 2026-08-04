import pytest

from agent_project_bootstrap.cli import render_target_files
from agent_project_bootstrap.remote import (
    StaleRepositoryError,
    build_remote_plan,
    inspect_remote_snapshot,
    materialize_remote_repository,
    open_remote_migration_pr,
)


PYPROJECT = '''[project]
name = "example-service"
[project.scripts]
example-service = "example_service.cli:app"
[tool.ruff]
line-length = 100
[tool.pytest.ini_options]
testpaths = ["tests"]
'''
WORKFLOW = '''name: CI
jobs:
  test:
    steps:
      - run: ruff check .
      - run: python -m pytest
'''


class FakeClient:
    def __init__(self, shas=None):
        self.shas = list(shas or ["abc123", "abc123"])
        self.writes = []
        self.files = {
            "pyproject.toml": PYPROJECT,
            ".github/workflows/ci.yml": WORKFLOW,
            "README.md": "# Example Service\n",
            "src/example_service/cli.py": "def app(): pass\n",
        }

    def get_repository(self, repository):
        return {"default_branch": "main"}

    def get_branch_sha(self, repository, branch):
        return self.shas.pop(0) if len(self.shas) > 1 else self.shas[0]

    def get_tree(self, repository, sha):
        return [
            {"path": path, "type": "blob", "sha": f"sha-{index}"}
            for index, path in enumerate(self.files)
        ]

    def get_file(self, repository, path, ref):
        return self.files[path]

    def create_commit_on_branch(self, repository, branch, base_sha, files, message):
        self.writes.append(("commit", repository, branch, base_sha, files, message))
        return "commit123"

    def create_pull_request(self, repository, title, body, head, base, draft=True):
        self.writes.append(("pr", repository, title, head, base, draft, body))
        return {"number": 7, "html_url": "https://example.test/pr/7", "draft": draft}


def _plan(client):
    managed = {
        str(path) for path in render_target_files("example-service", "python-service")
    }
    with materialize_remote_repository(
        client,
        "acme/example-service",
        managed_paths=managed,
    ) as snapshot:
        rendered = render_target_files(
            "example-service",
            "python-service",
            snapshot.root,
        )
        return snapshot, build_remote_plan(
            snapshot,
            "example-service",
            "python-service",
            rendered,
        )


def test_remote_inspection_uses_repository_evidence() -> None:
    client = FakeClient()
    managed = {
        str(path) for path in render_target_files("example-service", "python-service")
    }
    with materialize_remote_repository(
        client,
        "acme/example-service",
        managed_paths=managed,
    ) as snapshot:
        result = inspect_remote_snapshot(snapshot)
    assert result["detected_profile"] == "python-service"
    assert result["profile_confidence"] == "high"
    inference = result["profile"]["command_inference"]
    assert inference["test"]["command"] == "python -m pytest"
    assert inference["test"]["confidence"] == "high"
    assert "src/example_service/cli.py" in result["profile"]["entry_points"]
    assert client.writes == []


def test_remote_plan_is_non_writing_and_includes_lock() -> None:
    client = FakeClient()
    _, plan = _plan(client)
    actions = {item.path: item.action for item in plan.items}
    assert actions[".project/bootstrap-lock.yaml"] == "create"
    assert actions["ARCHITECTURE.md"] == "create"
    assert client.writes == []
    assert plan.profile_confidence == "high"


def test_open_pr_rechecks_source_sha() -> None:
    client = FakeClient(shas=["abc123", "changed456"])
    _, plan = _plan(client)
    with pytest.raises(StaleRepositoryError):
        open_remote_migration_pr(client, plan)
    assert client.writes == []


def test_open_pr_creates_single_commit_and_draft_pr() -> None:
    client = FakeClient(shas=["abc123", "abc123"])
    _, plan = _plan(client)
    result = open_remote_migration_pr(client, plan)
    assert result["pull_request_number"] == 7
    assert result["draft"] is True
    assert [write[0] for write in client.writes] == ["commit", "pr"]
    committed_files = client.writes[0][4]
    assert ".project/manifest.yaml" in committed_files
    assert "src/example_service/cli.py" not in committed_files
