# E: Calibration runs (outline)

One Sonnet session, a single queue: one `crucible run` at a time, never loading or unloading
models (use what LM Studio already serves, often over LM Link), cloud runs one at a time.

- Calibration set per task: one small local, one mid-size, one frontier cloud model (Andrew
  picks the models before this starts).
- After each task: report its score spread, n, and whether it separates the three models; flag
  any task where the reference answer, an empty answer or a real run scores unexpectedly.
- Feeds the Suite v2 cut (F): a task is promotable when its oracle passes and its scores aren't
  all equal.
