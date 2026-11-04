---
name: publish-results
description: Publish Crucible results to the portfolio's Crucible page, from this machine or from a results file made on another one. Use when asked to publish, upload, add or update Crucible results or scores on the site.
---

# Publish Crucible results

The portfolio (`schaferandrew.github.io`, page `/crucible/`) reads its data from `_data/crucible/`. Crucible
3.0.0 publishes **bundle format 3** there ([docs/bundle-format.md](../../../docs/bundle-format.md)): one file
per run, per score record and per status record, keyed by each run's permanent `run_uuid`, plus one catalog
per suite. Publishing only ever adds files; it never edits or deletes one.

**The live portfolio currently reads format 3** (verified by its `AGENTS.md` and
`_data/crucible/catalog/`). If targeting another site or a different checkout, inspect its dashboard
reader before choosing a format; don't infer the format from the Crucible repo alone.

## 1. Make sure scores are current (for runs in this checkout)

For an existing format-3 bundle from USB or another machine, don't rescore local runs just to import
it. Validate the source and destination bundles with `crucible publish --check` instead; keep imported
records and scores unchanged.

```bash
uv run crucible versions          # the version lock is clean
uv run crucible suite verify      # the current suite still holds
uv run crucible checks            # rerun checks; scores land in score records (add --no-hidden to skip graders)
```

If `crucible` says runs are from before 3.0.0, they need `crucible migrate`. Migrating real runs moves
folders: show the user `crucible migrate --dry-run` first and run it only when they say so.

## 2a. Format 2 (only for a target that still reads format 2)

```bash
uv run crucible export --format 2 --out ../schaferandrew.github.io/_data/crucible/ironwood.json
```

The file name is the machine; never overwrite another machine's file with this machine's runs.

## 2b. Format 3 (the live portfolio)

```bash
uv run crucible publish --dry-run                 # what would be added
uv run crucible publish                           # adds to ../schaferandrew.github.io/_data/crucible/
uv run crucible publish --check ../schaferandrew.github.io/_data/crucible   # schema, names, content hashes
```

- Publishing twice adds nothing. A rescore under a new rubric version adds a score record; a run marked with
  `crucible status <run> --invalid REASON` (or `--withdrawn`) adds a status record. Nothing else changes.
- Runs through a harness their mode doesn't use are skipped and listed (they stay in `runs/`), so runs
  removed from the site for that reason don't come back. Never delete them from `runs/` to keep them off.
- Full outputs go to `crucible-data/outputs/`, outside `_data`, so Jekyll never parses them.
- From another machine, run `crucible publish --to <folder>` there and transfer the resulting
  format-3 bundle, or convert its format-2 file with
  `crucible migrate --bundle <file> --to ../schaferandrew.github.io/_data/crucible`.

## Importing an existing format-3 bundle (for example, from USB)

The bundle may already contain records also present on the site. A matching UUID is not enough to
assume two files are identical: a later publish can enrich an older record with hashes, metrics or
an output reference. Never overwrite a destination file during import.

1. Check the source bundle and the site's `_data/crucible/` with `crucible publish --check`.
   Ignore only recognized legacy pre-hash signatures and report any schema errors or hash mismatches
   on records that already have hashes. Ignore `._*` AppleDouble sidecars; never import them.
2. For `catalog/`, `runs/`, `scores/` and `status/`, compare relative paths. Copy a source file only
   when the destination path is absent. If it exists and bytes differ, preserve the site's copy and
   report the conflict; if identical, skip it. Catalogs are included in this rule too.
3. Copy bundle `outputs/<run_uuid>.txt` files to the site's `crucible-data/outputs/`, also
   add-only. If a transfer bundle has output text at its root instead, recover it only when an
   imported run's `output_ref` names that exact file; don't import unrelated root files.
4. Run `crucible publish --check` on the destination. Repeat the same add-only comparison and confirm
   it finds zero additions; this verifies the import is idempotent. Build Jekyll and check that the
   new runs/scores appear in generated dashboard data.

## 3. Check and ship

1. Preview: in the portfolio, `bundle exec jekyll serve` and open `http://localhost:4000/crucible/`; switch
   between Chat and Agentic and confirm the new models or runs show up.
2. Commit and push the portfolio **only when the user asks to publish/deploy**. Keep the page's existing
   navbar and indexing settings; don't change its promotion or visibility as part of a results publish.

## Don'ts

- Don't hand-edit or rewrite published JSON: `publish --check` catches it (content hashes). Fix the
  run, rescore or add a status record, and publish again. For imports, copy validated source records
  add-only; do not normalize or patch their contents.
- Don't publish runs from `runs-archive/`.
- Don't start or load a local model to fill gaps when the user's models are served remotely (LM Studio over
  LM Link).
