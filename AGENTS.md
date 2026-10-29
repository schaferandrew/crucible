# AGENTS.md

Instructions for any coding agent working in this repo (Claude Code, opencode, pi, Codex...).
Read [README.md](README.md) for what Crucible is and how to run it; this file is the rules.

## Releases: two tracks

Crucible has two version numbers: the tool's (semver, `pyproject.toml`) and the suite's (which tasks
are scored, at which versions). A PR can be on one track or both. The full rules are in
[docs/versioning.md](docs/versioning.md); CI enforces them (`crucible/ci.py`).

### Tool changes (`crucible/`, `pyproject.toml`, `tests/`, `crucible/schemas/`)

These change what people install, so every one is a Crucible release:

1. Bump `version` in `pyproject.toml` (then `uv lock`):
   - **major**: an incompatible change to the CLI, the task YAML format, check or grader formats,
     harness names, the run record or bundle format, or the identity rules (slug format, `run_uuid`)
   - **minor**: new features, check types, harnesses, CLI or dashboard improvements
   - **patch**: fixes that change no behavior a user relies on
2. Add `## X.Y.Z (YYYY-MM-DD)` to `CHANGELOG.md`, for someone running Crucible (move anything under
   `## Unreleased` into it).
3. After merging: tag `vX.Y.Z` on the merge commit and publish the release:
   ```bash
   git fetch origin && git tag vX.Y.Z origin/main && git push origin vX.Y.Z
   gh release create vX.Y.Z --target origin/main --title "Crucible X.Y.Z" --notes-file <that version's changelog section>
   ```

### Task changes (`tasks/`, `graders/`, `fixtures/`, `repos/`)

These change the suite, not the tool. No version bump, no tag:

1. Bump the task's `version` (content changed, runs must be redone) or `rubric_version`
   (scoring changed, stored runs are rescored), then `uv run crucible versions --update`.
2. Add a line under `## Unreleased` in `SUITE_CHANGELOG.md`.
3. New tasks start `status: provisional`. Only `crucible suite cut` makes a task active, and only
   `crucible suite patch` publishes rubric fixes to a suite. Never edit `suites/*.yaml` by hand.
4. Validate checks against a correct and a wrong answer from real runs, and an empty answer
   (every check must fail it). Graders need `crucible grader <task>` to pass, with
   `seeded: [0, 0]` in the oracle.

Task IDs are kebab-case slugs and are not part of Crucible's versioned surface; renaming one
is a suite change (add the old one to `aliases`).

Docs-only PRs (README, AGENTS.md, `docs/`) need neither.

## Working on the code

- Python 3.9+, `uv`. Tests: `uv run --with pytest python -m pytest -q tests` (all must pass).
- macOS and Linux only. Don't add Windows code paths.
- These are benchmark **tasks**; "test" means software tests only (hidden tests, unit tests,
  `npm test`, the grader's test files).
- A task is `tasks/<slug>.yaml`: `id` (`^[a-z0-9]+(-[a-z0-9]+)*$`, at most 40 characters, says what
  the task is, never its tier, area or difficulty, never reused), `name`, `aliases` (earlier IDs).
  Its hidden grader, if any, is `graders/<slug>/`. Areas, categories, weights and tiers are suite
  data in `tasks/taxonomy.yaml`.
- After changing a task, its repo, fixtures, rubric, checks or grader: bump `version` or
  `rubric_version` (above), run `uv run crucible versions --update`, and
  `uv run crucible checks --doc docs/checks.md` to regenerate the rules doc.
- Score only the answer block: chat tasks ask for the answer in a delimited block with identical
  format wording across tasks, and checks read that block with a tolerant parser
  ([docs/scoring.md](docs/scoring.md)). Prefer deterministic scoring: `checks:` for answers,
  hidden grader tests for repos. A reference answer scores 10, an empty answer 0.
- Runs live in `runs/<model>/<task>/<timestamp>/`; `meta.json` is the run record, scores are
  score records in `scores/`, invalidations are status records ([docs/data-model.md](docs/data-model.md)).
  Never edit a run record; rescore (`crucible checks`) or mark it (`crucible status`).
- Never run git commands that switch branches in the user's checkout while a `crucible run`
  is active there (`pgrep -fl "crucible run"`); use `git worktree add` instead.

## Running models

- Never load or unload models in LM Studio or Ollama yourself. Models are often served from
  another machine over LM Link; loading one here can start it on this laptop instead.
- Never run local inference in parallel (one `crucible run` against a local server at a time).
- Cloud runs (OpenRouter) go one at a time too, so billed cost stays attributable.
- Scoring is automatic; never ask the user to grade. Human or AI-judge review is a future feature.

## Publishing results

`crucible publish` adds this machine's runs, score and status records to the portfolio's
`_data/crucible/` folder in bundle format 3 ([docs/bundle-format.md](docs/bundle-format.md)): it only
ever adds files, keyed by `run_uuid`, and validates everything it writes. Until the dashboard
switches to format 3, the live page reads the single format-2 file from `crucible export --format 2`.
Deploying is a commit and push in `schaferandrew.github.io`; see the `publish-results` skill.
