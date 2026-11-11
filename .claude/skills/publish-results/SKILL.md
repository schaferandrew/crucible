---
name: publish-results
description: Publish Crucible results to the portfolio's Crucible page, from this machine or from a results file made on another one. Use when asked to publish, upload, add or update Crucible results or scores on the site.
---

# Publish Crucible results

The portfolio (`schaferandrew.github.io`, page `/crucible/`) reads its data from `_data/crucible/`. Crucible
3.0.0 publishes **bundle format 3** there ([docs/bundle-format.md](../../../docs/bundle-format.md)): one file
per run, per score record and per status record, keyed by each run's permanent `run_uuid`, plus one catalog
per suite. Publishing only ever adds files; it never edits or deletes one.

## 0. Which direction? Read this first

There are two directions, and the verb is the same, so pick before running anything:

| The task | The direction | The command |
|---|---|---|
| This machine's runs → the drive | **out** | `crucible publish --to "$USB"` (see the `sync-runs-usb` skill) |
| A drive's bundle → the portfolio | **in** | copy records add-only, then commit (section 2c below) |
| This machine's runs → the portfolio | **out** (portfolio) | `crucible publish --to ../schaferandrew.github.io/_data/crucible` |

If the user says "publish the results" without naming a destination, ask which of the three they
mean rather than guessing: `--to <site>/_data/crucible` and importing a drive bundle are easy to
confuse, and running the wrong one changes the wrong repo. Importing is **not** a `publish --to`
against the site.

**The live portfolio currently reads format 3** (verified by its `AGENTS.md` and
`_data/crucible/catalog/`). If targeting another site or a different checkout, inspect its dashboard
reader before choosing a format; don't infer the format from the Crucible repo alone.

## 0b. Destination branch: `master`, by PR

Publishing changes `schaferandrew.github.io`, whose default branch is **`master`** (not `main`) and
which takes changes as pull requests. Before committing anything:

1. `git -C ../schaferandrew.github.io fetch origin` and check what the default branch is:
   `git -C ../schaferandrew.github.io symbolic-ref refs/remotes/origin/HEAD`.
2. Never commit results onto whatever branch the user happens to have checked out — it is usually a
   feature branch, and may be far behind. Put them on a fresh branch off the current default, in a
   **worktree** (`git worktree add ../schaferandrew.github.io-publish origin/master`), so the user's
   checkout is untouched. AGENTS.md forbids switching branches while a `crucible run` is active.
3. Commit and push the branch, then open the PR against the default branch:
   `gh pr create --base master --head <branch>`. A direct push to `master` may be rejected.
4. Remove the worktree once the PR is merged: `git worktree remove ../schaferandrew.github.io-publish`.

`_site/` is tracked in that repo despite being gitignored, so a build dirties unrelated files with
Jekyll-version churn. Leave those out of the results commit (`git checkout -- _site`).

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

`--check` must exit 0 before anything is committed. Its warnings aren't failures: list them for the
user. A model name it flags gets an alias in `registry/models.yaml` (then publish again, which sends the
registry along as `registry/*.json` and `corrections.json`); never edit a published run. Host names
it can't map to a machine go in `registry/machines.yaml` only when provable.

- Publishing twice adds nothing. A rescore under a new rubric version adds a score record; a run marked with
  `crucible status <run> --invalid REASON` (or `--withdrawn`) adds a status record. Nothing else changes.
- Runs through a harness their mode doesn't use are skipped and listed (they stay in `runs/`), so runs
  removed from the site for that reason don't come back. Never delete them from `runs/` to keep them off.
- Full outputs go to `crucible-data/outputs/`, outside `_data`, so Jekyll never parses them.
- From another machine, run `crucible publish --to <folder>` there and transfer the resulting
  format-3 bundle, or convert its format-2 file with
  `crucible migrate --bundle <file> --to ../schaferandrew.github.io/_data/crucible`.

