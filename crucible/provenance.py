"""Which crucible produced a run, and on which machine: recorded in every new run's meta.json.

A run from a modified checkout (an edited grader, a changed prompt) is flagged by
`crucible_dirty`, so its score can be told apart from one the released code produced.
Everything is best effort: outside a git checkout the commit and dirty flag are None.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Changes here can move a score; changes elsewhere (docs, tests) can't
SCORED_PATHS = ("crucible", "tasks", "graders", "fixtures", "repos")


def crucible_version() -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version("crucible")
    except (ImportError, PackageNotFoundError):
        return None


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _in_checkout() -> bool:
    """True when crucible runs from its own git checkout (not an install inside some other repo)."""
    top = _git("rev-parse", "--show-toplevel")
    return bool(top) and Path(top).resolve() == REPO_ROOT


def machine_file() -> Path:
    return Path(os.environ.get("CRUCIBLE_MACHINE_FILE") or Path.home() / ".crucible" / "machine.json")


def machine_id() -> str | None:
    """A random ID for this machine, minted once; never the hostname (it changes, and it's personal)."""
    path = machine_file()
    try:
        found = json.loads(path.read_text(encoding="utf-8")).get("machine_id")
        if found:
            return found
    except (OSError, ValueError, AttributeError):
        pass
    minted = f"m_{uuid.uuid4().hex[:12]}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"machine_id": minted}, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return None
    return minted


def capture() -> dict:
    in_git = _in_checkout()
    status = _git("status", "--porcelain", "--", *SCORED_PATHS) if in_git else None
    return {
        "crucible_version": crucible_version(),
        "crucible_commit": _git("rev-parse", "--short", "HEAD") if in_git else None,
        "crucible_dirty": bool(status) if status is not None else None,
        "machine_id": machine_id(),
    }
