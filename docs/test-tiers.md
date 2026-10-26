# Test tiers and metric integrity

Status: the groundwork is in (tiers, versions, lock, release 2026.11, backfill, environment capture, `crucible judge`, `crucible export`). The new tests below are still proposals.

Day to day:

- `crucible run spark|temper|forge` runs a whole tier.
- `crucible versions` checks the lock (CI runs the same check). After editing a prompt, bump `version` (content) or `rubric_version` (rubric), then run `crucible versions --update`.
- `crucible versions --release 2026.12` pins the active tests into a new release file.
- `crucible versions --backfill runs` stamps older runs with the version they used.
- `crucible judge <run_dir> <payload.json>` saves an agent score; the judge follows `crucible/judge_instructions.md`.
- `crucible export --out <file>` writes the JSON the portfolio page reads.

## Three tiers

Tier is a third axis next to suite (from the test-ID prefix) and category (the scoring class). A test keeps its ID and suite, and gains a `tier`. Coding, writing and the rest each get tests at every tier.

| Tier | Question it answers | Bar |
|---|---|---|
| **Spark** | Does it light up? It loads, follows a format, calls a tool, reads code and makes a small correct change. | A model you'd run at all should score 8+ here. Failing Spark is disqualifying, so it works as a gate, not a ranking. |
| **Temper** | Does it hold an edge under real daily work? These are the things you'd hand it on a normal day and expect to use the output. | This is the headline ranking for local models. |
| **Forge** | Can it do work you'd normally need a frontier (trillion-parameter-class) model for? That means long-horizon, multi-file, ambiguous, high-stakes tasks. | A strong mid-size local model should struggle here. A clean Forge result is the news. |

The names follow the crucible metaphor: the spark lights the fire, tempering is what makes steel usable, and the forge is the big heat.

## Current tests by tier

| Tier | Tests | Count |
|---|---|---|
| Spark | KNOW-1 (firetruck color), WRIT-1a (3 obvious email errors), RSCH-2b (fetch a given weather URL), TASK-2 (call 3 mock tools and combine them) | 4 |
| Temper | CODE-1, CODE-1b, CODE-2, CODE-2b, CODE-3, CODE-6, RSCH-1, KNOW-2, KNOW-3, RSCH-2, MATH-4, TASK-1, TASK-3, KNOW-5, KNOW-6, KNOW-7, KNOW-8, WRIT-1b, WRIT-1c, WRIT-2, WRIT-2b, CODE-4, CODE-4b | 23 |
| Forge (candidate) | CODE-5 (reproduce an intermittent bug in a real browser, then fix it) | 1 |

There are three gaps:

- **Spark is thin.** It needs tests that check the mechanics on their own: context length, schema compliance, a single precise tool call, and repo navigation.
- **Forge is effectively empty.** qwen3.8-27b, a 27B model, scored 9.2–10 on every coding test (agent score), including CODE-4, CODE-4b and CODE-5. Those three are browser-driven and were the hardest-looking tests, but in practice they sit at Temper. CODE-5 stays a Forge *candidate* only until calibration (below) confirms or demotes it.
- **Temper carries almost everything,** so today's headline score is really a Temper score.

## New tests

IDs continue each suite's numbering and are never reused. Each test lists what it adds.

### Spark (target: 10–12 total)

| ID | Test | What it checks |
|---|---|---|
| C7 | **Find it.** In the `nextjs-data-access` repo, name the file and function that loads account data, and the line that decides the plan name. | Reading and navigating code without editing |
| C8 | **One-line fix.** A tiny repo with one failing unit test caused by an off-by-one error. Make it pass without touching the test, then run the suite. | Edit, run and verify loop |
| KNOW-4 | **Schema out.** Turn a short paragraph into JSON matching a supplied JSON Schema. Output only the JSON. | Format compliance, which local models often get wrong |
| E8 | **One tool call.** Using the mock calendar MCP, answer "What's my first meeting on Thursday?" Graded on the tool arguments and the answer. | Single precise tool call, no over-calling |
| G4 | **Needle.** A roughly 60k-token fixture document with 3 planted facts to retrieve and quote. | Whether the configured context length actually works. LM Studio and Ollama default to small contexts and silently truncate. |
| WRIT-3 | **Constraints.** Write a 120–150 word product note: 3 bullets, no adverbs, uses two given terms, no exclamation marks. | Following explicit, checkable instructions |
| X0 | **Load probe** (not rubric-scored). A fixed 200-token prompt that records time to first token, tokens per second and peak memory. | Whether it runs on this hardware at a usable speed. This is the hardware axis the portfolio issue asks for. |

