---
name: sync-runs-usb
description: Sync this machine's Crucible runs to a removable drive's crucible-results bundle (bundle format 3) with crucible publish --to — preview, publish, verify. Use when asked to copy/sync/backup runs to the USB, get runs off this machine, or update the results on an external/USB drive.
---

# Sync runs to a USB drive

The destination is any removable volume containing a `crucible-results/` bundle (format 3,
accumulated from all machines, everything keyed by `run_uuid` so nothing ever collides and
publish only adds). **No volume name is hardcoded** — find the destination first.

**Put files there only with `crucible publish --to`.** Never copy records onto the drive with
`cp`, Finder or drag-and-drop: on macOS every such copy also writes an AppleDouble sidecar
(`._<name>`) next to the file, and `--check` then parses those sidecars as records and fails
the whole bundle ("not valid JSON"). If you must copy by hand, prefix the command with
`COPYFILE_DISABLE=1`. A bundle can accumulate thousands of sidecars this way — clean them in step 2.

## Step 1: resolve the destination

In order of preference:

1. **Explicit path**: if the user's request names a path (e.g. "sync to `/Volumes/Samsung USB`"),
   use it as-is. Validate `${path}/crucible-results` exists (or the path itself has
   `runs/scores/outputs/catalog` subfolders).
2. **Search `/Volumes`**: candidates are volumes where `[ -d "$V/$c/crucible-results" ]` — that is,
   a `crucible-results/` folder at the volume root containing `runs/` and `scores/` subfolders.
   Mounted macOS resource-fork entries (names starting with `._`) are not candidates.
3. **Ask**: if multiple candidates match, or one match is ambiguous, list them and ask the user
   which to use (see sample below). If none match, ask the user to plug in the drive or give a path
   — do not create the folder on an arbitrary volume unasked.

Once resolved, set `USB="$VOLUME/crucible-results"`.

Sample question when multiple candidates:

> Found multiple drives with a crucible-results bundle — which one?
> - `/Volumes/Samsung USB/crucible-results` (852 runs, last run 2026-11)
> - `/Volumes/WD Backup/crucible-results` (510 runs, last run 2026-10)

Only create a new `crucible-results/` on a drive when the user explicitly asks to start a bundle on
that drive; without user confirmation the directory may be live, so always resolve before publishing.

## Step 2: publish (and verify)

First drop any macOS copy junk the drive has picked up. It is safe: sidecars are resource-fork
metadata, never records, and no real record is zero bytes.

```bash
find "$USB" -name '._*' -delete              # AppleDouble sidecars from Finder/cp
find "$USB" -type f -size 0 -print           # zero-byte files: failed writes, inspect, then delete
```

A zero-byte record is a copy that was cut short. Delete it and let `crucible publish --to` write the
real one; if the record already exists on the other side of a sync, the good copy is the other one.
Don't try to repair it by hand-editing.

Then publish (the usual steps, with the resolved path):

1. Check whether a `crucible run` is active on this machine:

   ```bash
   pgrep -fl "crucible run"
   ```

   If one is, in-flight runs won't be syncable yet. Run the steps anyway with dry-run, tell the user
   the run is still active, and publish again only for what's complete. Never disturb a running run.

2. Preview, then publish:

   ```bash
   uv run crucible publish --to "$USB" --dry-run
   uv run crucible publish --to "$USB"
   ```

3. Verify (always):

   ```bash
   uv run crucible publish --check "$USB"
   ```

   The exit code is the verdict. 0 means the bundle is valid, whatever warnings follow. Report the
   warnings to the user without treating them as failures:
   - "runs have no output and no content hash": records from before every record was hashed (old
     `crucible migrate` conversions, early 3.x publishes). Expected; they can't be verified.
   - "model.base ... isn't a registry model": a model recorded under a bad name. Say which; the fix
     is an alias (with a reason) in `registry/models.yaml`, never an edit to the run.

   A non-zero exit is real trouble: a hash that doesn't match (a record or output edited after
   publishing), a schema error, or a missing output. Stop, show the user the lines, and don't copy
   that bundle onward until it's understood. The one exception is a wall of `._*` "not valid JSON"
   errors with little else: that is copy junk, not a broken bundle — clean it (step 2) and check
   again before deciding anything is wrong.

## Troubleshooting

- A dry run right after publish shows new additions: a run is active and wrote runs since. Go again,
  or report and finish.
- If `crucible` says runs are from before 3.0.0 locally, they need `crucible migrate` first — show
  `crucible migrate --dry-run` to the user and only run it on their say-so.
- `publish --dry-run` may report 0 outputs even when the subsequent publish adds outputs — the
  dry-run delta isn't a perfect predictor; that's fine, publish only adds.
