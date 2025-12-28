from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

import pdfplumber


DATE_LINE_RE = re.compile(
    r"^\s*(?P<m>\d{1,2})[/-](?P<d>\d{1,2})(?:[/-](?P<y>\d{2,4}))?\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<amount>[+\-\u2212]?\s*\$?\s*\(?\s*(?:\d[\d,]*\.\d+|\d[\d,]+|\.\d+)\s*\)?\s*(?:CR)?)\s*$"
)

CLOSING_DATE_RE = re.compile(
    r"Closing\s*Date\s*[:]?\s*(?P<m>\d{1,2})\/(?P<d>\d{1,2})\/(?P<y>\d{2,4})",
    re.IGNORECASE,
)


@dataclass
class Txn:
    yyyy_mm_dd: str
    description: str
    amount_display: str


def _stem(p: Path) -> str:
    return p.name[:-4] if p.name.lower().endswith(".pdf") else p.stem


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s{2,}", " ", s.strip())


def _strip_leading_amp(desc: str) -> str:
    return desc.lstrip("& ")


def _amount_to_value(amount_display: str) -> float:
    s_raw = amount_display.strip()
    s = s_raw.upper()

    has_cr = s.endswith("CR")
    if has_cr:
        s = s[:-2]

    s = s.replace(" ", "").replace("\u2212", "-")

    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]

    if s.startswith("-"):
        neg = True
        s = s[1:]
    if s.endswith("-"):
        neg = True
        s = s[:-1]

    s = s.replace("$", "").replace(",", "")

    if s.startswith("."):
        s = "0" + s

    s2 = re.sub(r"[^0-9.]", "", s)
    if s2 == "" or s2 == ".":
        val = 0.0
    else:
        parts = s2.split(".")
        if len(parts) > 2:
            s2 = parts[0] + "." + "".join(parts[1:])
        val = float(s2)

    if has_cr:
        return +val
    return -val if neg else +val


def _value_sign(val: float) -> int:
    return 1 if val > 1e-12 else (-1 if val < -1e-12 else 0)


def _find_closing_year(pdf: "pdfplumber.PDF") -> Tuple[int, int, int]:
    for page in pdf.pages:
        text = page.extract_text() or ""
        m = CLOSING_DATE_RE.search(text)
        if m:
            y = int(m.group("y"))
            if y < 100:
                y += 2000
            return (y, int(m.group("m")), int(m.group("d")))

    # fallback: best-effort
    from datetime import date
    today = date.today()
    return (today.year, today.month, today.day)


def _infer_full_date(m: int, d: int, closing_year: int, closing_month: int, y_from_line: int | None = None) -> str:
    if y_from_line is not None:
        return f"{y_from_line:04d}-{m:02d}-{d:02d}"
    year = closing_year - 1 if m > closing_month else closing_year
    return f"{year:04d}-{m:02d}-{d:02d}"


def _extract_activity_lines(pdf: "pdfplumber.PDF") -> List[str]:
    lines: List[str] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        if not text:
            continue
        page_lines = [ln.rstrip() for ln in text.splitlines()]
        in_section = False
        for ln in page_lines:
            ln_clean = ln.strip()
            if "ACCOUNT" in ln_clean.upper() and "ACTIVITY" in ln_clean.upper():
                in_section = True
                continue
            if in_section and ln_clean.isupper() and len(ln_clean) > 6 and "ACCOUNT" not in ln_clean:
                in_section = False
            if in_section:
                lines.append(ln)
    return lines


def _extract_candidate_lines_anywhere(pdf: "pdfplumber.PDF") -> List[str]:
    keep: List[str] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        for ln in text.splitlines() if text else []:
            s = ln.rstrip()
            if DATE_LINE_RE.match(s.strip()):
                keep.append(s)
    return keep


def _parse_transactions(lines: Iterable[str], closing_year: int, closing_month: int) -> List[Txn]:
    txns: List[Txn] = []
    for raw in lines:
        s = _normalize_spaces(raw)
        m = DATE_LINE_RE.match(s)
        if not m:
            continue

        mm = int(m.group("m"))
        dd = int(m.group("d"))

        yy = m.group("y")
        y_from_line = None
        if yy:
            y_from_line = int(yy)
            if y_from_line < 100:
                y_from_line += 2000

        desc = _strip_leading_amp(m.group("desc").strip())
        amt_disp = m.group("amount").strip()
        full_date = _infer_full_date(mm, dd, closing_year, closing_month, y_from_line=y_from_line)
        txns.append(Txn(full_date, desc, amt_disp))

    return txns


def extract_activity(*, pdf_path: Path, out_dir: Path) -> dict[str, Path]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _stem(pdf_path)

    summary_csv = out_dir / f"{stem}.summary.csv"
    activity_csv = out_dir / f"{stem}.activity.csv"
    monarch_csv = out_dir / f"{stem}.monarch.csv"

    with pdfplumber.open(pdf_path) as pdf:
        closing_year, closing_month, _ = _find_closing_year(pdf)
        lines = _extract_activity_lines(pdf)
        if not lines:
            lines = _extract_candidate_lines_anywhere(pdf)
        txns = _parse_transactions(lines, closing_year, closing_month)

    pos_count = neg_count = 0
    pos_sum = neg_sum = 0.0
    for t in txns:
        val = _amount_to_value(t.amount_display)
        sgn = _value_sign(val)
        if sgn > 0:
            pos_count += 1
            pos_sum += val
        elif sgn < 0:
            neg_count += 1
            neg_sum += val

    payments_count = neg_count
    payments_total = abs(neg_sum)
    purchases_count = pos_count
    purchases_total = -abs(pos_sum)

    with activity_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Amount", "AmountValue"])
        for t in txns:
            w.writerow([t.yyyy_mm_dd, t.description, t.amount_display, f"{_amount_to_value(t.amount_display):.2f}"])

    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Key", "Value"])
        w.writerow(["SourcePDF", str(pdf_path)])
        w.writerow(["Extractor", "chase"])
        w.writerow(["TransactionCount", str(len(txns))])
        w.writerow(["PaymentsAndCreditsCount", str(payments_count)])
        w.writerow(["PurchasesAndFeesCount", str(purchases_count)])
        w.writerow(["TotalPaymentsAndCredits", f"{payments_total:.2f}"])
        w.writerow(["TotalPurchasesAndFees", f"{purchases_total:.2f}"])

    with monarch_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Merchant", "Amount", "Category", "Account", "Notes"])
        for t in txns:
            w.writerow([t.yyyy_mm_dd, t.description, f"{_amount_to_value(t.amount_display):.2f}", "", "", ""])

    return {"summary": summary_csv, "activity": activity_csv, "monarch": monarch_csv}
