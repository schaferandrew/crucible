# A2: Leak scan (read-only)

**Goal.** Find every place a model can read the answer to its task, before Suite v2. Known
example (finding B5): `repos/login-service/server.js:29` says
`// C5: intermittent blank dashboard - triggered when session is expired`.

**Read-only.** Edit nothing; the fixes land with the task conversions (package D).

## Where to look

Everything copied into an agent's workspace or sent in a prompt:
- `repos/*/` (excluding `node_modules`, lockfiles): comments, READMEs, commit-style notes, test
  names, fixture data.
- `fixtures/` (including `mock-calendar/*.json`, `mock-data/*.json`, the mock MCP servers'
  output shapes).
- The `prompt:` text of every file in `prompts/`.

## What counts as a leak

- Task IDs, old or new (`C5`, `COD11`, `CODE-5`, `TASK-4`…) or words like `BUG`, `FIXME`,
  `seeded`, `planted`, `trap`, `expected`, `answer`, `grader`, `hidden test`.
- Comments or docs that describe the bug, the fix or the ground truth.
- Test files in a seeded repo that already assert the fixed behavior (they'd hand the model the
  spec of the hidden tests).
- Fixture data that states a conclusion the model is supposed to compute (for example a
  pre-computed free slot or count).

## Report

Your final message: a table with file:line, what it reveals, which task it affects, and
severity (gives the answer / strong hint / cosmetic). Then a one-line verdict per seeded repo
(clean / needs fixes). No edits, no commits.
