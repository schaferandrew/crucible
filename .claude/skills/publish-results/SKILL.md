---
name: publish-results
description: Publish Crucible results to crucible-dashboard from this machine or a removable drive's format-3 bundle. Use when asked to publish, upload, or update Crucible results on the site.
---

# Publish Crucible results

`schaferandrew/crucible-dashboard` owns the format-3 results bundle in `bundle/`, including
`bundle/outputs/`. The dashboard generates its site data from that bundle on every deploy.

- **Machine → USB.** Use the [sync-runs-usb skill](../sync-runs-usb/SKILL.md).
- **Machine → dashboard.** Publish local runs with `crucible publish --to "$BUNDLE"`.
- **USB → dashboard.** Validate and import the existing bundle as described below.

## Set up a results worktree

Fetch `origin/main` in the dashboard checkout. Create a feature branch and a worktree so the
current checkout stays available. Run the commands using absolute paths when switching repositories.

```bash
DASHBOARD=/absolute/path/to/crucible-dashboard
PREVIEW=/absolute/path/to/crucible-dashboard-publish
git -C "$DASHBOARD" fetch origin main
git -C "$DASHBOARD" worktree add -b publish-results "$PREVIEW" origin/main
BUNDLE="$PREVIEW/bundle"
```

## Publish this machine's runs

From the Crucible checkout, verify versions and suites and refresh scores with
`uv run crucible versions`, `uv run crucible suite verify`, and `uv run crucible checks`.

```bash
uv run crucible publish --to "$BUNDLE" --dry-run
uv run crucible publish --to "$BUNDLE"
uv run crucible publish --check "$BUNDLE"
```

For pre-3.0 runs, show `uv run crucible migrate --dry-run` before migrating local data.

## Import a USB bundle

Set `USB` to the resolved `crucible-results/` directory. Inspect AppleDouble sidecars (`._*`)
and zero-byte files if validation fails. Clean copy artifacts and revalidate before importing.

1. From Crucible, run `uv run crucible publish --check "$USB"` and
   `uv run crucible publish --check "$BUNDLE"`. Stop on a nonzero exit and report validation errors.
   Report any warnings. A model-name correction belongs in Crucible's `corrections.yaml`.
2. Compare paths in `catalog/`, `runs/`, `scores/`, `status/` and `outputs/`. Skip identical files,
   copy missing files, and preserve existing dashboard files when bytes differ. Report conflict
   counts. For legacy transfers with outputs at the root, copy an output into `outputs/` only if
   an imported run references that exact file. If a correction needs updating, use the current
   Crucible registry as the source.
3. Validate the destination again, then repeat the comparison to verify that no additions remain.

## Preview and deploy

In the dashboard worktree, run `npm ci`, `npm run data:gen`, `npm run check`, `npm test`, and
`npm run build`. Verify the imported runs in `static/data/runs/` or use `npm run dev` to view them at
`http://localhost:5173/crucible-dashboard/`.

When asked to publish, commit the bundle changes on the feature branch and open a dashboard PR
against `main`. The Deploy workflow starts after merge. Verify the results at
`https://www.schaferandrew.com/crucible-dashboard/` once it succeeds.
