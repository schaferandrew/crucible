---
name: add-task
description: Add a new Crucible chat task, or convert an existing one to the answer-block format, end to end - numbered atomic inputs, a fixed answer block scored item by item with the items check, validation against reference, empty and real wrong answers, version bumps, the lock, SUITE_CHANGELOG and the checks doc. Use when asked to add, write, convert or rewrite a chat task, or to move one to an answer block.
---

# Add or convert a chat task

Chat tasks follow one convention (decision D12, [docs/scoring.md](../../../docs/scoring.md#answer-blocks)):
the model reasons in prose, then ends with a fixed block, and **only the block is scored**, one item at a time,
every item weighing the same. The worked example is `tasks/fact-check-history.yaml` (formerly HIST-2); read it
before starting.

Touch only your task's files: `tasks/<slug>.yaml`, `tasks/versions.lock.json`, `docs/checks.md` and a
SUITE_CHANGELOG line. If the task needs something the `items` check can't express, stop and ask: that's an engine
change in `crucible/checks.py` (a tool release with tests and a CHANGELOG entry), not a task change.

## 1. Inputs: numbered and atomic

Number every claim, sentence, event or question, one checkable fact each, so an answer line can only refer to
one of them. HIST-2 turned a paragraph into eight lines:

```
1. Christopher Columbus first reached the Americas in 1493.        <- wrong: 1492
2. In 1215, King Richard sealed Magna Carta at Runnymede.          <- wrong: John
3. The United States Declaration of Independence was adopted on July 4, 1776.
...
8. Germany was reunified in the year after the Berlin Wall fell.   <- true, its own line
```

- Every wrong item is correctable to **one short value**: a year, number, name, letter, date. If the fix would
  be a sentence, rewrite the item ("on its return voyage" became "sank in April 1913").
- A detection task needs **accurate controls** (HIST-2 has 3 of 8), and leaving each one out is an item, so
  flagging everything can't win.
- Don't put the answer in the prompt, a fixture, or a comment the model sees.

## 2. The answer block

Copy the format paragraph **word for word**, so following it is equally hard in every task. Only the header,
the line shape and the value examples change between the two forms.

Detection (find and correct the wrong items), as in HIST-2:

```
Explain your reasoning first if it helps. Then end your reply with this block, and nothing after it:

ERRORS:
<number>: <corrected value>

One line per inaccurate numbered item, and none for accurate ones. Give only the corrected value (a year,
number or name), not a sentence. If every item is accurate, write `ERRORS: none`.
```

Questions (one answer per numbered question):

```
Explain your reasoning first if it helps. Then end your reply with this block, and nothing after it:

ANSWERS:
<number>: <answer>

One line per numbered question, in order. Give only the answer (a number, name or letter), not a sentence.
```

Use `|` block style for the prompt in YAML so the block's lines stay as written.

## 3. Expected items in YAML

Each scored thing is an item of an `items` check. A criterion bound to an `items` check earns its share of
the points, so **give each criterion as many points as it has items**: the score is then items passed / all
items x 10, and the score record shows one bar per criterion. Several checks can read the same block.

```yaml
checks:
- id: errors_found
  type: items
  header: [ERRORS, ERROR]          # names accepted for the block; case, bold, `##` and a missing colon are fine
  items:
  - {id: listed, expect: [1, 2, 4, 5, 7], of: [1, 2, 4, 5, 7], normalize: line_set}   # 5 items
  rule: 'Lists each inaccurate claim (1, 2, 4, 5 and 7) in the ERRORS: block; one item per line.'
- id: corrections
  type: items
  header: [ERRORS, ERROR]
  normalize: year                  # default for this check's items
  items:
  - {id: columbus, key: '1', expect: 1492, label: 'Line 1 corrected to 1492'}
  - {id: king, key: '2', expect: John, normalize: name, aliases: [King John], label: 'Line 2 corrected to King John'}
  rule: 'Corrects each one to its value alone: ...'
- id: accurate_kept
  type: items
  header: [ERRORS, ERROR]
  items:
  - {id: listed, expect: [], of: [3, 6, 8], normalize: line_set}                      # 3 items
  rule: 'Leaves the accurate claims (3, 6 and 8) out of the ERRORS: block; one item per claim.'
rubric:
- {criterion: Errors found, max_score: 5, check: errors_found, description: ...}
- {criterion: Corrections, max_score: 5, check: corrections, description: ...}
- {criterion: Accurate claims left alone, max_score: 3, check: accurate_kept, description: ...}
```

Normalizers (the header comment in `crucible/checks.py` has the full list):

| `normalize` | Reads | Passes when |
|---|---|---|
| `number`, `money` | the first number in the value | it equals `expect` (within `tolerance`; money to half a cent) |
| `year` | every 3-4 digit year in the value | each one is expected: "18 June 1815" passes, "1812 or 1815" fails |
| `name` | the whole value, folded (case, accents, punctuation, a leading "the") | it's `expect` or one of `aliases`; never a sentence |
| `line_set` + `of` | the line labels in the block | each line in `of` is listed exactly when it's in `expect` (one item per line) |
| `letter_set` + `of` | the letters in the block | each letter in `of` is in or out as expected (one item per letter) |
| `ordering` | the block's entries | each pair of `expect` is in order (one item per pair) |
| `line_number`, `datetime` | the value | same line number / same date, time, zone as far as `expect` states |

- `key: '4'` reads the block line labelled 4 (`4: …`, `4. …`, `4) …`, `Line 4: …`, `- Q4: …`); the last such
  line wins. Without `key`, items take the block's lines in order.
- A value written `wrong → right` (or `->`, `=>`) is scored on what follows the arrow.
- Every `rule` is plain English and states the answer (docs/checks.md publishes it, decision D7).
- A new task needs an `id` and `name` (the ID says what it is, never its tier or difficulty) and
  `status: provisional`, always. Its `area`, `category` and `tier` must be IDs that already exist in
  `tasks/taxonomy.yaml`; adding one there is a suite change, so ask first.

## 4. Validate

Write the cases into a YAML file in your scratchpad (`name`, `expect`, `answer`; copy
[examples/fact-check-history.yaml](examples/fact-check-history.yaml)), working out every expected score by hand
first as items passed / all items x 10. Then:

```bash
uv run python .claude/skills/add-task/validate.py <task> <cases.yaml>
```

It prints the table (answer, expected, actual) and the detail of every item for a case that misses. Every one
of these must land where you expect:

1. **Reference answer: 10**, with and without prose before the block.
2. **Empty answer and whitespace only: 0.** Also an answer with no block (the old format): 0.
3. **Gaming:** flagging every line scores well below 10 (HIST-2: 7.69 even with perfect corrections, 3.85 with
   junk values); `ERRORS: none` earns only the controls (2.31).
4. **Realistic wrong answers** from real runs of the old version. `runs/` in the main checkout is real data:
   copy it into your scratchpad (`rsync -a --exclude node_modules --exclude .git`), run
   `uv run crucible migrate --runs <copy>`, and read answers from the copy with `checks.final_answer(run_dir)`;
   never touch the original. Adapt each into the new format, keeping its mistakes (missed errors, false flags,
   wrong values, whole sentences instead of values, hedges like "1812 or 1815").
5. **Formatting variants of the reference all score 10:** a bold header (`**ERRORS**`), a `## Errors`
   heading, a code fence around the block or inside it, a draft block followed by the final one, bullets,
   `Line n:` and `n.` labels, a blank line after the header, the singular header, the first line on the
   header line.

A miss means the check or your arithmetic is wrong: fix the check (or the prompt) and say so, never the
expected score to fit. Put the table in your report. (Tests are the tool's track: add an oracle test beside
`test_fact_check_history_oracle` in `tests/test_answer_blocks.py` only if your brief lets you touch tests.)

## 5. Versions, lock, changelog, docs

1. Converting: bump `version` (the prompt changed, old runs no longer count) and `rubric_version`; keep or
   improve `name`. New task: `version: 1`, `rubric_version: 1`. A scoring-only fix: `rubric_version` alone.
2. `uv run crucible versions --update`, then `uv run crucible versions` (clean) and `uv run crucible suite
   verify` (holds).
3. One line under `## Unreleased` in `SUITE_CHANGELOG.md`, for someone reading the leaderboard: the slug and
   old ID, the versions, what changed, why, and whether runs must be redone.
4. `uv run crucible checks --doc docs/checks.md`.
5. `uv run --with pytest python -m pytest -q tests`: all pass. The 3.0.0 rename tests skip tasks bumped since
   3.0.0, so a bump doesn't break them.
6. Commit on your branch. Don't push, merge or cut a suite: the task stays provisional until `crucible suite
   cut`, and the user asks for that separately.

Report: the branch and commits, the validation table, the versions you bumped, and anything the format
couldn't express.
