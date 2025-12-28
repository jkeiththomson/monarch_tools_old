"""Chase credit card statement activity extractor.

Ported from the original console-based implementation that already produced
correct counts and totals for Payments/Credits vs Purchases/Fees.

This module exposes a single entry point:

    extract_activity(pdf_path: str, out_dir: str) -> str

which is used by the `activity` command via:

    monarch_tools.extractors.chase.extract_activity
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

import csv
import re

import pdfplumber



# --- Parsing primitives copied from the original implementation ---


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
    amount_display: str  # Keep original formatting incl. $, commas, (), sign



def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s{2,}", " ", s.strip())





def _strip_leading_amp(desc: str) -> str:
    return desc.lstrip("& ")





def _amount_to_value(amount_display: str) -> float:
    """
    Convert display string (may include $, spaces, commas, parentheses, sign, CR) to numeric value.
    Rules:
      - (x) is negative
      - Leading/trailing minus → negative
      - 'CR' means credit → positive (overrides minus/parentheses)
      - Accept Unicode minus (−)
      - Accept cents-only like .99 or $.99
    """
    s_raw = amount_display.strip()
    s = s_raw.upper()

    # Detect and strip trailing CR (credit)
    has_cr = s.endswith("CR")
    if has_cr:
        s = s[:-2]

    # Normalize spaces
    s = s.replace(" ", "")

    # Normalize unicode minus to ASCII
    s = s.replace("\u2212", "-")

    # Parentheses → negative
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]

    # Leading/trailing minus
    if s.startswith("-"):
        neg = True
        s = s[1:]
    if s.endswith("-"):
        neg = True
        s = s[:-1]

    # Strip $, commas
    s = s.replace("$", "").replace(",", "")

    # Handle leading dot like .99
    if s.startswith("."):
        s = "0" + s

    # Keep only digits and dot now
    s2 = re.sub(r"[^0-9.]", "", s)
    if s2 == "" or s2 == ".":
        # Fallback: nothing numeric — treat as zero
        val = 0.0
    else:
        # Ensure there's at most one dot; if multiple, keep first two segments
        parts = s2.split(".")
        if len(parts) > 2:
            s2 = parts[0] + "." + "".join(parts[1:])
        val = float(s2)

    # Apply sign: CR forces positive (payments/credits)
    if has_cr:
        return +val
    return -val if neg else +val





def _value_sign(val: float) -> int:
    return 1 if val > 1e-12 else (-1 if val < -1e-12 else 0)





def _find_closing_year(pdf: "pdfplumber.PDF") -> Tuple[int, int, int]:
    """Return (year, month, day) for Closing Date.
    Strategy:
      1) Prefer 'Closing Date'
      2) Else, use max year seen on page 1
      3) Else, fall back to today's year
    """
    for page in pdf.pages:
        text = page.extract_text() or ""
        m = CLOSING_DATE_RE.search(text)
        if m:
            y = int(m.group("y"))
            if y < 100:
                y += 2000
            return (y, int(m.group("m")), int(m.group("d")))

    if pdf.pages:
        first = pdf.pages[0].extract_text() or ""
        candidates = re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", first)
        if candidates:
            years = []
            for mm, dd, yy in candidates:
                y = int(yy)
                if y < 100:
                    y += 2000
                years.append(y)
            if years:
                y = max(years)
                mm, dd, _ = candidates[0]
                return (y, int(mm), int(dd))

    from datetime import date

    today = date.today()
    return (today.year, today.month, today.day)





def _infer_full_date(
    m: int,
    d: int,
    closing_year: int,
    closing_month: int,
    y_from_line: int | None = None,
) -> str:
    """Return YYYY-MM-DD, preferring a year present on the line."""
    if y_from_line is not None:
        return f"{y_from_line:04d}-{m:02d}-{d:02d}"
    year = closing_year - 1 if m > closing_month else closing_year
    return f"{year:04d}-{m:02d}-{d:02d}"





def _extract_activity_lines(pdf: "pdfplumber.PDF") -> List[str]:
    """Collect lines within ACCOUNT ACTIVITY sections across all pages."""
    lines: List[str] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        if not text:
            continue
        page_lines = [ln.rstrip() for ln in text.splitlines()]

        in_section = False
        for ln in page_lines:
            ln_clean = ln.strip()
            # header detection (tolerant)
            if "ACCOUNT" in ln_clean.upper() and "ACTIVITY" in ln_clean.upper():
                in_section = True
                continue
            # heuristic end
            if (
                in_section
                and ln_clean.isupper()
                and len(ln_clean) > 6
                and "ACCOUNT" not in ln_clean
            ):
                in_section = False
            if in_section:
                lines.append(ln)
    return lines





def _extract_candidate_lines_anywhere(pdf: "pdfplumber.PDF") -> List[str]:
    """Fallback: scan all page lines and keep those that look like 'MM/DD ... amount'."""
    keep: List[str] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        for ln in text.splitlines() if text else []:
            s = ln.rstrip()
            if DATE_LINE_RE.match(s.strip()):
                keep.append(s)
    return keep





def _parse_transactions(
    lines: Iterable[str], closing_year: int, closing_month: int
) -> List[Txn]:
    txns: List[Txn] = []
    for raw in lines:
        s = _normalize_spaces(raw)
        m = DATE_LINE_RE.match(s)
        if not m:
            continue
        mm = int(m.group("m"))
        dd = int(m.group("d"))
        # Optional year on the line
        yy = m.group("y")
        y_from_line = None
        if yy:
            y_from_line = int(yy)
            if y_from_line < 100:
                y_from_line += 2000
        desc = _strip_leading_amp(m.group("desc").strip())
        amt_disp = m.group("amount").strip()
        # Normalize a few spaced formats for the display copy (we keep the original semantics)
        amt_disp = (
            amt_disp.replace(" $", " $")
            .replace("$ ", "$")
            .replace(" )", ")")
            .replace("( ", "(")
            .replace("  ", " ")
        )
        full_date = _infer_full_date(
            mm, dd, closing_year, closing_month, y_from_line=y_from_line
        )
        txns.append(Txn(full_date, desc, amt_disp))
    return txns




def _write_activity_csv(
    out_path: Path, txns: List[Txn], pos_label: str, neg_label: str
) -> Tuple[int, int, float, float]:
    # pos bucket: > 0 values (as parsed)
    # neg bucket: < 0 values (as parsed)
    pos_count = neg_count = 0
    pos_sum = neg_sum = 0.0

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Amount"])
        for t in txns:
            val = _amount_to_value(t.amount_display)
            sgn = _value_sign(val)
            if sgn > 0:
                pos_count += 1
                pos_sum += val
            elif sgn < 0:
                neg_count += 1
                neg_sum += val
            w.writerow([t.yyyy_mm_dd, t.description, t.amount_display])

        w.writerow([])

        # Reinterpret the buckets for the summary:
        # - neg_* are PAYMENTS / CREDITS → positive total
        # - pos_* are PURCHASES / FEES   → negative total
        payments_count = neg_count
        payments_total = abs(neg_sum)

        purchases_count = pos_count
        purchases_total = -abs(pos_sum)

        w.writerow([f"{pos_label} (count)", "", str(payments_count)])
        w.writerow([f"{neg_label} (count)", "", str(purchases_count)])
        w.writerow([f"Total {pos_label}", "", f"{payments_total:.2f}"])
        w.writerow([f"Total {neg_label}", "", f"{purchases_total:.2f}"])

    return payments_count, purchases_count, payments_total, purchases_total



def extract_activity(pdf_path: str, out_dir: str) -> str:
    """
    Extract Chase account activity from a PDF into an activity CSV.

    Parameters
    ----------
    pdf_path:
        Path to the Chase PDF statement.
    out_dir:
        Directory where the .activity.csv should be written.

    Returns
    -------
    str
        The filesystem path of the written CSV, as a string.
    """
    pdf_path_obj = Path(pdf_path)
    if not pdf_path_obj.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path_obj}")

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    # Match the naming used by the new activity command:
    #   <out_dir>/<pdf_stem>.activity.csv
    out_path = out_dir_path / f"{pdf_path_obj.stem}.activity.csv"

    with pdfplumber.open(pdf_path_obj) as pdf:
        closing_year, closing_month, _ = _find_closing_year(pdf)
        lines = _extract_activity_lines(pdf)
        if not lines:
            # Fallback: be more permissive and look anywhere in the PDF.
            lines = _extract_candidate_lines_anywhere(pdf)

        txns = _parse_transactions(lines, closing_year, closing_month)

    # Use the same bucket labels as the original implementation.
    pos_label = "Payments and credits"
    neg_label = "Purchases and fees"

    payments_count, purchases_count, payments_total, purchases_total = _write_activity_csv(
        out_path, txns, pos_label, neg_label
    )

    print(f"[chase extractor] Wrote activity CSV with {len(txns)} rows: {out_path}")
    print(f"[chase extractor] {pos_label} (count): {payments_count}")
    print(f"[chase extractor] {neg_label} (count): {purchases_count}")
    print(f"[chase extractor] Total {pos_label}: {payments_total:.2f}")
    print(f"[chase extractor] Total {neg_label}: {purchases_total:.2f}")

    return str(out_path)
