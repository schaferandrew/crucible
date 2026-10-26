# AGENTS.md

Instructions for any coding agent working in this repo (Claude Code, opencode, pi, Codex...).
Read [README.md](README.md) for what Crucible is and how to run it; this file is the rules.

## Every change that lands on `main` is a release

This is the rule most easily missed, and CI enforces it on pull requests.

1. **Bump the version** in `pyproject.toml` (then `uv lock`) following the policy at the top of
   [CHANGELOG.md](CHANGELOG.md):
   - **major**: an incompatible change to the stable surface: test IDs, the chat/agentic
     sections, harness names, the CLI, or the results bundle format
     (`crucible/schemas/results.schema.json`)
   - **minor**: new tests, areas, harness features, test version bumps, CLI or dashboard
     improvements
   - **patch**: fixes that change no behavior a user relies on
2. **Add a changelog entry** under a new `## X.Y.Z (YYYY-MM-DD)` heading in `CHANGELOG.md`
   (move anything under `## Unreleased` into it). Say what changed for someone running
   Crucible, not how the code changed.
3. **After the PR merges**, tag the merge commit and publish the release:
   ```bash
   git fetch origin && git tag vX.Y.Z origin/main && git push origin vX.Y.Z
   gh release create vX.Y.Z --target origin/main --title "Crucible X.Y.Z" --notes-file <that version's changelog section>
   ```

Docs-only PRs (README, AGENTS.md, comments) don't need a release; CI only checks PRs that touch
`crucible/`, `prompts/`, `graders/`, `fixtures/`, `repos/` or `pyproject.toml`.

## Working on the code

- Python 3.9+, `uv`. Tests: `uv run --with pytest python -m pytest -q tests` (all must pass).
- macOS and Linux only. Don't add Windows code paths.
- After changing a prompt, its repo, fixtures, rubric, checks or graders:
  `uv run crucible versions --update`, and bump the test's `version` (content changed) or
  `rubric_version` (scoring changed); `uv run crucible checks --doc docs/checks.md` regenerates
  the rules doc. Old runs stop counting until rerun; that's intended.
- Test IDs are the area's four letters, a hyphen and a number (`CODE-11`, `WRIT-2b`); see
  `crucible/taxonomy.py`. Renaming an ID is a major version.
- New tests start `status: provisional`. Prefer deterministic scoring: `checks:` for answers,
  hidden grader tests for repos. Validate checks against a correct and a wrong answer.
- Never run git commands that switch branches in the user's checkout while a `crucible run`
  is active there (`pgrep -fl "crucible run"`); use `git worktree add` instead.

## Running models

- Never load or unload models in LM Studio or Ollama yourself. Models are often served from
  another machine over LM Link; loading one here can start it on this laptop instead.
- Never run local inference in parallel (one `crucible run` against a local server at a time).
- Cloud runs (OpenRouter) go one at a time too, so billed cost stays attributable.
- Scoring is automatic; never ask the user to grade. Human or AI-judge review is a future feature.

## Publishing results

`crucible publish` writes this machine's results into the portfolio's `_data/crucible/`
folder. Deploying is a commit and push of that folder in `schaferandrew.github.io`; see the
`publish-results` skill.
