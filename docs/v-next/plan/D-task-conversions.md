# D: Task conversions

Order (decision D10: all scoring fixes land here, on the 3.0.0 task track):

1. Engine rule first: an empty answer fails every check (B2), as a rubric bump for every task.
2. **Exemplars, by the orchestrating session (Opus):** HIST-2 (answer block, numbered claims,
   13 items) and CODE-11 (isolated per-test grader, `seeded: [0, 0]`). Then write the
   `add-task` and `convert-grader` skills from them.
3. **Fan-out, one Sonnet session per task, each in its own worktree, touching only its task's
   files**, following the skills:
   - rescore per item: MATH-2, GEOG-1, GEOG-2, HIST-3
   - answer-block rewrites: WRIT-1a, WRIT-1b, WRIT-1c (B4), WRIT-2b, MATH-4, HIST-1, KNOW-4
   - graders: CODE-12, CODE-13, CODE-14, CODE-15 (B3)
   - agentic answers: TASK-1, TASK-2, TASK-4, TASK-5, TASK-6
   - leak fixes from [A2's report](reports/A2-leak-scan.md): each conversion session fixes its own task's leaks; the CODE-13 and CODE-14 repos need the most work
   - retirements: CODE-1, CODE-2, CODE-4b, CODE-6, RSCH-1, RSCH-2, WRIT-2
4. A Sonnet reviewer checks each branch: reference answer 10, empty answer 0, real wrong
   answers land where expected, lock updated, SUITE_CHANGELOG entry, only the task's files touched.

Everything lands `provisional`.

## Status

**Exemplars (done, Crucible 3.1.0):** HIST-2 (`fact-check-history`) and CODE-11
(`editorial-review-workflow`), with the `add-task` and `convert-grader` skills.

**Wave 1 (done, combined as Crucible 3.2.0 on `claude/crucible-3-2-0-91cb06`):** each branch was
verified by its session; validation cases are in `.claude/skills/add-task/examples/`.

| Branch | Tasks | Status |
|---|---|---|
| `claude/w1-code12` | CODE-12 `cursor-pagination` (grader; cursor correctness capped at 6) | done |
| `claude/w1-code15` | CODE-15 `accessibility-audit-fixes` (grader) | done |
| `claude/w1-code13` | CODE-13 `cache-leak-incident` (grader, leak fixes) | done |
| `claude/w1-know4` | KNOW-4 `news-briefing-from-feeds` (`cited_paragraphs` check) | done |
| `claude/w1-writ1c` | WRIT-1c `proofread-economics-essay` (B4) | done |
| `claude/w1-writing` | WRIT-1a `proofread-customer-email`, WRIT-1b `proofread-literary-paragraph`, WRIT-2b `names-for-one-character` | done |
| `claude/w1-chat-numeric` | MATH-2 `household-money-math`, GEOG-1 `capitals-not-largest-city`, GEOG-2 `landlocked-countries`, HIST-1 `order-historical-events`, HIST-3 `letter-from-1863`, MATH-4 `seating-logic-puzzle` | done |
| `claude/w1-calendar` | TASK-4 `calendar-free-at-330`, TASK-5 `calendar-hour-with-jamie`, TASK-6 `calendar-team-of-16` | done |

Tasks active in Suite v1 (WRIT-1a, 1b, 1c, 2b, MATH-4) stay active; their version bumps stop old runs
counting. Everything else is provisional until the Suite v2 cut.

**Wave 2 (done, combined as Crucible 3.3.0 on `claude/crucible-3.3.0`):** each branch was verified by
its session and again after combining (every grader oracle and add-task example passes).

| Branch | Tasks | Status |
|---|---|---|
| `claude/w2-code3-bb4a2f` | CODE-3 `nextjs-server-data-boundary` (grader, leaks removed) | done |
| `claude/w2-code14-0b4983` | CODE-14 `invite-signup-loop` (grader, leaks removed; capped at 5 without the Legal terms) | done |
| `claude/w2-code1b` | CODE-1b `interest-calculator-cli` (first Python grader: `runner: pytest`, `own_tests`, `repo: null`) | done |
| `claude/w2-code45` | CODE-4 `login-recovery` (`audit_log`, `workspace_unchanged` checks), CODE-5 `blank-dashboard-debug` (grader); CODE-4b `login-recovery-repeat` version 2 for the shared repo | done |
| `claude/w2-tasks123` | TASK-1 `two-calendar-slots-json`, TASK-2 `morning-brief-spanish`, TASK-3 `morning-brief-priorities` (whole-document `items` kinds) | done |

Tasks active in Suite v1 (CODE-1b, CODE-3, CODE-4, CODE-4b, TASK-1, TASK-2, TASK-3) stay active; their version bumps stop old runs
counting.

**Every Suite v2 conversion is complete**, except the two moved to Suite v3.

**Moved to Suite v3 (lean plan):** CODE-2b `navbar-hamburger-menu` (needs the first Playwright
grader) and RSCH-2b `weather-vs-normal` (needs a frozen `web` fixture host). Not converted here.

**Not converted:** the retirements (CODE-1, CODE-2, CODE-4b, CODE-6, RSCH-1, RSCH-2, WRIT-2), which happen
at the cut.
