# Bundle format

What `crucible publish` writes for the dashboard. Format 3 splits what a suite **is** (a catalog)
from what **happened** (run, score and status records), one file per thing, so publishing only ever
adds files. Schemas: `crucible/schemas/{catalog,run,score,status,corrections}.schema.json`.

## Layout

```
_data/crucible/
  catalog/v1.json  v2.json  v2.1.json            one per suite
  runs/2026-10/<run_uuid>.json                   one per run, never edited
  scores/2026-10/<run_uuid>.r<n>.<method>.json   one per run × rubric version × method
  status/<run_uuid>.json                         status records, only appended to
  corrections.json                               reviewed fixes for badly recorded model fields
crucible-data/outputs/<run_uuid>.txt             full model output, outside _data
```

Month folders come from the run's `started_at` and keep directories browsable on GitHub. Outputs
live outside `_data` so Jekyll never parses them; the page fetches one when asked.

## Publishing

```
crucible publish [--to <site>/_data/crucible] [--outputs DIR] [--runs runs] [--dry-run]
```

1. Reads the run UUIDs and score records already in the folder (the file names).
2. For each run in `runs/` (never `runs-archive/`): writes its record and output unless its UUID is
   there. Local-only fields are dropped; `output_ref` and `provenance.content_hash` are set.
3. Writes each score record not yet there (UUID + rubric version + method), and appends new status
   records.
4. Writes a catalog for every suite that has none, and rewrites the latest suite's catalog when it
   changed (task names, summaries, provisional tasks). A past suite's catalog never changes.
5. Writes `corrections.json` from the repo's `corrections.yaml` when it changed (below).
6. Validates every file before writing it, and prints what it added.

Publishing twice writes nothing. Nothing published is deleted or rewritten: to take a run out,
add a status record (`crucible status <run> --withdrawn REASON`) and publish.

**Content hash.** `provenance.content_hash` is SHA-256 over the canonical JSON (sorted keys,
compact) of the run record without `provenance`, a zero byte, and the output text.
`crucible publish --check DIR [--outputs DIR]` validates every file against its schema, checks the
file names, and recomputes every content hash, so an edited copy is detectable. Run it before
committing the portfolio. A run published before every record was hashed (a format-2 run converted
by an older `crucible migrate --bundle`, or an early 3.x publish) and with no output has an empty
hash; runs are never edited, so the check lists those as unverifiable warnings instead of failing.
A hash that doesn't match, or an output with no hash, is always an error. The exit code is the
verdict: 0 means valid, whatever the warnings. It also prints, as warnings that never fail the check, every published
`model.base` that doesn't look like `<maker>/<model>` (a packager prefix, a format or quant tag, an
OpenRouter `~` or `:free`, no maker) and that `corrections.json` doesn't fix.

## Corrections

Runs are never edited, so a model field recorded badly stays that way in its run record.
`corrections.yaml` (the Crucible repo's root) is the reviewed list of how to read them, and
`crucible publish` writes it whole as `corrections.json`:

```json
{"record": "corrections", "format_version": 3,
 "models": [{"base": "granite-4.2-3b-mlx@4bit", "to_base": "ibm-granite/granite-4.2-3b",
             "maker": "ibm-granite", "publisher": null, "reason": "..."}],
 "publishers": [{"from": "Qwen", "to": "qwen"}]}
```

The page applies it once, as it reads the runs: a run whose `model.base` equals an entry's `base` is
read as `to_base` (in `variant_key` too); the entry's `maker` and `publisher` fill only fields the
run left empty; a `publishers` entry maps a recorded spelling. The page also fills an empty `format`
from a quant name only one format uses (`Q4_K_M`, `IQ3_XS`: gguf; `4bit`: mlx). It keeps what was
recorded and shows it in the run detail. Add an entry only when the answer is known; never guess a
maker, and never merge two models nothing recorded says are the same.

## The catalog

```json
{
  "format_version": 3, "format_revision": 1,
  "suite": {"id": "v1", "version": "1.0", "cut_at": "2026-10-28", "status": "current", "changelog_url": "…"},
  "crucible_version": "3.0.0",
  "scoring_policy": {"coverage_min": 0.75, "in_progress_below": 0.75, "repeat_aggregate": "mean"},
  "modes": [{"id": "chat", "label": "Chat", "blurb": "one API call, no tools", "order": 1}],
  "areas": [{"id": "writing", "label": "Writing", "mode": "chat", "order": 1}],
  "categories": [{"id": "writing", "label": "Writing", "weight": 0.10}],
  "tiers": [{"id": "spark", "label": "Spark", "blurb": "…", "order": 1, "role": "gate", "gate": {"mean": 8, "min": 5}}],
  "harnesses": [{"id": "direct", "label": "direct", "modes": ["chat"]}],
  "tasks": [{"id": "react-lead-form", "name": "React lead form", "aliases": ["CODE-16"], "mode": "agentic",
             "area": "coding", "category": "coding_debug", "tier": "temper", "status": "provisional",
             "version": 1, "rubric_version": 1, "weight": null,
             "scoring": {"method": "hidden_tests", "unit": "tests", "total": 43, "scale": 10},
             "criteria": [{"id": "Renders", "label": "Renders", "max_score": 2}],
             "summary": "…", "prompt": "…", "rules": [], "added_in": null}]
}
```

- Every known task is listed. A task the suite pins is `active`, with its pinned version, rubric
  version, tier, category and `weight` (its category's weight split across the category's pinned
  tasks). Any other task is `provisional` or `retired`, with no weight.
- `role` (`gate`, `headline`, `stretch`) lets the page find the gate and the headline tier without
  knowing tier names. Everything is referenced by ID; labels are only read from the catalog.
- A run counts in a suite when the suite pins its task at the run's `task.version` and the run
  went through one of its mode's harnesses; its score is the score record at the pinned
  `rubric_version`.

## Compatibility

- `format_version` changes only for breaking changes; `format_revision` counts additive ones (see
  [versioning.md](versioning.md#bundle-format)). A page that meets a higher `format_version` skips
  the file and shows one line, never an error.
- Revisions: 1 (Crucible 3.6.0) adds the run record's optional `model.origin` (who trained the
  model, read from the source; see [data-model.md](data-model.md#model-origin)). Runs published
  before it don't have the field and are never rewritten to add it, so a reader treats it as
  optional and falls back to its own inference when it's missing.
- Revision 2 (Crucible 3.8.0) adds `corrections.json` and the run record's optional
  `model.reasoning.resolved_source`. A reader without corrections shows runs as recorded.
- Unknown areas, categories or tiers render generically, after the known ones; an unknown task ID
  in a run is kept and listed under "Other runs"; unknown fields are ignored; an unknown enum value
  shows as a raw tag.

## Format 2 (until the dashboard switches)

`crucible export --format 2 --out FILE` writes the single-file bundle the live page reads today
(`crucible/schemas/results.schema.json`). It's frozen: tasks are listed by their pre-3.0.0 IDs (a
task's first alias, plus a `slug` field), runs by their legacy `run_id` (or run path for runs made
since 3.0.0), and scores count only on the current task and rubric versions. It's removed once the
page reads format 3.
