# Data model

What a run records, how it's identified, and how scores and invalidations attach to it. The code is
`crucible/runrecord.py`; the published schemas are in `crucible/schemas/` (`run`, `score`,
`status`, `catalog`).

## Run folders

```
runs/<model_slug>/<task>/<timestamp>/
  meta.json                         the run record
  prompt.txt  stdout.txt  stderr.txt  command.sh  session.json  direct-response.json
  workspace/                        agentic runs: the seeded repo as the agent left it
  scores/r<rubric_version>.<method>.json   score records
  status.json                       status records, an append-only list
  grader_results.json               the hidden tests' raw results (evidence; the score is in scores/)
```

`<model_slug>` is the provider/model with unsafe characters replaced, plus `@reasoning-<level>` for
a non-default reasoning level (each level is its own model). Runs from before 3.0.0 used
`<model_slug>/<category>/<test_id>/<timestamp>`; `crucible migrate` moves them (below).

## The run record

`meta.json` is written when the run ends and never edited afterwards. Everything except `local` is
published; `local` stays on the machine.

| Field | Holds |
|---|---|
| `record`, `format_version` | `"run"`, 3 |
| `run_uuid` | Permanent identity (below) |
| `run_path` | `<model_slug>/<task>/<timestamp>`: where it lives today, not its identity |
| `legacy_run_id` | The pre-3.0.0 `run_id` of a migrated run, else null |
| `started_at`, `ended_at`, `elapsed_s` | Timing |
| `task` | `id`, `version`, `rubric_version`, `content_hash`, `rubric_hash`, and `alias`: the ID a migrated run was recorded under |
| `harness` | `id` (direct, opencode, pi), `version` |
| `model` | `id` (provider/model as run), `base`, `publisher` (who packaged the weights), `artifact` (the packaged repo they were downloaded from, when the source names it), `format`, `quant`, `reasoning` (`requested`, `resolved`), `context_loaded`, `variant_key`, `display`, and since 3.6.0 `origin` (who trained them, below) |
| `endpoint` | `where` (local or cloud), `provider`, `app`, `served_via` (LM Link), `device`, `upstream` (OpenRouter's provider), `resolved_model` |
| `hardware` | The device that ran the weights: `key`, `class`, `accelerators`, `system_memory_gb`, `cpu`, `offload`, `label`. Null for cloud runs |
| `outcome` | `status` (completed, timeout, no_answer, context_limit, failed, harness_error), `harness_status`, `returncode`, `timed_out`, `invalid` (set at run time), `leaks` |
| `metrics` | Tokens, tool calls, responses, TTFT, response time, cost, reasoning characters |
| `output_ref` | Set when published: `outputs/<run_uuid>.txt` |
| `provenance` | `crucible_version`, `crucible_commit`, `crucible_dirty`, `machine_id`, `machine_label`, `source` (`crucible-run`, `crucible-migrate`, `bundle-format-2`), `content_hash` (set when published), `submitter` and `verification` (reserved, null) |
| `local` | Never published: the raw `environment` capture, `tools`, `watch`, `platform`, the check results, and for migrated runs `legacy_meta` (the 2.x meta.json as it was) |

## Model origin

`model.publisher` is who packaged the weights (`lmstudio-community`, `mlx-community`) and is part of
the variant key. `model.origin` (`crucible/origin.py`, added in 3.6.0) is who **trained** them, read
from the source at run time; Crucible keeps no list of labs or models.

```json
"origin": {"maker": "qwen", "base_repo": "Qwen/Qwen3.6-35B-A3B-Base", "params": 35100000000,
           "active_params": 3000000000, "source": "gguf"}
```

| Field | Holds |
|---|---|
| `maker` | The lab's namespace, lowercased (`qwen`, `google`, `openai`); null when no source names one |
| `base_repo` | The repo the weights derive from (`Qwen/Qwen3.5-9B`, a Hugging Face ID); null when unknown |
| `params`, `active_params` | Parameter counts as the source states them (an exact count, or a size label: `35B-A3B` is 35e9 and 3e9); never parsed from a model's name |
| `source` | Every source that answered a field, in trust order, joined with `+` (`gguf`, `gguf+lmstudio-key`), or `none` |

Sources, in trust order; the first one that answers a field wins it:

1. `gguf`: the GGUF file's header (`general.base_model.0.repo_url`/`.organization`, then
   `general.organization`; `general.parameter_count`, `general.size_label`), or `mlx-card`: an MLX
   folder's README front matter (`base_model`). Only when the weights are on this machine: LM Studio
   names the file (`lms ps`/`lms ls`) and the device that ran it is this one. Runs over LM Link skip it.
   The same path fills `model.artifact` (`lmstudio-community/Qwen3.5-9B-GGUF`).
2. `ollama`: `/api/show`'s `model_info` (the same `general.*` keys) and `details.parameter_size`.
   A model pulled from `hf.co/<org>/<repo>` gets that repo as its `artifact`.
