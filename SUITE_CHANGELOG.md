# Suite changelog

What changed in each suite: which tasks are scored, at which version and rubric version, with which
tiers and weights. Written for someone reading the leaderboard. Crucible's own releases (the tool)
are in [CHANGELOG.md](CHANGELOG.md); how the two version numbers work is in
[docs/versioning.md](docs/versioning.md).

Suites are cut with `crucible suite cut` (a new major) or `crucible suite patch` (rubric fixes, stored
runs rescored). Task changes between cuts go under `## Unreleased`.

## Unreleased

- fact-check-history (formerly HIST-2), now "Fact-check eight history claims": version 2, rubric 2,
  still provisional. The paragraph became eight numbered claims with one fact each, and the answer is
  an `ERRORS:` block of `<number>: <corrected value>` lines, scored as 13 equal items: the five errors
  found, their five corrections, and the three accurate claims left alone. This fixes a perfect answer
  scoring 5 (quoting "Runnymede" in the King John fix counted as flagging an accurate claim). Runs of
  version 1 no longer count; rerun it.

- novel-character-names (formerly WRIT-2) and names-for-one-character (WRIT-2b): rubric 3. An empty
  answer now scores 0 (it scored 4.0 and 2.0: an empty list had no repeated names and no undescribed
  ones). Only gemma-4-26b-a4b-qat's timed-out runs change.

## Suite v1 (2026-10-28)

The active tasks as scored on the dashboard on 2026-10-28: 24 tasks (21 chat, 3 agentic), at the
versions and rubric versions the dashboard counted that day, with the category weights it used.
Every run that counted on the dashboard counts in Suite v1 with the same score; scores from the AI
judge are not part of any suite (they stay in the run folders).

Suite v1 takes its name from the 2026.11 release (`releases/2026.11.yaml`, cut 2026-10-24), which
`suites/v1.yaml` keeps under `release_2026_11` for the record. The release had fallen behind the
tasks, so Suite v1 pins what was actually scored instead:

- **Newer versions:** fire-truck-color (formerly KNOW-1) rubric 2; seating-logic-puzzle (MATH-4) v2,
  rubric 2; two-calendar-slots-json (TASK-1) v2; morning-brief-priorities (TASK-3) v2; the proofreading
  and naming tasks (WRIT-1a rubric 3; WRIT-1b, WRIT-1c, WRIT-2, WRIT-2b rubric 2). The release pinned
  version 1 and rubric 1 for all of them.
- **Retired since the release:** explain-enshittification (KNOW-2), explain-solar-panels (KNOW-3),
  sink-leak-advice (KNOW-5), running-toilet-advice (KNOW-6), cold-window-advice (KNOW-7),
  furnace-wont-start-advice (KNOW-8).
- **Added:** the three evals, grade-palindrome-function (EVAL-1), grade-two-sentence-summary (EVAL-2)
  and grade-binary-search-answer (EVAL-3).
- **Weights:** the dashboard's category weights (coding_repo 0.10, reasoning 0.05, plus math,
  geography, history and evals at 0.05 each), not the release's (coding_repo 0.15, reasoning 0.10,
  no math, geography, history or evals).

Tasks were renamed to slugs in Crucible 3.0.0 (CODE-16 is now react-lead-form); the old IDs are
aliases, listed in [docs/task-id-map.json](docs/task-id-map.json). The rename changed no task.
