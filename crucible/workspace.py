"""Everything about preparing a run on disk: prompts, run dirs, workspaces.

Layout: runs/<model_slug>/<category>/<test_id>/<timestamp>/ holding
prompt.txt, stdout.txt, stderr.txt, command.sh, meta.json, session.json and
(for agent runs) workspace/ with the seeded repo and fixtures.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from crucible import procs

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
FIXTURES_DIR = REPO_ROOT / "fixtures"
REPOS_DIR = REPO_ROOT / "repos"

# Marker file in a seeded repo -> command that installs its dependencies
DEPENDENCY_INSTALLERS = {
    "package.json": lambda: [procs.resolve_executable("npm"), "install"],
    "requirements.txt": lambda: [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
}


def all_test_ids() -> list[str]:
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.yaml"))


def load_prompt(test_id: str) -> dict:
    path = PROMPTS_DIR / f"{test_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def fixture_names(prompt_def: dict) -> list[str]:
    fixtures = prompt_def.get("fixtures") or []
    return [fixtures] if isinstance(fixtures, str) else list(fixtures)


@dataclass
class RunDir:
    run_id: str   # <model_slug>/<category>/<test_id>/<timestamp>
    path: Path    # absolute
    title: str    # unique session title for agents that support one


def new_run_dir(output_dir: Path, test_id: str, model: str | None, prompt_def: dict) -> RunDir:
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # Characters that are unsafe in directory names on any OS
    model_slug = re.sub(r'[/:\\<>"|?*]', "_", model or "default")
    category = prompt_def.get("category", "uncategorized")
    run_id = f"{model_slug}/{category}/{test_id}/{now}"
    path = (output_dir / run_id).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return RunDir(run_id=run_id, path=path, title=f"{now}_{test_id}_{model_slug}")


def _copy_into(src: Path, dest_dir: Path, contents_only: bool = False) -> None:
    """Copy a file or directory into dest_dir (a directory's contents if contents_only)."""
    items = list(src.iterdir()) if contents_only and src.is_dir() else [src]
    for item in items:
        if item.is_dir():
            shutil.copytree(item, dest_dir / item.name)
        else:
            shutil.copy2(item, dest_dir / item.name)


def setup_workspace(run_dir: Path, prompt_def: dict) -> Path:
    """Create workspace/: the seeded repo's contents plus fixtures, deps installed.

    Seeded repos are copied, never mutated.
    """
    workspace = run_dir / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    repo = prompt_def.get("repo")
    if repo and (REPOS_DIR / repo).exists():
        _copy_into(REPOS_DIR / repo, workspace, contents_only=True)
    for name in fixture_names(prompt_def):
        src = FIXTURES_DIR / name
        if src.exists():
            _copy_into(src, workspace)
        else:
            print(f"  Warning: fixture not found: {src}")

    _install_dependencies(workspace)
    return workspace


def _install_dependencies(workspace: Path) -> None:
    """Install a seeded repo's dependencies so the agent starts from a working tree."""
    marker = next((m for m in DEPENDENCY_INSTALLERS if (workspace / m).exists()), None)
    if marker is None:
        return
    print(f"  Installing dependencies ({marker})...")
    try:
        subprocess.run(DEPENDENCY_INSTALLERS[marker](), cwd=workspace,
                       capture_output=True, text=True)
    except FileNotFoundError as exc:
        print(f"  Warning: {exc}; skipping dependency install")


def inline_fixtures(prompt_text: str, fixtures: list[str]) -> str:
    """Append fixture contents to the prompt, for runs without file tools."""
    lines = [prompt_text.rstrip()]
    for name in fixtures:
        src = FIXTURES_DIR / name
        if not src.is_file():
            kind = "is a directory" if src.is_dir() else "not found"
            lines.append(f"\n[Fixture {kind}: {name}]")
            continue
        lines += ["\n---", f"FIXTURE: {name}", "---", src.read_text(encoding="utf-8")]
    return "\n".join(lines)
