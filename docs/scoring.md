# Scoring

How a run becomes a score. Every score is deterministic: programmatic checks for chat answers,
hidden tests for repos. AI-judge and human review exist (`crucible judge`, `crucible score`) but are
never part of a run, and their scores aren't part of any suite. The rules for each task's checks
are generated into [checks.md](checks.md).

## A task's score

A task's `rubric` lists criteria worth points; each is bound to a check (`check: <id>`) or to the
hidden tests (`hidden_tests: <selector>`). A task whose every criterion is bound is fully
deterministic and is scored the moment its run ends.

- **Points.** A check passes or fails its criterion's points, unless it reports a share (an
  `items` check or `grade_closeness`), which earns that share of the points. The score is points
  earned / points available x 10. A criterion with `cap_if_failed` caps the score when it earns
  nothing (e.g. a modified contract suite).
- **Per test** (`scoring: per_test`). Every hidden test weighs the same: passed / all tests x 10.
  A criterion's points are the share of the tests it selects. Gates (`existing`, `contract_unchanged`)
  earn nothing and only cap; a test criterion with `cap_if_failed` keeps its points and also caps the
  score when any one of its tests fails (cursor-pagination's cursor correctness, capped at 6).

## Score records

Each scoring writes a score record, `scores/r<rubric_version>.<method>.json` in the run folder
(method `checks` or `hidden_tests`). A rescore under a new rubric version adds a record; it never
edits the run or an earlier score.

```json
{"record": "score", "format_version": 3, "run_uuid": "…", "rubric_version": 4, "rubric_hash": "…",
 "method": "checks", "scored_at": "…", "crucible_version": "3.0.0",
 "raw": {"passed": 12, "total": 13, "unit": "items"}, "score": 9.23, "scale": 10, "capped_at": null,
 "items": [{"id": "error-line-1", "group": "errors found", "label": "Line 1 flagged", "passed": true, "detail": "1: 1492"}],
 "groups": [{"id": "errors found", "passed": 5, "total": 5}]}
```

`raw` is the source of truth: what was counted (`points`, `items` or `tests`) and how many
passed. `score` is derived (`passed / total x scale`, then any cap) and stored for convenience.
`items` keeps every check or hidden test with its detail; `groups` rolls them up per rubric
criterion for the dashboard's bars. The catalog states each task's expected `total`; a score record
whose total differs can be flagged rather than counted, which catches a grader that silently
skipped tests.

## Answer blocks

New and converted chat tasks follow one convention (decision D12):

1. **Inputs are numbered and atomic:** each claim, sentence or event is one numbered item with one
   checkable fact.
2. **The model reasons in prose, then ends with a fixed block** (`ANSWERS:`, `ERRORS:`, `ORDER:`)
   with one item per line, in the same format wording across tasks. Only the block is scored.
3. **Each expected item scores on its own, with equal weight** (the `items` check): items passed /
   all items x 10.
4. **Normalization only for short values** (numbers, names with listed aliases, letters, line
   numbers, dates): case, punctuation, thousands separators, accents, `**bold**` and code fences.
   Never fuzzy-match sentences.
5. **A missing or unparseable block scores 0, and so does an empty answer.** The parser accepts the
   common variants (`**ANSWERS**`, `Answers:`, a fenced block) and takes the last block.
6. **Accurate controls:** a detection task includes correct items, and leaving them out of the block
   is itself an item, so flagging everything can't win.

Validate every check against a reference answer (10), an empty answer (0) and real wrong answers
from `runs/` where they exist.

## Aggregating

The dashboard, not Crucible, aggregates (from the suite's catalog, [bundle-format.md](bundle-format.md)):
- Tiers are scored separately, never blended: Spark is a gate, Temper the headline, Forge a stretch
  ([task-tiers.md](task-tiers.md)).
- A tier needs `coverage_min` of its tasks run. Repeat runs of a configuration are averaged, shown
  with n and the range (decision D4).
- The capability ranking has one row per base model and reasoning level, scored by its best single
  configuration (device × quant × harness × provider); runs from different configurations are
  never averaged (D13). See [data-model.md](data-model.md) for the keys.
