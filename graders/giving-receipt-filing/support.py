"""Ground truth and helpers for the giving-receipt-filing hidden tests.

Everything here is fictional. The receipts are generated, byte for byte, by make_pdf(), so the tests
can recognise a filed PDF by its hash wherever the model put it or whatever it renamed it to. build.py
writes the fixtures, the reference solution and the calibration fixtures from this same data.
"""
import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the grading copy: giving-log.csv, records/ and inbox/ as the model left them
HEADER = ["Date", "Organization", "Amount", "Method", "Tax Year", "Receipt File"]


def make_pdf(lines):
    """A minimal one-page PDF (Helvetica, uncompressed so any text extractor reads it), deterministic."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = ["BT", "/F1 12 Tf", "16 TL", "72 740 Td"]
    for line in lines:
        content.append(f"({esc(line)}) Tj T*")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def slug(org):
    return re.sub(r"[^A-Za-z0-9]+", "-", org).strip("-")


def rel_path(date, org):
    return f"records/{date[:4]}/{date}_{slug(org)}.pdf"


# Already filed and logged: they show the layout, the naming and the column conventions
EXISTING = [
    ("2024-03-10", "Lakeside Animal Rescue", "75.00", "Card", ["Lakeside Animal Rescue", "Donation Receipt", "", "Date of gift: March 10, 2024", "Amount: $75.00", "Paid by: credit card"]),
    ("2024-12-24", "Maple Street Community Church", "300.00", "Check", ["Maple Street Community Church", "Contribution Receipt", "", "Date of gift: December 24, 2024", "Amount: $300.00", "Paid by: check no. 1141"]),
    ("2025-02-14", "Northfield Library Friends", "50.00", "Card", ["Northfield Library Friends", "Thank you for your donation", "", "Date of gift: February 14, 2025", "Amount: $50.00", "Paid by: debit card"]),
    ("2025-06-01", "Lakeside Animal Rescue", "100.00", "Card", ["Lakeside Animal Rescue", "Donation Receipt", "", "Date of gift: June 1, 2025", "Amount: $100.00", "Paid by: credit card"]),
    ("2025-11-27", "Maple Street Community Church", "200.00", "Check", ["Maple Street Community Church", "Contribution Receipt", "", "Date of gift: November 27, 2025", "Amount: $200.00", "Paid by: check no. 1163"]),
]

# The new receipts in inbox/. The file names are decoys: none says anything true about the gift date.
# key: what the Organization cell must contain (lower case, letters and digits only)
RECEIPTS = [
    {   # Acknowledgment letter written after New Year; the gift itself was made on the last day of 2025.
        "id": "pantry", "inbox": "receipt-scan-20260104.pdf", "key": "hopeharbor", "org": "Hope Harbor Food Pantry",
        "date": "2025-12-31", "amount": 180.00, "method": "card",
        "lines": ["Hope Harbor Food Pantry", "1200 Quay Street, Marlowe", "", "January 4, 2026", "",
                  "Dear friend,", "",
                  "Thank you for your generous gift of $180.00, received on",
                  "December 31, 2025 and charged to your credit card.", "",
                  "Your gift will put 360 meals on tables this winter.", "",
                  "No goods or services were provided in exchange for this gift.",
                  "Hope Harbor Food Pantry is a 501(c)(3) organization. EIN 00-0000001."],
    },
    {   # First gift of the new year, and the first file for the 2026 folder; the letter quotes last year's total too.
        "id": "radio", "inbox": "donation.pdf", "key": "riverbendpublicradio", "org": "Riverbend Public Radio",
        "date": "2026-01-02", "amount": 60.00, "method": "card",
        "lines": ["Riverbend Public Radio", "Member Services", "", "RECEIPT", "",
                  "Date of gift: January 2, 2026", "Gift: $60.00 monthly sustainer (card on file)", "",
                  "Your giving to Riverbend in 2025 totaled $660.00.", "",
                  "Thank you for keeping public radio independent.",
                  "No goods or services were provided in exchange for this gift."],
    },
    {   # A reissued statement for an old gift, printed this year; same church as two earlier rows.
        "id": "church", "inbox": "maple-st-statement.pdf", "key": "maplestreetcommunitychurch", "org": "Maple Street Community Church",
        "date": "2024-11-17", "amount": 250.00, "method": "check",
        "lines": ["Maple Street Community Church", "Reissued contribution statement", "",
                  "Statement printed: March 2, 2026", "",
                  "This copy replaces the receipt mailed to you in 2024.", "",
                  "Date of gift: November 17, 2024", "Amount: $250.00", "Paid by: check no. 1129", "",
                  "Pledge balance remaining: $500.00 (not part of this gift).",
                  "No goods or services were provided in exchange for this gift."],
    },
]
for r in RECEIPTS:
    r["pdf"] = make_pdf(r["lines"])
    r["sha"] = hashlib.sha256(r["pdf"]).hexdigest()
    r["rel"] = rel_path(r["date"], r["org"])
for e in EXISTING:
    pass

EXISTING_ROWS = [[d, o, a, m, d[:4], rel_path(d, o)] for d, o, a, m, _ in EXISTING]


# -------- reading what the model left --------

def read_log():
    path = ROOT / "giving-log.csv"
    if not path.is_file():
        return None
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.reader(fh))


def norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def column(header, word):
    for i, name in enumerate(header):
        if word in norm(name):
            return i
    return None


def parse_date(text):
    text = str(text).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def parse_amount(text):
    try:
        return round(float(re.sub(r"[^0-9.\-]", "", str(text))), 2)
    except ValueError:
        return None


def log_rows():
    """(header, [row dicts keyed by column role]) with rows already in the log before the run removed."""
    rows = read_log()
    if not rows:
        return None, []
    header, body = rows[0], rows[1:]
    idx = {"date": column(header, "date"), "org": column(header, "organ"), "amount": column(header, "amount"),
           "method": column(header, "method"), "year": column(header, "year"), "file": column(header, "file")}
    out = []
    for raw in body:
        if not any(c.strip() for c in raw):
            continue
        out.append({k: (raw[i].strip() if i is not None and i < len(raw) else None) for k, i in idx.items()})
    return idx, out


def is_original(row):
    for d, o, a, m, _ in EXISTING:
        if parse_date(row["date"] or "") == d and norm(row["org"] or "") == norm(o) and parse_amount(row["amount"] or "") == float(a):
            return True
    return False


def new_rows(receipt):
    idx, rows = log_rows()
    return [r for r in rows if not is_original(r) and receipt["key"] in norm(r["org"] or "")]


def filed(receipt):
    """Paths under records/ whose bytes are exactly this receipt."""
    base = ROOT / "records"
    if not base.is_dir():
        return []
    return [p for p in base.rglob("*") if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == receipt["sha"]]


def inbox_hashes():
    base = ROOT / "inbox"
    if not base.is_dir():
        return set()
    return {hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob("*") if p.is_file()}
