"""The release check CI runs on every pull request: two tracks (docs/versioning.md#releases).

  tool changes (crucible/, pyproject.toml, tests/)   -> a version bump and a CHANGELOG.md entry
  task changes (tasks/, graders/, fixtures/, repos/) -> a SUITE_CHANGELOG.md entry, a clean lock and a
                                                       suite that still holds
  suites/*.yaml                                      -> may be added, never edited

    python -m crucible.ci --base <sha>
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

TOOL_PATHS = ("crucible/", "pyproject.toml", "tests/")
TASK_PATHS = ("tasks/", "graders/", "fixtures/", "repos/")
RULES = "see docs/versioning.md#releases"


def _under(paths: list[str], prefixes: tuple[str, ...]) -> list[str]:
    return [p for p in paths if p.startswith(prefixes) or p in prefixes]


def version_of(pyproject: str) -> str | None:
    match = re.search(r'(?m)^version = "(.*)"', pyproject)
    return match.group(1) if match else None


def problems(changed: list[str], modified: list[str], old_version: str | None, new_version: str | None,
             changelog: str, suite_changelog_added: list[str]) -> list[str]:
    """What the PR is missing. `changed` is every file it touches, `modified` the ones it edits (not adds),
    `suite_changelog_added` the lines it adds to SUITE_CHANGELOG.md."""
    found = []
    if _under(changed, TOOL_PATHS):
        if old_version == new_version:
            found.append(f"Tool changes need a version bump in pyproject.toml (still {new_version}); {RULES}")
        elif not re.search(rf"(?m)^## {re.escape(new_version or '')} ", changelog):
            found.append(f"Add '## {new_version} (YYYY-MM-DD)' to CHANGELOG.md; {RULES}")
    if _under(changed, TASK_PATHS) and not any(line.strip() for line in suite_changelog_added):
        found.append(f"Task changes need an entry under '## Unreleased' in SUITE_CHANGELOG.md; {RULES}")
    edited = [p for p in _under(modified, ("suites/",)) if p.endswith(".yaml")]
    if edited:
        found.append(f"Suite files are immutable ({', '.join(edited)}); cut or patch a new one; {RULES}")
    return found


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m crucible.ci", description="Two-track release check for a PR")
    parser.add_argument("--base", required=True, help="The PR's base commit")
    args = parser.parse_args()
    span = f"{args.base}...HEAD"
    changed = _git("diff", "--name-only", span).split()
    modified = _git("diff", "--name-only", "--diff-filter=M", span).split()
    added = [line[1:] for line in _git("diff", span, "--", "SUITE_CHANGELOG.md").splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    with open("pyproject.toml", encoding="utf-8") as f:
        new_version = version_of(f.read())
    with open("CHANGELOG.md", encoding="utf-8") as f:
        changelog = f.read()
    found = problems(changed, modified, version_of(_git("show", f"{args.base}:pyproject.toml")), new_version,
                     changelog, added)
    if _under(changed, TASK_PATHS):
        for command in (["versions"], ["suite", "verify"]):  # the lock matches; pinned tasks unchanged unless bumped
            if subprocess.run([sys.executable, "-m", "crucible.cli", *command]).returncode != 0:
                found.append(f"`crucible {' '.join(command)}` failed; {RULES}")
    for problem in found:
        print(f"::error::{problem}")
    if not found:
        print("Release check passed.")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
