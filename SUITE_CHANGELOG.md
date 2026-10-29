# Suite changelog

What changed in each suite: which tasks are scored, at which version and rubric version, with which
tiers and weights. Written for someone reading the leaderboard. Crucible's own releases (the tool)
are in [CHANGELOG.md](CHANGELOG.md); how the two version numbers work is in
[docs/versioning.md](docs/versioning.md).

Suites are cut with `crucible suite cut` (a new major) or `crucible suite patch` (rubric fixes, stored
runs rescored). Task changes between cuts go under `## Unreleased`.

## Unreleased

- **accessibility-audit-fixes (formerly CODE-15): rubric 2 → 3, still provisional.** Now an isolated,
  per-test grader (`artifacts`: apps/web/src). 38 hidden tests cover all six audit findings (dialog 9,
  read more 6, tag filter 7, button names 6, form errors 6, status messages 4) plus the model's own
  regression tests as one test; each weighs the same and every one fails on the seeded repo. New tests
  cover keyboard paths (Enter and Space, Cancel and Delete from the keyboard, reopening the dialog),
  ARIA states both ways, the other form fields, the count staying in the button's name and a live
  region that persists. "No axe violations" passed the seeded repo, so it is no longer a free test:
  axe now runs inside each finding's tests, which can't be set up without the fix. "Existing tests
  still pass" (cap 5) and "Contract suite untouched" (cap 4) are caps, not points. Reference solution
  with native `<dialog>`, `<button>` and `<select>`, and three calibration fixtures. Stored runs:
  gemma-4-e4b and gpt-oss-20b (both no-ops) 2.31 → 0.0.

- cache-leak-incident (formerly CODE-13): version 3, rubric 4, still provisional. An isolated, per-test
  grader: 17 equal tests (12 on the cache's behaviour, 4 on the postmortem, 1 for the model's regression
  tests), run in a fresh copy of the seeded repo that takes only the API, web and shared source and
  `incident/POSTMORTEM.md`. The repo gains a seeded test that anonymous reads are still served from the cache, so
  a fix that switches caching off fails "existing tests" and is capped at 5. "Existing tests" (cap 5) and "contract untouched" (cap 4) no longer pay points.
  The postmortem now starts with four fixed lines (`Deploy:`, `First affected request:`, `First report:`,
  `Affected users:`), one test each, so a stray "481" elsewhere no longer passes. Leaks removed: the deploy
  log's commit message and the CHANGELOG 1.8.0 entry no longer name the cache, and the comments in
  `responseCache.ts`, `app.ts` and `server.ts` and the prompt sentence naming the switch are gone (the logs'
  `cache=HIT` evidence is unchanged; 371 / 481 affected users still hold). The stored runs were made with
  the leaky version 2 and don't count for version 3; rescored on copies for reference: gemma-4-e4b 1.0 to 0.0,
  gpt-oss-20b 2.0 to 0.0 (no-op runs), deepseek-v4.1-flash 10.0 to 7.65 (13/17: it passes every cache test and
  the regression test; the four postmortem lines didn't exist in its prompt).

- news-briefing-from-feeds (formerly KNOW-4): version 2, rubric 2, still provisional. The ten sources are
  numbered `[S1]` to `[S10]` and the briefing stays prose, one paragraph per story, each ending with its
  sources (`[S1, S2, S9 opinion]`). Now fully deterministic, 22 equal items: the nine same-day sources each
  cited exactly once with the levy, fire and rally sources combined (9), the stale S10 not cited and Okoro
  and "school board" absent (2), the column cited as opinion (1), nine facts found in the paragraph by its
  citations (levy $41.6 million and 7-2, one firefighter, the three attributed crowd estimates, "expected to
  sign", 3.75% and 0.25), and no invented figures (1). Replaces the two judge criteria and the outlet-name
  and word-count checks. Runs of version 1 no longer count; rerun it.

- fact-check-history (formerly HIST-2), now "Fact-check twelve history claims": version 2, rubric 2,
  still provisional. The paragraph became twelve numbered claims with one fact each (five wrong, seven
  true), and the answer is an `ERRORS:` block of `<number>: <corrected value>` lines, scored as 17 equal
  items: the five errors found, their five corrections, and the seven accurate claims left alone.
  Flagging every claim scores at most 5.9, flagging none 4.1. This fixes a perfect answer
  scoring 5 (quoting "Runnymede" in the King John fix counted as flagging an accurate claim). Runs of
  version 1 no longer count; rerun it.

- novel-character-names (formerly WRIT-2) and names-for-one-character (WRIT-2b): rubric 3. An empty
  answer now scores 0 (it scored 4.0 and 2.0: an empty list had no repeated names and no undescribed
  ones). Only gemma-4-26b-a4b-qat's timed-out runs change.

- **editorial-review-workflow (formerly CODE-11): rubric 3 → 4, still provisional.** The hidden tests
  now run in a fresh copy of the seeded repo that takes only the model's source folders, and every
  test weighs the same (25 hidden tests, up from 13: privacy split into one test per way a draft could
  leak, plus own-articles ordering, who may submit, editing a hidden draft, no self-rejection, and
  authors seeing feedback in their list), plus one for the model's own tests catching the bug.
  Passing the seeded tests and leaving the contract suite untouched are now caps (5 and 4), not
  points, so a run that changes nothing scores 0 instead of 2. Stored runs are rescored from their
  workspaces: gpt-oss-20b and gemma-4-e4b 2.0 → 0, qwen3.5-9b 2.43 → 0.77, qwen3.6-35b-a3b
  4.96 → 4.62, deepseek-v4.1-flash (task version 2) 9.33 → 9.23.

- **cursor-pagination (formerly CODE-12): rubric 2 → 3, still provisional.** Same conversion as
  editorial-review-workflow. The hidden tests now run in a fresh copy of the seeded repo with only the
  model's source folders, and every test weighs the same (tests passed / all x 10). The old grader paid
  for doing nothing: gemma-4-e4b and gpt-oss-20b made no changes and scored 3.0. The 10 old tests grew to
  55: concurrent creates, deletes (of the cursor's own article, and unread ones), favorites and churn
  between pages, comments paged and stable, one validation test per way a cursor can be wrong
  (tampered, forged position, other tag, author, endpoint, offset), backward compatibility of offset
  clients and unpaged comments, and ten web tests for Load more (home tabs, feed, profile tabs,
  comments). "Existing tests" (the seeded API tests) and "Contract suite untouched" are caps (5 and 4),
  not points; "Regression tests" is one test in the pool. The seeded web tests are not part of the cap:
  one of them asserts the numbered pagination the brief tells the model to replace. Stored runs, old
  → new: gemma-4-e4b 3.0 → 0.0 and gpt-oss-20b 3.0 → 0.0 (no-ops), deepseek-v4.1-flash-free 10.0 → 10.0
  (55/55). Task version unchanged, so stored runs were rescored.

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