3. `openrouter`: the model ID's author prefix, with a leading `~` dropped (`~openai/gpt-luna-latest`
   is `openai`), for every harness; plus `hugging_face_id` as `base_repo` when Crucible already
   fetched the model's `/models` entry in that process (opencode's pricing does).
4. `lmstudio-key`: LM Studio's model key prefix (`qwen/qwen3.5-9b` is `qwen`).

A packager namespace (`origin.PACKAGERS`: mlx-community, lmstudio-community, unsloth, bartowski) is
never a maker; the same list sets `publisher` from a model key. Everything is best effort: an
unreadable file or an unreachable server leaves nulls and never fails the run. Runs recorded before
3.6.0 have no `origin` and aren't backfilled (run records never change); readers treat it as
optional and work the maker out themselves for those runs.

## Identity keys

| Key | Made of | Used for |
|---|---|---|
| `run_uuid` | UUIDv4 minted before the run starts; migrated runs get a UUIDv5 (below) | Dedup, score and status records, URLs |
| `task_key` | `task.id` + `task.version` | Which suites a run counts in |
| `variant_key` | `base` \| `publisher` \| `format` \| normalized `quant` | One model "as weights" |
| `model_key` | `variant_key` + `reasoning.resolved` | A leaderboard row |
| `config_key` | `model_key` + `endpoint.where` + (`provider`, `upstream` for cloud) + `harness.id` + `hardware.key` (local) | Repeat-run grouping, drill-down |
| `machine_id` | `m_` + 12 hex, minted once into `~/.crucible/machine.json` | Provenance; never the hostname |

Normalization: `quant` is lowercased (`Q4_K_M` → `q4_k_m`, MLX `4bit` → `mlx-4bit`); `base` is the
model without its provider prefix or a date suffix; `format` is `gguf`, `mlx`, `safetensors`, or
`api` in the variant key for cloud models.

**Legacy UUIDs.** A run recorded before `run_uuid` existed gets
`uuid5(NS, f"{machine_id}:{legacy_run_id}")`, where `machine_id = "m_" + uuid5(NS, "host:<hostname>").hex[:12]`,
`<hostname>` is the first label of the hostname the run recorded, lowercased, and `NS` is
`crucible.runrecord.NAMESPACE`. A run that recorded no hostname uses `crucible migrate --machine`
(default: this machine's name), the same name its published bundle's `source.machine` carries.
The same run gets the same UUID from its folder and from its published bundle.

## Hardware key

The accelerator that ran the weights, plus its memory (`crucible/hardware.py`): `m1-pro-32gb`
(Apple silicon, unified memory), `rtx-5070-ti-16gb` (one GPU, VRAM), `2x-rtx-3090-24gb`,
`rtx-4090-24gb+rtx-3090-24gb` (mixed, by VRAM), `cpu-ryzen-7-7700-32gb` (CPU only, system RAM).
It describes where the weights ran: this machine, or the LM Link peer that served them. Cloud runs
have none.

## Score and status records

A score record is one score of one run at one rubric version by one method; see
[scoring.md](scoring.md). Rescoring after a `rubric_version` bump adds a record; the run record
never changes. Rescoring at the same rubric version replaces the local record, but publishing never
rewrites a published one.

A status record marks a run after the fact: `crucible status <run> --invalid "stale server"`,
`--withdrawn`, or `--valid` to undo. They're appended to `status.json`; the last one wins. A run's
own `outcome.invalid` (a harness error, a context too small, a leak) is set at run time.

## Repeat runs

Every run is kept. Per `config_key` × `task_key` the dashboard shows the mean with n and the range
(decision D4).

## Migrating runs from before 3.0.0

`crucible migrate [--dry-run] [--runs DIR]` works through every `meta.json` under DIR, at any depth:

1. Mints a legacy `run_uuid` into every `meta.json` that lacks one, before anything moves.
2. Rewrites `meta.json` as the run record, mapping the 2.4.0 fields (`model_variant`,
   `hardware_key`, `endpoint`, `provenance`) and keeping the old record under `local.legacy_meta`.
   It fills `publisher` and `format` where the model key or quant implies them (`mlx-community/…`,
   a `-mlx` tag or a `4bit` quant is MLX) and leaves the rest null; cloud runs get no hardware.
3. Turns `check_results.json` (with `grader_results.json`) into a score record at the rubric
   version it was scored under. The score is copied, not recomputed; the old files stay.
4. Moves the folder to `<model>/<task>/<timestamp>`, removing the emptied category folders.

Folders without a `meta.json` (runs stopped before they were recorded) and unknown test IDs are
reported and left alone. Running it twice changes nothing. `crucible migrate --bundle FILE --to DIR`
converts a published format-2 bundle into format-3 records, for runs whose folders exist only on
another machine; runs already in DIR are skipped.
