---
name: publish-results
description: Publish Crucible results to the portfolio's Crucible page, from this machine or from a results file made on another one. Use when asked to publish, upload, add or update Crucible results or scores on the site.
---

# Publish Crucible results

The portfolio's Crucible page (`schaferandrew.github.io`, page `/crucible/`) reads every `*.json` file in its
`_data/crucible/` folder. Each file is a **results bundle** matching `crucible/schemas/results.schema.json`;
the page merges them (runs by `run_id`, newest bundle wins, tests from the newest bundle). One bundle per
machine, named after the machine (`ironwood.json`).

## From this machine

1. Make sure scores are current (both are cheap and safe to rerun):
   ```bash
   uv run crucible versions          # the version lock is clean
   uv run crucible checks            # re-run programmatic checks on existing runs
   ```
   Runs of judge-scored tests with no score yet still publish; they show as "not scored". Score them first
   with `crucible score` (by hand) or the judge flow (`crucible/judge_instructions.md`) if the user wants.
2. Write and validate the bundle:
   ```bash
   uv run crucible publish                  # writes ../schaferandrew.github.io/_data/crucible/<machine>.json
   uv run crucible publish --to <folder>    # anywhere else (or set CRUCIBLE_PUBLISH_DIR)
   ```
   It refuses to write a bundle that doesn't match the schema.

## From another machine

On that machine: `uv run crucible publish --to <some folder>` and bring the file over (AirDrop, a USB stick,
or GitHub's "Add file → Upload files" straight into `_data/crucible/`). Then, here:
```bash
uv run crucible publish --check <file>.json
cp <file>.json ../schaferandrew.github.io/_data/crucible/
```
Never overwrite another machine's bundle with this machine's: the file name is the machine.

## Check and ship

1. Preview: in the portfolio, `bundle exec jekyll serve` and open `http://localhost:4000/crucible/`; switch
   between Chat and Agentic and confirm the new models or runs show up.
2. Commit and push the portfolio **only when the user says to**. The Crucible page stays out of the navbar
   and keeps its under-construction notice until the user says otherwise.

## Don'ts

- Don't hand-edit bundle JSON to change scores; fix the run or rescore it and publish again.
- Don't publish runs from `runs-archive/` (bad-day runs and models with no scored runs live there).
- Don't start a local model on this machine to fill gaps when the user's models are served remotely
  (LM Studio over LM Link); check `crucible run`'s model list first.
