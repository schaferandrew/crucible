"""Hidden tests for giving-receipt-filing: the giving log and the records folder as the model left them."""
import pytest

from support import (EXISTING, EXISTING_ROWS, RECEIPTS, ROOT, filed, inbox_hashes, log_rows, new_rows, norm,
                     parse_amount, parse_date, rel_path)

IDS = [r["id"] for r in RECEIPTS]


def one_row(receipt):
    rows = new_rows(receipt)
    assert len(rows) == 1, f"{len(rows)} new rows for {receipt['org']}, expected 1"
    return rows[0]


def one_file(receipt):
    found = filed(receipt)
    assert len(found) == 1, f"{len(found)} copies of the {receipt['org']} receipt under records/, expected 1"
    return found[0]


@pytest.fixture(params=RECEIPTS, ids=IDS)
def receipt(request):
    return request.param


class TestRows:
    """rows"""

    def test_one_new_row(self, receipt):
        one_row(receipt)

    def test_amount(self, receipt):
        row = one_row(receipt)
        assert parse_amount(row["amount"] or "") == receipt["amount"], f"amount {row['amount']!r}, expected {receipt['amount']:.2f}"

    def test_method(self, receipt):
        row = one_row(receipt)
        method = norm(row["method"] or "")
        words = ("check", "cheque") if receipt["method"] == "check" else ("card", "credit", "debit")
        assert any(w in method for w in words), f"method {row['method']!r}, expected a {receipt['method']}"


class TestDates:
    """dates"""

    def test_row_date_is_the_gift_date(self, receipt):
        row = one_row(receipt)
        assert parse_date(row["date"] or "") == receipt["date"], f"date {row['date']!r}, expected {receipt['date']}"

    def test_tax_year(self, receipt):
        row = one_row(receipt)
        assert (row["year"] or "").strip()[:4] == receipt["date"][:4], f"tax year {row['year']!r}, expected {receipt['date'][:4]}"

    def test_filed_in_the_gift_year_folder(self, receipt):
        path = one_file(receipt)
        assert path.parent == ROOT / "records" / receipt["date"][:4], f"filed in {path.parent.relative_to(ROOT)}, expected records/{receipt['date'][:4]}"

    def test_file_name_starts_with_the_gift_date(self, receipt):
        path = one_file(receipt)
        assert path.name.startswith(receipt["date"] + "_"), f"file name {path.name!r}, expected it to start {receipt['date']}_"


class TestFiling:
    """filing"""

    def test_filed_once_as_a_pdf(self, receipt):
        assert one_file(receipt).suffix.lower() == ".pdf"

    def test_named_like_the_others(self, receipt):
        assert one_file(receipt).name == rel_path(receipt["date"], receipt["org"]).split("/")[-1]

    def test_gone_from_the_inbox(self, receipt):
        one_file(receipt)  # moved, not just copied (and not deleted)
        assert receipt["sha"] not in inbox_hashes(), "the receipt is still in inbox/"

    def test_row_points_at_the_file(self, receipt):
        row = one_row(receipt)
        path = one_file(receipt)
        cell = (row["file"] or "").replace("\\", "/").strip()
        want = f"{path.parent.name}/{path.name}"
        assert cell.endswith(want), f"Receipt File {cell!r}, expected it to end {want}"


class TestIntegrity:
    """integrity"""

    def test_log_is_the_five_old_rows_plus_three_new(self):
        idx, rows = log_rows()
        assert idx is not None, "no giving-log.csv"
        old = [r for r in rows if r["date"] and any(
            parse_date(r["date"]) == e[0] and norm(r["org"] or "") == norm(e[1]) and parse_amount(r["amount"] or "") == float(e[2]) for e in EXISTING)]
        assert len(old) == len(EXISTING), "an earlier row was changed or removed"
        assert len(rows) == len(EXISTING) + len(RECEIPTS), f"{len(rows)} rows, expected {len(EXISTING) + len(RECEIPTS)}"

    def test_records_hold_the_five_old_pdfs_plus_three_new(self):
        base = ROOT / "records"
        files = [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"] if base.is_dir() else []
        assert len(files) == len(EXISTING) + len(RECEIPTS), f"{len(files)} PDFs under records/, expected {len(EXISTING) + len(RECEIPTS)}"
        for d, o, *_ in EXISTING:
            assert (ROOT / rel_path(d, o)).is_file(), f"{rel_path(d, o)} is gone"
