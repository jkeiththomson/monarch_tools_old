import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

import pdfplumber


def build_parser():
    parser = argparse.ArgumentParser(
        prog="monarch-tools",
        description="Monarch Money toolbox CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # --- hello ---
    p_hello = sub.add_parser("hello", help="Say hello")
    p_hello.set_defaults(func=cmd_hello)

    # --- name ---
    p_name = sub.add_parser("name", help="Print your name")
    p_name.add_argument("who", help="Name to greet")
    p_name.set_defaults(func=cmd_name)

    # --- help ---
    p_help = sub.add_parser("help", help="Show available commands and usage")
    p_help.set_defaults(func=cmd_help)

    # --- activity (real, positional) ---
    p_activity = sub.add_parser(
        "activity",
        help="Extract account activity from a statement PDF and write <stem>.activity.csv",
        description=(
            "Parse a statement PDF for the given account type and emit <stem>.activity.csv "
            "in the same folder as the PDF."
        ),
    )
    p_activity.add_argument(
        "account_type",
        choices=["chase", "citi", "amex"],
        help="Which account type parser to use."
    )
    p_activity.add_argument(
        "statement_pdf",
        help="Statement PDF path (absolute) or a path/filename under ./statements."
    )
    p_activity.add_argument(
        "--debug",
        action="store_true",
        help="Print diagnostic info (counts and a few sample lines)."
    )
    p_activity.set_defaults(func=cmd_activity)

    return parser


def cmd_hello(ns: argparse.Namespace) -> int:
    print("Hello from monarch-tools!")
    return 0


def cmd_name(ns: argparse.Namespace) -> int:
    print(f"Hello, {ns.who}!")
    return 0


def cmd_help(ns: argparse.Namespace) -> int:
    print("Available commands:")
    print("  hello                        Say hello")
    print("  name <who>                   Print your name")
    print("  activity <type> <pdf>        Extract account activity from a statement PDF")
    print("  help                         Show this help message")
    print("\nUse 'monarch-tools <command> --help' for detailed options.")
    return 0


# ------------------------------
# Activity extraction implementation
# ------------------------------

ACTIVITY_HEADERS = ("ACCOUNT ACTIVITY", "ACCOUNT ACTIVITY (CONTINUED)", "ACCOUNT  ACTIVITY")

# Robust date/amount matcher:
# - Allows .99 cents-only
# - Optional spaces/sign/$/parentheses
# - Optional trailing 'CR'
# - Accepts Unicode minus
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


def _infer_full_date(m: int, d: int, closing_year: int, closing_month: int, y_from_line: int | None = None) -> str:
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
            if in_section and ln_clean.isupper() and len(ln_clean) > 6 and "ACCOUNT" not in ln_clean:
                in_section = False
            if in_section:
                lines.append(ln)
    return lines


def _extract_candidate_lines_anywhere(pdf: "pdfplumber.PDF") -> List[str]:
    """Fallback: scan all page lines and keep those that look like 'MM/DD ... amount'."""
    keep: List[str] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        for ln in (text.splitlines() if text else []):
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
        amt_disp = amt_disp.replace(" $", " $").replace("$ ", "$").replace(" )", ")").replace("( ", "(").replace("  ", " ")
        full_date = _infer_full_date(mm, dd, closing_year, closing_month, y_from_line=y_from_line)
        txns.append(Txn(full_date, desc, amt_disp))
    return txns


def _write_activity_csv(out_path: Path, txns: List[Txn], pos_label: str, neg_label: str) -> Tuple[int, int, float, float]:
    # pos = > 0  (payments/credits)
    # neg = < 0  (purchases/fees)
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

        # Footer summary using statement convention mapping (Option A)
        w.writerow([])
        w.writerow([f"{pos_label} (count)", "", str(pos_count)])
        w.writerow([f"{neg_label} (count)", "", str(neg_count)])
        w.writerow([f"Total {pos_label}", "", f"{pos_sum:.2f}"])
        w.writerow([f"Total {neg_label}", "", f"{neg_sum:.2f}"])

    return pos_count, neg_count, pos_sum, neg_sum


def _resolve_statements_pdf(arg_value: str) -> Path | None:
    """
    Resolve a PDF path as either:
      1) An absolute filesystem path to a .pdf file, or
      2) A relative path/filename under <project_root>/statements.
    """
    p = Path(arg_value).expanduser()
    if p.is_absolute() and p.suffix.lower() == ".pdf" and p.is_file():
        return p

    project_root = Path(__file__).resolve().parents[2]  # .../monarch-tools
    statements_dir = project_root / "statements"
    candidate = statements_dir / arg_value

    if candidate.suffix.lower() == ".pdf" and candidate.is_file():
        return candidate

    target_name = Path(arg_value).name
    for q in statements_dir.rglob("*.pdf"):
        if q.name == target_name:
            return q
    return None


def cmd_activity(ns: argparse.Namespace) -> int:
    pdf_path = _resolve_statements_pdf(ns.statement_pdf)
    if pdf_path is None:
        print("Error: could not find the PDF under ./statements (checked relative path and filename search).")
        return 2

    out_path = pdf_path.with_suffix("")
    out_path = out_path.with_name(out_path.name.replace(".statement", ""))
    out_path = out_path.with_name(f"{out_path.name}.activity.csv")

    with pdfplumber.open(pdf_path) as pdf:
        closing_year, closing_month, _ = _find_closing_year(pdf)
        lines = _extract_activity_lines(pdf)
        if ns.debug:
            print(f"[debug] lines from ACTIVITY sections: {len(lines)}")
        if not lines:
            lines = _extract_candidate_lines_anywhere(pdf)
            if ns.debug:
                print(f"[debug] fallback lines from anywhere: {len(lines)}")
        txns = _parse_transactions(lines, closing_year, closing_month)
        if ns.debug:
            print(f"[debug] parsed transactions: {len(txns)}")
            for sample in txns[:5]:
                print(f"[debug] sample -> {sample.yyyy_mm_dd} | {sample.description[:60]} | {sample.amount_display}")

    # Map signs to PDF labels (Option A)
    # > 0 -> Payments and credits
    # < 0 -> Purchases and fees
    if ns.account_type in ("chase", "citi", "amex"):
        pos_label = "Payments and credits"   # > 0
        neg_label = "Purchases and fees"     # < 0
    else:
        pos_label = "Positive amounts"
        neg_label = "Negative amounts"

    pos_count, neg_count, pos_sum, neg_sum = _write_activity_csv(out_path, txns, pos_label, neg_label)

    print(f"Wrote: {out_path}")
    print(f"{pos_label} (count): {pos_count}")
    print(f"{neg_label} (count): {neg_count}")
    print(f"Total {pos_label}: {pos_sum:.2f}")
    print(f"Total {neg_label}: {neg_sum:.2f}")
    return 0


def main():
    parser = build_parser()
    ns = parser.parse_args()
    return ns.func(ns)


if __name__ == "__main__":
    raise SystemExit(main())