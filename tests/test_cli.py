import subprocess
import sys
from pathlib import Path

from agent_project_bootstrap.cli import audit_repo, init_repo, render_target_files
from agent_project_bootstrap.discovery import discover_repository
from agent_project_bootstrap.lifecycle import apply_plan, build_plan, read_lock, write_lock
from agent_project_bootstrap.verification import verify_repository


def test_init_audit_and_verify(tmp_path: Path) -> None:
    assert init_repo(tmp_path, "demo-project", "python-service", force=False) == 0
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "ARCHITECTURE.md").is_file()
    assert (tmp_path / ".project" / "bootstrap-lock.yaml").is_file()
    assert audit_repo(tmp_path, "python-service") == 0
    findings = verify_repository(tmp_path)
    assert not [finding for finding in findings if finding.level == "error"]


def test_generated_verifier_runs_outside_repository_root(tmp_path: Path) -> None:
    repository = tmp_path / "demo-project"
    repository.mkdir()
    assert init_repo(repository, "demo-project", "python-service", force=False) == 0

    result = subprocess.run(
        [sys.executable, str(repository / "scripts" / "verify-agent-harness.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Agent harness verification passed." in result.stdout


def test_existing_file_is_not_overwritten(tmp_path: Path) -> None:
    target = tmp_path / "CLAUDE.md"
    target.write_text("custom", encoding="utf-8")
    init_repo(tmp_path, "demo-project", "python-service", force=False)
    assert target.read_text(encoding="utf-8") == "custom"
    assert "CLAUDE.md" not in read_lock(tmp_path).get("managed_files", {})
    plan = build_plan(
        tmp_path,
        "demo-project",
        "python-service",
        render_target_files("demo-project", "python-service", tmp_path),
    )
    assert {item.path: item.action for item in plan.items}["CLAUDE.md"] == "conflict"


def test_discovery_detects_typescript_browser_extension(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export {};", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest","build":"vite build"},"dependencies":{"react":"latest"}}',
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        '{"manifest_version":3}', encoding="utf-8"
    )

    profile = discover_repository(tmp_path)
    assert "typescript" in profile.languages
    assert "react" in profile.frameworks
    assert "browser-extension" in profile.frameworks
    assert profile.package_managers == ["npm"]
    assert profile.commands["test"] == "npm run test"
    assert profile.command_inference["test"].confidence == "medium"


def test_managed_upgrade_preserves_custom_content(tmp_path: Path) -> None:
    rendered = render_target_files("demo-project", "python-service")
    for relative, content in rendered.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    write_lock(tmp_path, "python-service", rendered)

    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "Custom owner note.\n\n" + agents.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    plan = build_plan(tmp_path, "demo-project", "python-service", rendered)
    action = {item.path: item.action for item in plan.items}["AGENTS.md"]
    assert action == "merge"
    apply_plan(tmp_path, plan, rendered)
    assert agents.read_text(encoding="utf-8").startswith("Custom owner note.")


def test_unmanaged_customization_is_conflict(tmp_path: Path) -> None:
    init_repo(tmp_path, "demo-project", "python-service", force=False)
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("custom instructions", encoding="utf-8")
    rendered = render_target_files("demo-project", "python-service")
    plan = build_plan(tmp_path, "demo-project", "python-service", rendered)
    action = {item.path: item.action for item in plan.items}["CLAUDE.md"]
    assert action == "conflict"


def test_verification_detects_project_id_mismatch(tmp_path: Path) -> None:
    init_repo(tmp_path, "demo-project", "python-service", force=False)
    progress = tmp_path / ".project" / "progress.yaml"
    progress.write_text(
        progress.read_text(encoding="utf-8").replace(
            "demo-project", "other-project", 1
        ),
        encoding="utf-8",
    )
    findings = verify_repository(tmp_path)
    assert any("project IDs do not match" in finding.message for finding in findings)
