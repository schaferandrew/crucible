# A3: Data-driven Crucible dashboard (portfolio)

**Repo:** `schaferandrew.github.io`. **Branch:** `a3-crucible-data-driven` from `master`.
Pushing `master` deploys the site: never push.

**Goal.** Adding tasks, areas or tiers never needs a site code change, the page stops inlining
the whole bundle, and it works on a phone. It must keep working with today's bundle (format 2)
and be ready for format 3 (audit section 3), so read new fields when present and fall back to
today's behavior when not.

## Scope

1. **No hard-coded taxonomy** (`assets/js/crucible.js`, `crucible.html`, `crucible-about.html`):
   tier labels, blurbs and order, the headline and gate tiers (`role`), gate thresholds,
   `COVERAGE_MIN`, `IN_PROGRESS_BELOW`, mode blurbs and area lists come from the bundle
   (`tiers[]`, `modes[]`, `scoring_policy`, per audit section 3) with today's values as
   fallbacks. Local vs cloud comes from `run.inference.local` (fallback: today's provider prefix).
   The intro paragraph and About page's area table render from the bundle via Liquid.
2. **Unknown data** (audit section 3, "Data the site doesn't recognize"): unknown tiers, areas,
   enum values or fields render generically or are ignored, never throw; a bundle with a
   `format_version` above what the page supports is skipped with a one-line notice.
3. **Stop inlining** `{{ site.data.crucible | jsonify }}`: generate one JSON page
   (for example `crucible/data.json` with `layout: null`) and fetch it after first paint, with a
   loading state and an error state.
4. **Mobile** (audit section 4, "Mobile"): below 640 px the leaderboard becomes cards (rank,
   model, headline score bar, one line with the other tiers, time and cost, hardware); the task
   matrix and heatmap get a narrow-screen alternative; the scatter's `viewBox` scales to its
   container. Desktop stays as is.
5. **Portfolio `AGENTS.md`:** add the rules from audit section 7 ("Agent rules and skills"):
   data-driven, unknown data renders generically, respect `format_version`, publishing only adds
   files.

## Not in scope

No change to which scores are shown or how they're computed (judge scores, best configuration,
suite selector, Compare view and variant rows come with format 3, step 8). No edits to
`_data/crucible/`. No About-page versioning text yet.

## Done when

- `bundle exec jekyll build --destination <temp dir>` succeeds; the portfolio tree is unchanged
  apart from your source edits (never commit `_site/`).
- Served from the temp build, the page renders the current data with the same numbers as the
  live page (spot-check the Chat and Agentic leaderboards), at 1400 px and 375 px, with no
  console errors. Screenshots of both widths, before and after, in your report.
- A copy of the bundle with an extra tier, an extra area and an unknown field renders without
  errors (test locally, don't commit it).
- Committed on the branch; not pushed.
