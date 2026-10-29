# A1: Crucible 2.4.0 groundwork

**Goal.** Record everything Suite v2's run data model needs, from every new run onward, and
add the answer-block engine, without changing how any existing task is scored (decision D10:
scoring fixes wait for 3.0.0). Field names follow audit section 6 so 3.0.0 can map them
directly.

**Branch:** `a1-crucible-2.4.0` from `claude/suite-v2-audit`.

## Scope

1. **Run identity and provenance** (`crucible/runner.py`, `crucible/workspace.py`, new helper as needed)
   - `run_uuid`: a UUIDv4 minted when the run directory is created, written to `meta.json`.
   - `provenance`: `crucible_version` (from package metadata), `crucible_commit` (short git SHA
     of the checkout, or null outside git), `crucible_dirty` (uncommitted changes under
     `crucible/`, `prompts/`, `graders/`, `fixtures/`, `repos/`), `machine_id` (random, minted once
     into `~/.crucible/machine.json`; never the hostname).
   - Do **not** backfill old runs (that's `crucible migrate` in 3.0.0).
2. **Model variant** (`crucible/environment.py`)
   - LM Studio: read `publisher` and `compatibility_type` (format: `gguf`, `mlx`) from
     `/api/v0/models/<id>` alongside the existing quantization. Ollama: format `gguf`, publisher
     from the model name when it has a namespace.
   - Resolved reasoning level: when the request is `default`, record what the provider reports or
     the model's known default when it can be determined; else null. Keep `reasoning` as is.
   - OpenRouter (direct harness): the upstream provider that served the request and the resolved
     model id (the response's `model` field; the generation endpoint for the provider), recorded
     best-effort; null when unavailable. Never fail a run over it.
3. **Hardware key** (`crucible/hardware.py`)
   - A pure function producing the key from audit section 6: `m1-pro-32gb`, `rtx-5070-ti-16gb`,
     `2x-rtx-3090-24gb`, `cpu-ryzen-7-7700-32gb`, with the normalization rules there (drop vendor
     words and in-name memory sizes, alias table). Record it in `meta.json` for local runs.
   - Cloud runs record no hardware: in `crucible/exporter.py`, `hardware` is null when
     `inference.local` is false (today they export the laptop).
4. **Answer-block engine** (`crucible/checks.py`), unused by any prompt yet
   - A parser: find the block by header (`ANSWERS:`, `ERRORS:`, …, tolerant of `**bold**`,
     case, a trailing colon, code fences), take lines until a blank line or the next header, the
     last block wins.
   - An `items` check type: expected items declared in YAML, each scored on its own, reporting
     `share` = passed / total, with normalizers `number`, `money`, `name` (with aliases),
     `letter_set`, `line_number`, `datetime`, and `ordering` (pairs in order). Per-item results go
     into the check's detail so the dashboard can show them.
   - Behind the new type only: existing check types and existing scores must not change.
5. **Export and schema** (`crucible/exporter.py`, `crucible/bundle.py`, `crucible/schemas/results.schema.json`)
   - Add optional run fields: `run_uuid`, `provenance`, `model_variant` (`publisher`, `format`,
     `quant`, `reasoning_resolved`), `hardware_key`, `endpoint` (`upstream`, `resolved_model`).
     Optional and nullable: old runs export with nulls. `format_version` stays 2.
   - `crucible publish` sets `source.crucible_version` (the schema already has it).
6. **Release** (AGENTS.md rules): `pyproject.toml` 2.4.0, `uv lock`, a `## 2.4.0` CHANGELOG entry
   written for people running Crucible.

## Not in scope

No prompt, grader, fixture or repo changes. No change to any existing check's behavior (the
empty-answer fix B2 is 3.0.0). No renames, no new bundle format, no dashboard work, no model runs.

## Done when

- `uv run --with pytest python -m pytest -q tests` passes, with new tests for: UUID and
  provenance in `meta.json`, the hardware key (at least the four shapes above plus "Apple M1 Pro"
  and "M1 Pro" giving one key), the answer-block parser (variants and last-block-wins), every
  `items` normalizer, cloud runs exporting null hardware, and the schema accepting old and new runs.
- `uv run crucible export --out <scratch file>` on the existing `runs/` gives the same `check_score`
  for every run as before the change (compare the two exports), and `crucible publish --check`
  passes on the new export.
- `uv run crucible versions` is clean.
- Committed on the branch with the version bump and changelog entry; not pushed.
