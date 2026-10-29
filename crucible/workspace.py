"""Everything about preparing a run on disk: tasks, run dirs, workspaces.

Layout: runs/<model_slug>/<task>/<timestamp>/ holding prompt.txt, stdout.txt,
stderr.txt, command.sh, meta.json (the run record, see crucible/runrecord.py),
session.json, scores/ and (for agent runs) workspace/ with the seeded repo and fixtures.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from crucible import procs

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"
# Every ID a task has had (CODE-16, and C16 before that) -> its slug; task files' aliases add to it
ID_MAP_PATH = REPO_ROOT / "docs" / "task-id-map.json"
# Files in tasks/ that aren't tasks
NOT_TASKS = {"taxonomy"}
FIXTURES_DIR = REPO_ROOT / "fixtures"
REPOS_DIR = REPO_ROOT / "repos"

# Marker file in a seeded repo -> command that installs its dependencies. A repo with a lockfile
# installs exactly what it pins (npm ci), so every run starts from the same dependency tree.
DEPENDENCY_INSTALLERS = {
    "package.json": lambda ws: [procs.resolve_executable("npm"), "ci" if (ws / "package-lock.json").exists() else "install"],
    "requirements.txt": lambda ws: [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
}


def all_task_ids() -> list[str]:
    return sorted(p.stem for p in TASKS_DIR.glob("*.yaml") if p.stem not in NOT_TASKS)


def _read_task(slug: str) -> dict:
    return yaml.safe_load((TASKS_DIR / f"{slug}.yaml").read_text(encoding="utf-8"))


def aliases() -> dict[str, str]:
    """Every earlier ID, lowercased -> the task's slug: the ID map plus each task's own `aliases:`."""
    import json
    found = {}
    if ID_MAP_PATH.exists():
        found = {old.lower(): entry["id"] for old, entry in json.loads(ID_MAP_PATH.read_text(encoding="utf-8")).items()}
    for slug in all_task_ids():
        found.update({str(a).lower(): slug for a in _read_task(slug).get("aliases") or []})
    return found


def resolve(name: str) -> tuple[str, str | None]:
    """(slug, the alias it was named by, or None) for a slug or any earlier ID; KeyError if unknown."""
    if name in all_task_ids():
        return name, None
    slug = aliases().get(name.lower()) or (name.lower() if name.lower() in all_task_ids() else None)
    if slug is None:
        raise KeyError(name)
    return slug, (None if slug == name.lower() else name)


def load_task(name: str) -> dict:
    """A task by its slug or any earlier ID (CODE-16, C16)."""
    try:
        slug, _ = resolve(name)
    except KeyError:
        raise FileNotFoundError(f"Task not found: {name} (no tasks/{name}.yaml and no task has it as an alias)") from None
    return _read_task(slug)


def fixture_names(prompt_def: dict) -> list[str]:
    fixtures = prompt_def.get("fixtures") or []
    return [fixtures] if isinstance(fixtures, str) else list(fixtures)


@dataclass
class RunDir:
    run_path: str  # <model_slug>/<task>/<timestamp>
    path: Path    # absolute
    title: str    # unique session title for agents that support one
    run_uuid: str = ""  # permanent identity: survives renames and moves, unique across machines


def model_slug(model: str | None, reasoning: str = "default") -> str:
    """A run folder's model name; each reasoning level gets its own folder."""
    from crucible.reasoning import slug_suffix
    # Characters that are unsafe in directory names
    return re.sub(r'[/:\\<>"|?*]', "_", model or "default") + slug_suffix(reasoning)


