# Suite v2 work plan

The design, findings and decisions are in [../../v-next-audit.md](../../v-next-audit.md); its
section 8 lists the decisions (D1 to D13) every package follows. Each package below has a
brief in this folder. A package is done when everything under its "Done when" is true and its
author has reported back to the orchestrating session.

| Package | Phase | Repo | Model | Needs | Status |
|---|---|---|---|---|---|
| [A1 Crucible 2.4.0 groundwork](A1-crucible-2.4.0.md) | A | crucible | Opus | — | started |
| [A2 Leak scan](A2-leak-scan.md) | A | crucible (read-only) | Haiku | — | started |
| [A3 Data-driven dashboard](A3-portfolio-data-driven.md) | A | portfolio | Sonnet | — | started |
| [C Crucible 3.0.0](C-crucible-3.0.0.md) | C | crucible | Opus | A1 merged | outline |
| [D Task conversions](D-task-conversions.md) | D | crucible | Opus first two, then Sonnet per task | C merged | outline |
| [E Calibration runs](E-calibration.md) | E | crucible | Sonnet | D tasks as they land | outline |
| F Suite v2 cut and site switch | F | both | orchestrator, with Andrew | D, E | — |

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