### Temper (add to balance the suites)

| ID | Test | What it checks |
|---|---|---|
| C9 | **Add a feature.** Add pagination and filtering to a small existing REST API, with tests and docs. | The typical feature ticket |
| C10 | **Review a PR.** A diff with 3 planted bugs and 2 style nits. Find the bugs, rank them, and don't invent more. | Code review precision |
| G5 | **Messy data.** A CSV of a year of household spending (dupes, mixed date formats, refunds). Produce correct totals by category and the 3 biggest changes. | Arithmetic you can check, plus cleaning judgment |
| W4 | **Translate for humans.** Rewrite a technical incident report for a non-technical audience without losing or changing any fact. | Fidelity under rewriting |
| H5 | **Read the manual.** A dishwasher manual fixture plus an error code. Diagnose it, citing manual sections, and say when to stop and call. | Grounded answers from a supplied document |

### Forge

Built (provisional until calibrated). All five run on Conduit, a RealWorld monorepo (Express API, React web app, shared TypeScript package), and each is graded mainly by hidden acceptance tests in `graders/forge/<test>/` that the model never sees. Forge difficulty comes from the context a model has to take in and the competing requirements it has to balance, not from wall time: frontier models should finish in 10–20 minutes, with a 30-minute cap.

| ID | Test | What makes it hard |
|---|---|---|
| CODE-11 (v3) | **Editorial review from a product brief.** Only a small client contract is given; the rules (no self-approval, private feedback, nothing unapproved ever visible) must be found and applied everywhere articles surface. | Rules spread across every list, filter and endpoint; a built-in conflict with RealWorld's edit-in-place behavior to notice and resolve |
| CODE-12 | **Cursor pagination migration** across lists, feed and comments without breaking offset clients. | Correctness under concurrent writes; tamper-proof, query-bound cursors |
| CODE-13 | **Production incident** from ~4 MB of logs: a response cache leaking per-user data and serving stale writes. | Root cause from evidence; a postmortem whose numbers are checked against ground truth |
| CODE-14 | **Redirect loop from conflicting checks.** Invited accounts are created in a special state; the editor guard requires an onboarding flag they never get, the welcome page sends them back. Plus a sign-up dead end and a Legal requirement that conflicts with the design doc. | Two checks that each look right; already-broken accounts that must recover without data fixes; design doc vs Legal |
| CODE-15 | **Accessibility audit.** Fix six WCAG findings (dialog focus, disclosure announcements, a mouse-only custom widget, unnamed icon buttons, unlinked form errors, a silent status message) without changing the design or component APIs. | Native vs ARIA trade-offs; keyboard and screen reader behavior verified with axe-core and keyboard tests |

Calibration so far: the free DeepSeek V4.1 Flash scored 10/10 on CODE-11 v2, CODE-12 and CODE-13 in 5–8 minutes each. That's last year's frontier solving realistic hard problems, which is a fine result; CODE-11 v3, CODE-14 and CODE-15 aim at the "lots of context, competing requirements" kind of difficulty that separates models more.

## Keeping the metrics honest as tests are added

The risk: a model's score changes because the test set changed, not because the model did. Six rules prevent that.

### 1. Version every test

Each prompt YAML gains:

```yaml
test_id: CODE-3
tier: temper
version: 1            # bump by hand when prompt, fixture or repo changes
rubric_version: 1     # bump when only the rubric changes
status: active        # provisional | active | retired
```

- The runner writes `test_version` into `meta.json`, plus a `content_hash`: a hash of the prompt, the repo and the fixture tree.
- CI recomputes the hashes and fails if the content changed without a version bump, so drift can't happen silently.
- **Prompt or fixture change → new version → old runs are not comparable and must be rerun.**
- **Rubric-only change → re-score the stored outputs; no rerun needed.** Run directories already keep the output, so re-scoring is cheap (minutes with the agent judge).