def new_run_dir(output_dir: Path, task_id: str, model: str | None, reasoning: str = "default") -> RunDir:
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = model_slug(model, reasoning)
    run_path = f"{slug}/{task_id}/{now}"
    path = (output_dir / run_path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return RunDir(run_path=run_path, path=path, title=f"{now}_{task_id}_{slug}", run_uuid=str(uuid.uuid4()))


def _copy_into(src: Path, dest_dir: Path, contents_only: bool = False) -> None:
    """Copy a file or directory into dest_dir (a directory's contents if contents_only)."""
    items = list(src.iterdir()) if contents_only and src.is_dir() else [src]
    for item in items:
        if item.is_dir():
            shutil.copytree(item, dest_dir / item.name)
        else:
            shutil.copy2(item, dest_dir / item.name)


def workspaces_root() -> Path:
    """Where agents work: outside crucible's checkout (CRUCIBLE_WORKSPACES overrides)."""
    return Path(os.environ.get("CRUCIBLE_WORKSPACES") or Path.home() / ".crucible" / "workspaces")


def setup_workspace(run_dir: Path, prompt_def: dict) -> Path:
    """Create the workspace: the seeded repo's contents plus fixtures, deps installed.

    It lives outside crucible's checkout, linked from <run_dir>/workspace, because an
    agent that searches upward from inside the checkout finds the hidden graders,
    every prompt's rubric and other models' runs. finalize_workspace() moves it back
    into the run directory when the run ends. Seeded repos are copied, never mutated.
    """
    link = run_dir / "workspace"
    workspace = workspaces_root() / "_".join(run_dir.parts[-3:])
    for stale in (link, workspace):
        if stale.is_symlink():
            stale.unlink()
        elif stale.exists():
            shutil.rmtree(stale)
    workspace.mkdir(parents=True)
    try:
        link.symlink_to(workspace, target_is_directory=True)
    except OSError:
        # e.g. a filesystem without symlinks: fall back to working inside the run dir
        print("  Warning: could not link an outside workspace; the agent will work inside crucible's checkout")
        shutil.rmtree(workspace)
        workspace = link
        workspace.mkdir()

    repo = prompt_def.get("repo")
    if repo and (REPOS_DIR / repo).exists():
        _copy_into(REPOS_DIR / repo, workspace, contents_only=True)
    for name in fixture_names(prompt_def):
        src = FIXTURES_DIR / name
        if src.exists():
            _copy_into(src, workspace)
        else:
            print(f"  Warning: fixture not found: {src}")

    _isolate_git(workspace)
    _install_dependencies(workspace)
    return workspace


def finalize_workspace(run_dir: Path) -> None:
    """Move an outside workspace back into its run directory, so the run is self-contained."""
    link = run_dir / "workspace"
    if not link.is_symlink():
        return
    target = link.resolve()
    link.unlink()
    if target.exists():
        shutil.move(str(target), str(link))


def _isolate_git(workspace: Path) -> None:
    """Make the workspace its own git repository with the seeded state as the first commit.

    Run directories live inside crucible's own checkout, so without this, git commands in a
    workspace see crucible itself, including the hidden graders in graders/. Its own repo also
    lets an agent diff its changes against the seeded starting point.
    """
    if (workspace / ".git").exists():
        return
    env = {"GIT_AUTHOR_NAME": "crucible", "GIT_AUTHOR_EMAIL": "crucible@localhost",
           "GIT_COMMITTER_NAME": "crucible", "GIT_COMMITTER_EMAIL": "crucible@localhost"}
    gitignore = workspace / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("node_modules/\n.next/\ndist/\n__pycache__/\n.venv/\n", encoding="utf-8")
    try:
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     ["commit", "-q", "--no-gpg-sign", "-m", "Seeded workspace"]):
            subprocess.run(["git", *args], cwd=workspace, capture_output=True, text=True, check=True,
                           env={**os.environ, **env})
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"  Warning: could not give the workspace its own git repo ({exc}); git here sees the parent repo")


def _install_dependencies(workspace: Path) -> None:
    """Install a seeded repo's dependencies so the agent starts from a working tree."""
    marker = next((m for m in DEPENDENCY_INSTALLERS if (workspace / m).exists()), None)
    if marker is None:
        return
    print(f"  Installing dependencies ({marker})...")
    try:
        subprocess.run(DEPENDENCY_INSTALLERS[marker](workspace), cwd=workspace,
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