## 2c. Importing an existing format-3 bundle (for example, from USB)

The bundle may already contain records also present on the site. A matching UUID is not enough to
assume two files are identical: a later publish can enrich an older record with hashes, metrics or
an output reference. Never overwrite a destination file during import.

### First clean the bundle, then judge it

The bundle is often a Finder/`cp` copy, so it carries AppleDouble sidecars (`._*`) and possibly a
zero-byte record from a cut-short copy. `--check` parses both as records and fails, which makes a
perfectly good bundle look broken. Clean first:

```bash
USB=/Volumes/<drive>/crucible-results
find "$USB" -name '._*' -delete
find "$USB" -type f -size 0 -print   # a zero-byte record is a failed write; delete it
```

1. Check the source bundle and the site's `_data/crucible/` with `crucible publish --check`. The exit
   code is the verdict: 0 is valid. Report its warnings (unverifiable pre-hash runs, model names that
   need a registry alias, unmapped host names) but don't treat them as failures. A non-zero exit means stop: show
   the errors and import nothing from that bundle until they're understood. After the cleanup above,
   re-run `--check` — most sidecar failures vanish, and whatever is left is the real verdict.
2. For `catalog/`, `runs/`, `scores/` and `status/`, compare relative paths. Copy a source file only
   when the destination path is absent. If it exists and bytes differ, preserve the site's copy and
   report the conflict; if identical, skip it. Catalogs are included in this rule too.

   **Expect conflicts; they are not damage.** A drive often holds an older copy of a record the site
   has since enriched (extra metrics like `output_tokens_per_s`, a recomputed `provenance.content_hash`).
   Hundreds at once is normal. Keeping the destination is the whole point: importing would downgrade
   it. Report them as counts, and only show diffs if the user asks — do not "fix" them.
3. Copy bundle `outputs/<run_uuid>.txt` files to the site's `crucible-data/outputs/`, also
   add-only. If a transfer bundle has output text at its root instead, recover it only when an
   imported run's `output_ref` names that exact file; don't import unrelated root files.
4. Run `crucible publish --check` on the destination. Repeat the same add-only comparison and confirm
   it finds zero additions; this verifies the import is idempotent. Build Jekyll and check that the
   new runs/scores appear in generated dashboard data. The build needs the repo's Ruby, not the
   system one:

   ```bash
   cd ../schaferandrew.github.io
   export PATH="$HOME/.rbenv/shims:$PATH" && eval "$(rbenv init - bash)"
   bundle exec jekyll build    # system ruby fails: wrong bundler/jekyll version
   ```

   The page joins runs client-side, so grep `_site/crucible/data.json` for a new model name — not
   `_site/crucible/index.html`, which only holds the shell. A per-run entry also lives in
   `_data/crucible/runs/`; the `runs` key inside `data.json` holds only the pre-hash handful.

5. If the bundle's `corrections.json` differs from the site's, copy the newer one over (the source of
   truth is the Crucible repo's `registry/`, which `crucible publish` writes out as `registry/*.json` and
   `corrections.json`; copy the `registry/` folder too). Importing
   records that a correction names without importing the correction leaves those runs mislabeled.

## 3. Check and ship

1. Preview: in the portfolio, `bundle exec jekyll serve` and open `http://localhost:4000/crucible/`; switch
   between Chat and Agentic and confirm the new models or runs show up.
2. Commit and push the portfolio **only when the user asks to publish/deploy** (branch and PR rules in
   section 0b). Keep the page's existing navbar and indexing settings; don't change its promotion or
   visibility as part of a results publish.

## Don'ts

- Don't hand-edit or rewrite published JSON: `publish --check` catches it (content hashes). Fix the
  run, rescore or add a status record, and publish again. For imports, copy validated source records
  add-only; do not normalize or patch their contents.
- Don't publish runs from `runs-archive/`.
- Don't start or load a local model to fill gaps when the user's models are served remotely (LM Studio over
  LM Link).
