# Suite v2 work plan

The design, findings and decisions are in [../../v-next-audit.md](../../v-next-audit.md); its
section 8 lists the decisions (D1 to D13) every package follows. Each package below has a
brief in this folder. A package is done when everything under its "Done when" is true and its
author has reported back to the orchestrating session.

| Package | Phase | Repo | Model | Needs | Status |
|---|---|---|---|---|---|
| [A1 Crucible 2.4.0 groundwork](A1-crucible-2.4.0.md) | A | crucible | Opus | — | done: `claude/a1-crucible-2-4-0-5b0e27` (313efaf), 353 tests pass, no score changed; awaiting merge |
| [A2 Leak scan](A2-leak-scan.md) | A | crucible (read-only) | Haiku | — | done: [report](reports/A2-leak-scan.md) |
| [A3 Data-driven dashboard](A3-portfolio-data-driven.md) | A | portfolio | Sonnet | — | done: portfolio `claude/a3-crucible-data-driven-862318` (e76cd73); awaiting review and merge |
| [C Crucible 3.0.0](C-crucible-3.0.0.md) | C | crucible | Opus | A1 | started, on top of the A1 branch |
| [D Task conversions](D-task-conversions.md) | D | crucible | Opus first two, then Sonnet per task | C merged | done: exemplars (3.1.0), wave 1 (17 tasks, 3.2.0) and wave 2 (8 tasks, combined as Crucible 3.3.0 on `claude/crucible-3.3.0`, awaiting merge); every Suite v2 conversion is complete except CODE-2b and RSCH-2b, moved to Suite v3 |
| [E Calibration runs](E-calibration.md) | E | crucible | Sonnet | D tasks as they land | outline |
| F Suite v2 cut and site switch | F | both | orchestrator, with Andrew | D, E | — |

## Lean plan (Andrew's decision, 2026-10-29)

Suite v2 ships with what waves 1 and 2 converted, rather than waiting for every conversion:

- Combine the eight wave-1 branches into one release, Crucible 3.2.0.
- Cap CODE-12's core requirement: `cap_if_failed: 6` on cursor correctness, so cursors that skip or
  repeat under concurrent writes can't score near 10.
- Commit the wave-1 validation cases to `.claude/skills/add-task/examples/`.
- **`navbar-hamburger-menu` (CODE-2b) and `weather-vs-normal` (RSCH-2b) move to Suite v3.** Their
  conversions need new infrastructure (the first Playwright grader; a frozen `web` fixture host), which
  doesn't fit Suite v2. They are not converted in D.

## Rules for every session

- Read `AGENTS.md` (and `CLAUDE.md`) of the repo you work in, the audit's section 8, and your brief.
- Work on your own branch in your own worktree, cut from `claude/suite-v2-audit` (crucible) or
  `master` (portfolio). Touch only the files your brief lists.
- **Never push, open a PR, merge, tag or release.** Commit on your branch and report; Andrew
  approves every push and merge.
- Never load or unload models; no model runs unless your brief says so, and then one at a time.
- Never switch branches in a checkout with an active `crucible run` (`pgrep -fl "crucible run"`).
- If the brief and the code disagree, or a decision is needed, stop and ask the orchestrating
  session instead of guessing.
- Your final report says: branch and commits, what changed, test results (with output for any
  failure), what you didn't do and why.
