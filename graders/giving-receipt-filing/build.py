#!/usr/bin/env python3
"""Regenerate the giving-receipt-filing fixtures, reference solution and calibration fixtures.

    python graders/giving-receipt-filing/build.py

Writes fixtures/giving-tracker/ (what the agent is seeded with: giving-log.csv, records/, inbox/; the README
beside them is the ground truth and is never listed as a task fixture) and graders/giving-receipt-filing/
solution/ and calibration/. Everything comes from support.py, so the data and the tests cannot drift apart.
"""
import csv
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import support as s  # noqa: E402

FIXTURES = HERE.parent.parent / "fixtures" / "giving-tracker"


def write_log(dest, rows):
    with open(dest / "giving-log.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(s.HEADER)
        w.writerows(rows)


def new_row(r, date=None):
    date = date or r["date"]
    return [date, r["org"], f"{r['amount']:.2f}", "Card" if r["method"] == "card" else "Check", date[:4], s.rel_path(date, r["org"])]


def seed(dest):
    """The starting workspace."""
    (dest / "inbox").mkdir(parents=True)
    write_log(dest, s.EXISTING_ROWS)
    for d, o, a, m, lines in s.EXISTING:
        p = dest / s.rel_path(d, o)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(s.make_pdf(lines))
    for r in s.RECEIPTS:
        (dest / "inbox" / r["inbox"]).write_bytes(r["pdf"])


def solve(dest, dates=None, rows=True, files=True):
    """The seed with the work done. dates: {receipt id: the date to file it under} for calibration fixtures."""
    seed(dest)
    dates = dates or {}
    out = list(s.EXISTING_ROWS)
    for r in s.RECEIPTS:
        date = dates.get(r["id"], r["date"])
        if files:
            p = dest / s.rel_path(date, r["org"])
            p.parent.mkdir(parents=True, exist_ok=True)
            (dest / "inbox" / r["inbox"]).rename(p)
        if rows:
            out.append(new_row(r, date))
    write_log(dest, out)


def fresh(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def main():
    for name in ("giving-log.csv", "inbox", "records"):
        p = FIXTURES / name
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    seed(FIXTURES)
    cal = HERE / "calibration"
    shutil.rmtree(cal, ignore_errors=True)
    fresh(HERE / "solution")
    solve(HERE / "solution")
    # every wrong-year mistake a model can make from the file names or the letter dates
    fresh(cal / "filed-by-letter-date")
    solve(cal / "filed-by-letter-date", dates={"pantry": "2026-01-04"})
    fresh(cal / "filed-by-todays-date")
    solve(cal / "filed-by-todays-date", dates={r["id"]: "2026-11-08" for r in s.RECEIPTS})
    fresh(cal / "log-only")
    solve(cal / "log-only", files=False)
    fresh(cal / "files-only")
    solve(cal / "files-only", rows=False)
    for p in HERE.rglob("inbox"):  # git keeps no empty folders; an empty inbox is the same as none
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()


if __name__ == "__main__":
    main()
