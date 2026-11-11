# giving-tracker fixtures (ground truth, NOT shown to the agent)

Task: `tasks/giving-receipt-filing.yaml`. Hidden grader: `graders/giving-receipt-filing/` (support.py holds the same
data as code; `build.py` regenerates these fixtures, the reference solution and the calibration fixtures).
The task seeds only `giving-log.csv`, `records/` and `inbox/` from this folder, so this README never reaches the agent.
All organizations, people and amounts are fictional. The prompt never states today's date (2026-11-08 when written).

Layout the agent sees: `giving-log.csv` (Date, Organization, Amount, Method, Tax Year, Receipt File),
`records/<year>/<YYYY-MM-DD>_<Org-Name>.pdf` (2024 and 2025 exist, five filed receipts), `inbox/` (three new PDFs).
There is no `records/2026/` yet.

## Expected result per receipt

| Inbox file | Organization | Gift date | Amount | Method | Tax year | Filed as |
|---|---|---|---|---|---|---|
| `receipt-scan-20260104.pdf` | Hope Harbor Food Pantry | 2025-12-31 | 180.00 | Card | 2025 | `records/2025/2025-12-31_Hope-Harbor-Food-Pantry.pdf` |
| `donation.pdf` | Riverbend Public Radio | 2026-01-02 | 60.00 | Card | 2026 | `records/2026/2026-01-02_Riverbend-Public-Radio.pdf` (new folder) |
| `maple-st-statement.pdf` | Maple Street Community Church | 2024-11-17 | 250.00 | Check | 2024 | `records/2024/2024-11-17_Maple-Street-Community-Church.pdf` |

Final log: the five existing rows unchanged plus these three (eight rows). `inbox/` empty. Row order is not scored.

## The traps

- **Pantry**: the letter is dated January 4, 2026 and the scan's file name says 20260104, but the gift was received
  December 31, 2025. The year is 2025 (letter date, file name and today's year all give 2026).
- **Radio**: the gift really is in 2026 (January 2); the letter also quotes "$660.00" as 2025 giving, which is not this
  gift's amount. Needs a new `records/2026/` folder. A model that over-corrects and files it under 2025 is wrong.
- **Church**: a reissued statement "printed March 2, 2026" for a gift made November 17, 2024; "Pledge balance remaining:
  $500.00" is not the gift. The same church already has two rows (2024-12-24 for 300.00, 2025-11-27 for 200.00), so it is
  not a duplicate. Filed by print or upload date it lands in 2026.

## Scoring (graders/giving-receipt-filing, 35 hidden tests, equal weight)

rows (9), dates (12, `cap_if_failed: 6`), filing (12), integrity (2). A PDF is recognised by its sha256, so renaming is
fine but re-rendering it is not. Do nothing: 0. Reference solution: 10. Calibration: filed-by-letter-date 6 (capped),
filed-by-todays-date 6 (capped), log-only 4.57, files-only 4.57.

## Follow-up (not built): HSA variant

Issue #64: a medical receipt where the log must say whether it has been reimbursed from the HSA yet (reimbursed or not yet).
