# CLAUDE.md

@AGENTS.md

## Claude Code specifics

Skills in `.claude/skills/`, by job:
- `publish-results`: publish results to the dashboard.
- `add-task`: write a new chat task, or convert one to a scored answer block.
- `convert-grader`: convert a coding task to an isolated, per-test grader.
- `calibrate-task`: run a task on the calibration models and report whether it separates them.
- `cut-suite`: cut or patch a suite. Only when the user asks for it.

Rules:
- A PR touching `crucible/` or `pyproject.toml` carries the version bump and CHANGELOG entry;
  after merging, tag and cut the GitHub release before reporting the work as done.
- A PR touching only tasks carries a SUITE_CHANGELOG.md Unreleased entry and no version bump.
  Cutting a suite (`crucible suite cut`) is its own PR, and only when the user asks for it.
- Merges, pushes and suite cuts happen only when the user asks.