### 2. Score on a release, not on "whatever exists"

A release file pins the test set:

```yaml
# releases/2026.11.yaml
release: "2026.11"
judge: { model: claude-opus-5-5, prompt_version: 1 }
tests:
  - { id: CODE-1, version: 1, tier: temper, category: coding_build }
  - { id: KNOW-1, version: 1, tier: spark,  category: everyday }
  # ...
weights:          # category weights within each tier; same role as CATEGORY_WEIGHTS today
  temper: { coding_repo: 0.15, ... }
```

- Every published number says which release it is on, and models are only ranked against each other on the same release.
- A new release is cut when tests are added or bumped. Old runs keep counting toward any release whose `test@version` they match, so adding C9 doesn't throw away qwen's CODE-1 run.

### 3. New tests start provisional

New tests run and show up in the table, but stay out of tier scores until the next release. Before promotion, each one is **calibrated** on three anchor models: a small local model (e.g. 9B), a mid-size one (e.g. 27B) and a frontier model.

| Tier | The test is placed correctly if… |
|---|---|
| Spark | the small anchor scores 8 or more |
| Temper | the mid anchor scores 6 or more and the frontier anchor beats the small one by 2 or more |
| Forge | the mid anchor scores 5 or less and the frontier anchor scores 7 or more |

A test that misses its tier band moves tiers before promotion. This would have caught CODE-4, CODE-4b and CODE-5 being too easy for Forge.

### 4. Report tiers separately, never blended

- **Spark: pass or fail.** It passes at a mean of 8 or more with no test below 5. A fail is shown and the model is unranked.
- **Temper score** (0–10): the headline.
- **Forge score** (0–10): shown when present.

Blending tiers into one number would let a model with great Forge results hide a broken Spark, and adding Spark tests would shift everyone's single score.

### 5. A score needs coverage

- A tier score is published only when at least 80% of that tier's weight in the release has been scored.
- Below that it shows as partial (hollow marker, "15/23 tests") and is left out of rankings.
- The portfolio already shows coverage; this makes it the rule.

### 6. Record where every number came from

- **Every score records:** scorer type (human or agent), judge model, judge prompt version and `rubric_version`.
- **Judges are never mixed:** a release uses one judge, and agent and human scores don't go into the same mean. If the judge changes, re-score the whole release with it.
- **Every run records:** harness and harness version, inference host hardware, quantization, configured context length and sampling settings. This is the hardware axis, and it also explains odd results (a 4k context fails G4 by construction).
- **Repeats:** run each `test@version` at least twice per model and harness. Show the mean and the range instead of only the latest run. One sample can't tell a 1-point difference from noise.

## What this means for the current branch

These are the changes in Crucible, roughly in order:

1. **Taxonomy:** `taxonomy.py` gets `TIERS` and a `tier_for(test_id)` lookup from the YAML.
2. **Prompt YAMLs:** add `tier`, `version: 1`, `rubric_version: 1` and `status` to all 28.
3. **Runner:** writes `test_version`, `content_hash`, `rubric_version` and host/quant/context info into `meta.json`.
4. **Scorer and agent judge:** write `rubric_version` and the judge details into `results.json` / `agent_results.json`.
5. **Releases:** add `releases/2026.11.yaml` (all 28 current tests at v1) and a CI check for undeclared content changes.
6. **Backfill existing runs:** every run directory saved `prompt.txt`, so hash it against the v1 prompt. Runs that match get `test_version: 1`. Fixture contents weren't recorded, so they're assumed unchanged since no fixture has been edited.
7. **Exporter:** group scores by release, then tier, then category. The portfolio shows the Spark gate, then Temper and Forge scores, each with coverage.

New tests (C7–CODE-14, KNOW-4–E8, G4–G7, WRIT-3–W5, H5–H6, X0) land afterwards as provisional and are promoted in the next release once calibrated.

## Open questions

- Should Spark failures hide a model from the portfolio entirely, or show it with a "failed basics" flag? The flag seems more useful, since knowing a model breaks is information.
- Is the frontier anchor for calibration a paid API model (Claude or GPT via OpenRouter)? It needs to stay the same across releases.
- X0 needs per-host hardware capture first (see the portfolio issue: machine, GPU, VRAM/RAM).
