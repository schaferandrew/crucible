# Toolshed

Inventory and lending tracker for a community tool library. Plain JavaScript (ES modules, Node 18+),
no runtime dependencies. Data lives in a JSON file (`data/tools.json` by default).

## Layout

- `src/store.js`: `ToolStore`, loads and saves the JSON file and announces changes to listeners
- `src/validate.js`: turns raw JSON records into tools, rejects bad ones
- `src/dates.js`: small calendar helpers on `YYYY-MM-DD` strings
- `src/tools.js`: the lending rules (add, loan, return, retire, search, overdue)
- `src/report.js`: summaries and the text table
- `src/cli.js`: argument parsing and the commands
- `test/`: the test suite (`npm test`)

## CLI

`main(argv, { file, today, out })` in `src/cli.js` runs one command and returns the exit code
(0 ok, 1 a rule was broken, 2 bad usage).

```
list [--status available|loaned|retired] [--tag TAG] [--search TEXT]
add NAME --category CATEGORY [--tags a,b] [--cost 12.5]
loan ID BORROWER [--days 7]
return ID
retire ID --reason TEXT
overdue
report
```
