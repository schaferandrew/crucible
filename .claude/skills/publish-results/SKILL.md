---
name: publish-results
description: Publish Crucible results to the portfolio's Crucible page, from this machine or from a results file made on another one. Use when asked to publish, upload, add or update Crucible results or scores on the site.
---

# Publish Crucible results

The portfolio (`schaferandrew.github.io`, page `/crucible/`) reads its data from `_data/crucible/`. Crucible
3.0.0 publishes **bundle format 3** there ([docs/bundle-format.md](../../../docs/bundle-format.md)): one file
per run, per score record and per status record, keyed by each run's permanent `run_uuid`, plus one catalog
per suite. Publishing only ever adds files; it never edits or deletes one.

**Until the page switches to format 3, the live dashboard reads the single format-2 file**
(`_data/crucible/ironwood.json`). Ask the user which they want if it isn't clear; until they say the site has
switched, update the format-2 file and don't write format-3 folders into the live `_data/crucible/`.

## 1. Make sure scores are current

```bash
uv run crucible versions          # the version lock is clean
uv run crucible suite verify      # the current suite still holds
uv run crucible checks            # rerun checks; scores land in score records (add --no-hidden to skip graders)
```

If `crucible` says runs are from before 3.0.0, they need `crucible migrate`. Migrating real runs moves
folders: show the user `crucible migrate --dry-run` first and run it only when they say so.

## 2a. Format 2 (the live page today)

```bash
uv run crucible export --format 2 --out ../schaferandrew.github.io/_data/crucible/ironwood.json
```

The file name is the machine; never overwrite another machine's file with this machine's runs.

## 2b. Format 3 (once the page reads it)

```bash
uv run crucible publish --dry-run                 # what would be added
uv run crucible publish                           # adds to ../schaferandrew.github.io/_data/crucible/
uv run crucible publish --check ../schaferandrew.github.io/_data/crucible   # schema, names, content hashes
```

- Publishing twice adds nothing. A rescore under a new rubric version adds a score record; a run marked with
  `crucible status <run> --invalid REASON` (or `--withdrawn`) adds a status record. Nothing else changes.
- Full outputs go to `crucible-data/outputs/`, outside `_data`, so Jekyll never parses them.
- From another machine: run `crucible publish --to <folder>` there and copy the new files in (they never
  collide: names are UUIDs), or convert its format-2 file with
  `crucible migrate --bundle <file> --to ../schaferandrew.github.io/_data/crucible`. Then `publish --check`.

## 3. Check and ship

1. Preview: in the portfolio, `bundle exec jekyll serve` and open `http://localhost:4000/crucible/`; switch
   between Chat and Agentic and confirm the new models or runs show up.
2. Commit and push the portfolio **only when the user says to**. The Crucible page stays out of the navbar
   and keeps its under-construction notice until the user says otherwise.

## Don'ts

- Don't hand-edit published JSON: `publish --check` catches it (content hashes). Fix the run, rescore or add a
  status record, and publish again.
- Don't publish runs from `runs-archive/`.
- Don't start or load a local model to fill gaps when the user's models are served remotely (LM Studio over
  LM Link).
