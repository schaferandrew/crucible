---
name: calibrate-task
description: Calibrate a Crucible task by running it on the calibration models (one small local, one mid-size, one frontier), one at a time, then report the spread and whether it separates models. Use when asked to calibrate, check the difficulty of, or try out a new or changed task before promoting it.
---

# Calibrate a task

A provisional task is promoted only when it has runs from at least one small local, one mid-size and one
frontier model, its scores aren't all equal, and (for graders) its oracle passes
([docs/versioning.md](../../../docs/versioning.md#suites)). This skill gets those runs and reports.

## Before running anything

1. Resolve the task and check it: `uv run crucible task show <task>` (an old ID works too). It should be
   `provisional`; calibrating an active task is fine but say so.
2. `uv run crucible versions` must be clean. For a grader task, `uv run crucible grader <task>` must pass
   (reference solution 10, seeded repo 0, calibration fixtures in range).
3. Agree the three models with the user. Ask if they haven't named them; don't guess. Typical: a small local
   model (~9B), a mid-size one (~27B), a frontier cloud model via OpenRouter.

## Running

- **Never load or unload models** in LM Studio or Ollama. Models are often served from another machine over
  LM Link; loading one here can start it on this laptop. If a local model isn't loaded, ask the user to load it.
- **One run at a time**: never two `crucible run`s in parallel, local or cloud (billed cost stays attributable).
- Check nothing else is running first: `pgrep -fl "crucible run"`.
- Run each model in turn, in the background if it's long:
  ```bash
  uv run crucible run <task> --model <provider/model>      # chat tasks run with direct
  uv run crucible run <task> --model <provider/model> --agent pi   # agentic: pi or opencode
  ```
  Run each at least twice when time allows: one run can't tell a small difference from noise.
- A run that ends `harness_error`, or is marked invalid, is a setup problem: fix the setup and rerun; don't
  count it.

## Reporting

For each model: n runs, mean score, min to max, outcome of each run, and the time (and cost, for cloud).
Read scores from each run's score record (`runs/<model>/<task>/<ts>/scores/r<n>.*.json`, field `score`).
Then say plainly:

- **Does it separate models?** Scores all equal (all 10s or all 0s) means it doesn't.
- **Is it in its tier's band?** Spark: the small model scores 8+. Temper: the mid model 6+ and the frontier
  model at least 2 above the small one. Forge: the mid model 5 or less and the frontier model 7+.
- **Anything suspicious:** a check that fails a correct-looking answer, a grader error, an empty answer that
  scored above 0. Quote the run path.

Don't promote the task: promotion is `crucible suite cut`, which the user asks for separately (the
`cut-suite` skill). Don't change the task's checks to fit the results without saying so; that's a
`rubric_version` bump with its own SUITE_CHANGELOG entry.
