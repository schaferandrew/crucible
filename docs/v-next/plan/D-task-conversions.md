# D: Task conversions (outline; refined after C merges)

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
   - leak fixes from A2's report (B5 first)
   - retirements: CODE-1, CODE-2, CODE-4b, CODE-6, RSCH-1, RSCH-2, WRIT-2
4. A Sonnet reviewer checks each branch: reference answer 10, empty answer 0, real wrong
   answers land where expected, lock updated, SUITE_CHANGELOG entry, only the task's files touched.

Everything lands `provisional`.
