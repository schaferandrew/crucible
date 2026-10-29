# Versioning

The one canonical copy of how Crucible and its suites are versioned. AGENTS.md, CLAUDE.md and the
README carry a short checklist that links here; CI (`crucible/ci.py`), the version lock and
`crucible suite verify` enforce it. Why it's built this way is recorded in
[v-next-audit.md](v-next-audit.md), sections 3 and 5.

## Two version numbers

- **Crucible** (`pyproject.toml`) is semver for what people install: the CLI, the task YAML
  format, harnesses, check and grader formats, the scoring engine, the run record and bundle
  formats, and the identity rules.
- **The suite** (`suites/v2.yaml`) is which tasks are scored, at which `version` and
  `rubric_version`, with which tiers, categories and weights.

Which tasks exist, their slugs, names, tiers, areas, categories and weights are suite data, not
part of Crucible's stable surface: adding, retiring or renaming a task never needs a Crucible major.

## Releases

A pull request is on one track or both, by the paths it touches.

### Tool changes (`crucible/`, `pyproject.toml`, `tests/`, `crucible/schemas/`)

Every one is a Crucible release: bump `version` in `pyproject.toml` (then `uv lock`), add
`## X.Y.Z (YYYY-MM-DD)` to `CHANGELOG.md`, and after merging tag `vX.Y.Z` and `gh release create`.

| Bump | When |
|---|---|
| major | An incompatible change to the CLI, the task YAML format, check or grader formats, harness names, the run record or bundle format (`format_version`), or the identity rules (slug format, `run_uuid`) |
| minor | New features, check types, harnesses, additive bundle fields (`format_revision`), CLI or dashboard improvements |
| patch | Fixes that change no behavior a user relies on |

### Task changes (`tasks/`, `graders/`, `fixtures/`, `repos/`)

No version bump and no tag. Bump the task's `version` or `rubric_version` (below), run
`crucible versions --update`, and add a line under `## Unreleased` in `SUITE_CHANGELOG.md`.

### Suite files

`suites/*.yaml` are written only by `crucible suite cut` and `crucible suite patch`, and never
edited afterwards. CI fails a PR that modifies one.

Docs-only PRs need neither track.

## Task versions

A task's **content** is everything the model sees or works on: the prompt, whether it gets tools,
the seeded repo, fixtures and mock MCP data. Its **rubric** is everything the scorer uses: rubric,
checks, scoring mode and the hidden grader's files. They version separately:

| Changed | Bump | Old runs |
|---|---|---|
| content | `version` | No longer comparable; rerun |
| rubric | `rubric_version` | Rescored from stored outputs (`crucible checks`); no rerun |

`tasks/versions.lock.json` records the hashes each declared version was cut from. `crucible
versions` fails when a hash changed without a bump, or a version was bumped without a change.
The task's ID, name and aliases aren't hashed: renaming a task changes no hash and needs no bump.

## Suites

Suites are named `v<major>.<patch>`, written "Suite v2", "Suite v2.1".

| Change | Suite |
|---|---|
| Promote or retire a task, a task `version` bump, tier, category, area or weight changes, slug renames, gate or coverage thresholds | new major (`crucible suite cut v3 --promote … --retire …`) |
| `rubric_version` bumps that fix a check or grader | patch (`crucible suite patch`); stored runs are rescored |
| Adding, editing or removing provisional tasks; names and summaries | none |

A suite file pins, per active task: `id`, `version`, `rubric_version`, `content_hash`,
`rubric_hash`, `tier`, `category` and `weight` (the category's weight split across its tasks), plus
the tiers with their gates and the scoring policy. A patch file is a full copy, so each file stands
alone.

**Cutting.** Tasks land `provisional` at any time; they run, publish and show on the dashboard, and
never count. `crucible suite cut` promotes and retires tasks, writes the suite from the lock and
moves `## Unreleased` in SUITE_CHANGELOG.md under the new suite's heading. It refuses when the lock
isn't clean, the changelog has nothing under Unreleased, or a promoted task's grader fails
`crucible grader`. Promotion criteria: runs from at least one small local, one mid-size and one
frontier model, scores that aren't all equal, and for graders, a passing oracle.

**Verifying.** `crucible suite verify` checks the latest suite still holds: a pinned task's content
and rubric haven't changed without a version bump, and only a cut changed which tasks are active.

**Membership is derived, never stored on runs.** A run counts in every suite that pins its task at
the version it ran, scored by the score record at that suite's rubric version. A run from October
still counts in Suite v3 if its task didn't change.

## Bundle format

`format_version` (an integer) changes only for breaking format changes: a removed or renamed field,
a changed type or meaning, a new file layout or identity keys. That's a Crucible major. Additive
optional fields bump `format_revision`, which is always safe to read. A reader that meets a higher
`format_version` skips the file and says so, never errors. See [bundle-format.md](bundle-format.md).

| Change | Bundle | Suite | Crucible |
|---|---|---|---|
| Add a task to an existing area and category | data-only | provisional: none; promoting it: new suite | none |
| Retire a task; change its name, summary or prompt text shown | data-only | new suite (retire) / none (name) | none |
| Task `version` bump | data-only | new suite major | none |
| Task `rubric_version` bump | data-only | suite patch | none |
| Change category weights or tier gates | data-only | new suite major | none |
| Add an area, category or tier | data-only | new suite major | none |
| Rename an area, category or tier ID | breaking (old runs reference it) | new suite major | minor (exporter maps) |
| Add an optional field | `format_revision` + 1 | none | minor |
| Remove or rename a field, change its type or meaning, the layout or identity keys | `format_version` + 1 | none | **major** |
| Rename task IDs | data-only (`aliases`) | new suite major | none |
