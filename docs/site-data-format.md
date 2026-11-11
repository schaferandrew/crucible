# Site data format (`crucible site-data`, format 1)

`crucible site-data --bundle DIR --outputs DIR --out DIR [--display FILE --fallbacks FILE] [--built-at ISO]` turns a
published bundle (format 3 and 4 run records) into the static JSON the dashboard loads. It is layer 2 of the
dashboard design: it resolves **identity** (through the registry) and **run state** (the page's old rules) and never
scores; tier scores, gates, ranking, Combined pairing and filters are computed by the dashboard's TypeScript core
from these files. JSON Schemas for every file are in `crucible/schemas/site-data/` and are checked in the tests.

Principles the files follow:

- **Filters drill down, they never gate the first view.** Nothing is split or pre-selected by hardware, quant,
  harness or any other filter dimension. `<suite>/index.json` holds every setup and every cell of the suite; the page
  filters client-side. A leaderboard row is a model at a reasoning level showing its best setup across everything;
  that is layer 3's job.
- **Size scales with setups x tasks, not runs.** Detail (a task's runs, a model's runs, one run) is fetched on demand.
- **Hardware class is the only public machine identity.** A local deployment is `local~<hardware key>`. A machine's
  name (the registry label, e.g. Duskfall) is display-only credit: it is on runs, deployment credit lists and setup
  labels, never inside an ID and never a filter or grouping key. Raw host names (`Mac-168`, `ip-192-168-...`) are
  never emitted, and the build refuses to finish if any IPv4/IPv6 address or `ip-a-b-c-d` host name is in its output
  (`crucible/sitedata/guard.py`), including the copied model outputs.
- **Deterministic.** Minified JSON, keys sorted, lists in a documented stable order; two builds of the same input are
  byte-identical. `meta.built_at` is `--built-at`, else `SOURCE_DATE_EPOCH`, else the latest timestamp in the bundle
  (never the wall clock). Re-building into a folder first removes what the previous build wrote there.
- Hidden suites (`hidden_suites` in the display file) are omitted entirely. If that would hide every suite, none is hidden.
- Floats are rounded to 9 significant digits. `null` means "not known"; a missing optional block is omitted.

## Files

```
meta.json
<suite>/index.json
<suite>/tasks/<task>.json
<suite>/models/<model id with "/" replaced by "__">.json
runs/<run_uuid>.json
recent/<YYYY-MM>.json            (also recent/unknown.json for runs with no start time)
outputs/<run_uuid>.txt           (copied unchanged)
```

## IDs

IDs are opaque strings, composed by `crucible/registry.py` from resolved parts: URL-safe, deterministic, never parsed
by the page. A missing part is the literal `unrecorded`; nothing is merged by inference.

| Entity | Format | Example |
|---|---|---|
| model | `<maker>/<name>`, lowercase; `unknown/<slug>` when the registry doesn't know the raw base | `qwen/qwen3.5-9b` |
| maker | registry slug, or `unknown` | `qwen` |
| artifact | `<model>~<packager>~<format>~<quant>`; `<model>~api` for cloud | `qwen/qwen3.5-9b~lmstudio-community~gguf~q4_k_m` |
| variant | `<artifact>~r-<reasoning level>~<harness>` | `...~q4_k_m~r-on~direct` |
| deployment | `local~<hardware key>` or `cloud~<provider>` | `local~m5-pro-48gb`, `cloud~openrouter` |
| setup | `<variant>@<deployment>` | `...~r-on~direct@local~m5-pro-48gb` |
| run | `run_uuid` | |
| suite | catalog `suite.id` | `v4` |
| task | catalog `task.id` (aliases resolve to it) | `react-lead-form` |

Reasoning level = the requested level if explicit, else the resolved one, else `default`.

## Run state

Every run has one state per suite (rules reproduced from the page's `buildSuite`, in this order):

| state | meaning |
|---|---|
| `withdrawn` | the last status record says withdrawn |
| `unknown_task` | the suite has no such task (by id or alias) |
| `retired` | the task is retired |
| `invalid` | the last status record says invalid (or, with none, the harness marked `outcome.invalid`) |
| `older` | the run's task version differs from the suite's |
| `harness` | the harness isn't allowed for the task's mode |
| `counted` | the task is `active` |
| `provisional` | any other task status |

Validity: the last status record (sorted by `at`) wins: `withdrawn`, then `invalid`, then `valid: true`; with none,
`outcome.invalid` decides. A run's **score** in a suite is its score record at the task's pinned `rubric_version` and
scoring method, else any record at that rubric version, else (runs that don't count only) the newest rubric version.
A counted run without a numeric score is **unscored**. **Outcome**: `timed_out` (`outcome.timed_out` or status
`timeout`), `finished` (status `completed`), else `error`. **tps** is `metrics.output_tokens_per_s` when positive.
**cost** is the registry's `energy_cost`: billed `metrics.cost_usd` for cloud, time x watts x price per kWh for local
(the hardware key may be filled in from the registry, so some old runs now have a cost the page didn't show).

Records with `format_version` above 4 are skipped. A duplicate `run_uuid` keeps the first read; a duplicate score
(`run_uuid`, `rubric_version`, `method`) keeps the last.

## `meta.json`

`{site_data_format: 1, built_at, crucible_version, bundle_hash, current_suite, suites: [{id, version, label, status, cut_at}]}`.
`suites` is newest first. `bundle_hash` is a sha256 over every file in the bundle folder (paths and bytes).
`current_suite` is the suite whose `status` is `current`, else the first.

## `<suite>/index.json`

The first-load file. Keys: `suite`, `counts`, `catalog`, `entities`, `cells`, `setup_stats`, `other`.

### `counts`
`{runs, counted, counted_scored, unscored, provisional, older, harness, invalid, retired, unknown_task, withdrawn}`:
runs per state in this suite (`unscored` = counted runs without a numeric score; `counted_scored` = the rest).

### `catalog`
Resolved for display; the catalog's own fields win, display text it lacks comes from the fallbacks file, so the page
needs no fallback layer. No prompts, rules, criteria or summaries.

- `suite`: `{id, name ("Suite v4"), version, cut_at, status, changelog_url, format_revision}`
- `modes[]`: `{id, label, blurb, order, areas: [area id], harnesses: [harness id]}` ordered by (order, position)
- `areas[]`: `{id, label, mode, order, blurb, examples}`
- `categories[]`: `{id, label, weight}`
- `tiers[]`: `{id, label, blurb, detail, role (gate|headline|stretch|null), gate ({mean, min}|null), order}` in display order;
  a tier only tasks mention is appended with no role
- `harnesses[]`: `{id, label, modes}`
- `scoring_policy`: `{coverage_min, in_progress_below, ...}`
- `scoring_methods`: `{<method>: {label, blurb, criteria_label}}` for every method a task uses (including `judge`)
- `labels`: `{overall: "Overall", combined: {label, blurb}}`
- `tasks[]`: `{id, name, aliases, mode, area, category, tier, status, version, rubric_version, weight, added_in, scoring: {method, unit, total, scale}}`
  in catalog order. The full task is in `tasks/<task>.json`.

### `entities`
All keyed by their stable IDs, restricted to what the suite uses (setups with at least one cell; the models of runs
in `other`).

- `makers[id]`: `{id, label, url}`
- `models[id]`: `{id, label, maker, family, params, active_params, known}`; `known: false` for `unknown/...`
- `artifacts[id]`: `{id, model, packager, format, quant, api}`
- `variants[id]`: `{id, artifact, reasoning, harness}`
- `deployments[id]`: `{id, where, provider, hw, hw_label, label, machines: [{label, runs}], watts}`. `hw_label` is the
  registry's hardware label (e.g. "Apple M5 Pro, 48 GB"); `label` is that plus the contributing machines as credit,
  e.g. "Apple M5 Pro, 48 GB (Duskfall, Eclipse)"; `machines` lists those machine labels with their run counts in this
  suite (display only).
- `setups[id]`: `{id, variant, artifact, deployment, model, maker, packager, format, quant, reasoning, harness, where, hw,
  provider, modes, runs, labels, unrecorded}`.
  The flat fields are the filter facets. A recorded value is a string; a value that applies but wasn't recorded is the
  literal `"unrecorded"` (and is listed in `unrecorded`: any of `model, harness, where, provider, packager, format,
  quant, hw`); `null` means not applicable (cloud: `quant`, `hw`; local: `provider`). `modes` are the modes of the tasks
  it ran; `runs` counts its runs in cells (counted, provisional, older, harness, invalid).
  `labels`: `{model, maker, packager, hw, machines: [label], provider}` display strings.

### `cells`
One entry per setup x task with at least one run in the suite that reached the task (states counted, provisional,
older, harness, invalid), sorted by (setup, task):

```
{setup, task, runs, counted?: Block, provisional?: Block}
Block = {n, n_scored, mean, min, max, n_finished, mean_finished, timeouts, errors}
```
`runs` is all runs in the cell (any of those states). `counted`/`provisional` cover the runs in that state and are
omitted when there are none. In a block `n` is all the runs in that state, `n_scored` those with a numeric score,
`mean/min/max` are over the scored runs, `n_finished`/`mean_finished` over scored runs whose outcome is `finished`
(quality in comparisons), `timeouts`/`errors` count runs (scored or not) by outcome. The page's own counts are
`n_scored`.

### `setup_stats`
Time, speed and cost per setup for every included-tier subset x provisional on/off. These are the numbers the
leaderboard shows (the page's `V.stats`): over the setup's *scored* `counted` runs (and with provisional on, also its
scored `provisional` runs) in tasks of the included tiers:

`Stats = {runs, time (median elapsed_s), tps: {median, n} (runs that recorded it), cost (mean run cost over runs that have one)}`

Format `"subsets"` (suites with at most 5 tiers):
`{format, tiers: [tier id in suite order], keys: [key], by_setup: {<setup id>: {stats: [Stats], index: [int]}}}`.
`keys` is the same for every setup: all non-empty tier subsets, largest first, first with provisional off then on.
A key is the subset's tier IDs joined by `+` in suite order, then `:p0` (provisional off) or `:p1` (on), e.g.
`spark+temper+forge:p0`, `temper:p1`. For a setup, `index[i]` is the position in its `stats` array that applies to
`keys[i]`, or `-1` when the setup has no such run. Identical stats objects are stored once.

Format `"cells"` (more than 5 tiers): `{format, tiers, by_setup: {<setup id>: {<task id>: {counted?: [[elapsed_s, tps, cost]],
provisional?: [[...]]}}}}`: one triple per scored run; the page computes medians and means itself.

A setup's stats pool all its tasks, whatever their mode. Setups seldom span modes (a harness serves one), and the
Combined view's pooled median across paired setups can't be derived from medians: it needs the per-run values
(a known limit, see the stage 2b report).

### `other`
`{<model id>: {<state>: n}}`, runs that don't count, for the "Other runs" notes. States: `older, harness, invalid,
retired, unknown_task, withdrawn`, and `unscored` (counted runs without a numeric score). Zero counts are omitted.

## `<suite>/tasks/<task>.json`
`{suite, task, runs}`. `task` is the full catalog task (as in `catalog.tasks[]` plus `prompt`, `rules`, `criteria`,
`summary`). Every catalog task has a file, retired ones too. `runs` are the slim runs that resolved to the task (every
state except `unknown_task`; withdrawn included), newest first (by `started_at`, then `run_uuid`, descending).

Slim run: `{run_uuid, setup, state, score, outcome, elapsed_s, tps, cost, started_at, tool_calls, machine}`.
`score` is the suite's chosen score (null if none); `machine` the registry machine label or null (display only).

## `<suite>/models/<model>.json`
`{suite, model, runs}`: every run of the model in the suite, every state, as slim runs with an extra `task` (the
resolved task id, or the recorded one for `unknown_task`).

## `runs/<run_uuid>.json`
```
{run_uuid, summary, resolution, setup, validity: {state, reason}, suites: {<suite id>: {state, task, score, score_ref}},
 cost, outcome, scores: [score record], status: [status record], output}
```
- `summary`: the useful part of the record: `format_version, started_at, ended_at, elapsed_s, legacy_run_id,
  task {id, version, rubric_version, alias, content_hash, rubric_hash}, harness, model {id, base, raw_base, maker, packager,
  format, format_source, quant, reasoning, context_loaded}, endpoint {where, provider, served_via, upstream,
  resolved_model}, hardware {key}, outcome, metrics (all of them), provenance {crucible_version, crucible_commit,
  source, content_hash}`. Host, device and machine fields of the record are not copied.
- `resolution`: what the registry made of the record: `model, maker, packager, format, quant, where, provider,
  hardware_key, reasoning, harness, artifact, variant, deployment, setup, unrecorded, sources, notes, machine`.
  `sources` says where each field came from (`model_from`: recorded|alias|override|unknown, `hardware_from`, ...);
  `notes` are the "Recorded as ... corrected: <reason>" lines (machine names scrubbed from them); `machine` is the
  registry label or null.
- `suites`: per visible suite, the run's state and chosen score; `score_ref` is `{rubric_version, method}` of the
  record used.
- `scores`: every score record for the run, with `items` and `groups`. `status`: every status record, oldest first.
- `output`: `outputs/<run_uuid>.txt` when the output file exists, else null.

## `recent/<YYYY-MM>.json`
`{month, runs}`: every run started that month (newest first), slim: `{run_uuid, started_at, setup, model, task (as
recorded), harness, outcome, elapsed_s, cost, tps, machine, validity, states: {<suite id>: {state, task, score}}}`.
