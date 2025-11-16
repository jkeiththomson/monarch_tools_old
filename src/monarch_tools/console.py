import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pdfplumber


def build_parser():
    parser = argparse.ArgumentParser(
        prog="monarch_tools",
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
        help="Which account type parser to use.",
    )
    p_activity.add_argument(
        "statement_pdf",
        help="Statement PDF path (absolute) or a path/filename under ./statements.",
    )
    p_activity.add_argument(
        "--debug",
        action="store_true",
        help="Print diagnostic info (counts and a few sample lines).",
    )
    p_activity.set_defaults(func=cmd_activity)

    # --- categorize ---
    p_cat = sub.add_parser(
        "categorize",
        help="Apply merchant/category rules to activity CSV and write <stem>.monarch.csv",
        description=(
            "Read categories.txt, rules.json, and an activity.csv file and emit a Monarch-"
            "compatible CSV with Date,Payee,Category,Notes,Amount. The rules and categories"
            " files are updated iteratively as new merchants and categories are discovered."
        ),
    )
    p_cat.add_argument(
        "categories",
        help="Path to categories.txt (master list of categories)",
    )
    p_cat.add_argument(
        "rules",
        help="Path to rules.json (merchant → category rules)",
    )
    p_cat.add_argument(
        "activity",
        help="Path to an activity.csv file or a directory containing *.activity.csv files.",
    )
    p_cat.add_argument(
        "--no-update-rules",
        action="store_true",
        help="Do not modify categories.txt or rules.json; just apply existing rules.",
    )
    p_cat.set_defaults(func=cmd_categorize)

    return parser



def cmd_hello(ns: argparse.Namespace) -> int:
    print("Hello from monarch_tools!")
    return 0


def cmd_name(ns: argparse.Namespace) -> int:
    print(f"Hello, {ns.who}!")
    return 0


def cmd_help(ns: argparse.Namespace) -> int:
    print("Available commands:")
    print("  hello                        Say hello")
    print("  name <who>                   Print your name")
    print("  activity <type> <pdf>        Extract account activity from a statement PDF")
    print("  categorize                   Categorize activity.csv into Monarch CSV")
    print("  help                         Show this help message")
    print("\nUse 'monarch_tools <command> --help' for detailed options.")
    return 0

# ------------------------------
# Activity extraction implementation
# ------------------------------

ACTIVITY_HEADERS = (
    "ACCOUNT ACTIVITY",
    "ACCOUNT ACTIVITY (CONTINUED)",
    "ACCOUNT  ACTIVITY",
)

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

def _resolve_statements_pdf(arg_value: str) -> Path | None:
    """
    Resolve a PDF path as either:
      1) An absolute filesystem path to a .pdf file, or
      2) A relative path/filename under <project_root>/statements.
    """
    p = Path(arg_value).expanduser()
    if p.is_absolute() and p.suffix.lower() == ".pdf" and p.is_file():
        return p

    project_root = Path(__file__).resolve().parents[2]  # .../monarch_tools
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
        print(
            "Error: could not find the PDF under ./statements (checked relative path and filename search)."
        )
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
                print(
                    f"[debug] sample -> {sample.yyyy_mm_dd} | {sample.description[:60]} | {sample.amount_display}"
                )

    # Map signs to PDF labels (Option A)
    # > 0 -> Payments and credits
    # < 0 -> Purchases and fees
    if ns.account_type in ("chase", "citi", "amex"):
        pos_label = "Payments and credits"  # > 0
        neg_label = "Purchases and fees"  # < 0
    else:
        pos_label = "Positive amounts"
        neg_label = "Negative amounts"

    pos_count, neg_count, pos_sum, neg_sum = _write_activity_csv(
        out_path, txns, pos_label, neg_label
    )

    print(f"Wrote: {out_path}")
    print(f"{pos_label} (count): {pos_count}")
    print(f"{neg_label} (count): {neg_count}")
    print(f"Total {pos_label}: {pos_sum:.2f}")
    print(f"Total {neg_label}: {neg_sum:.2f}")
    return 0

# ------------------------------
# Categorize implementation
# ------------------------------


def _load_categories(path: Path) -> List[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        cats = [line.strip() for line in f if line.strip()]
    # de-duplicate while preserving order
    seen: set[str] = set()
    result: List[str] = []
    for c in cats:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _save_categories(path: Path, categories: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort for stable, readable file
    unique_sorted = sorted({c for c in categories if c})
    with path.open("w", encoding="utf-8", newline="") as f:
        for c in unique_sorted:
            f.write(c + "\n")


def _load_rules(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"rules_version": 1, "patterns": [], "exact": {}}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("rules_version", 1)
    data.setdefault("patterns", [])
    data.setdefault("exact", {})
    return data


def _save_rules(path: Path, rules: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort exact keys for readability
    exact = rules.get("exact") or {}
    sorted_exact = {k: exact[k] for k in sorted(exact.keys(), key=str.lower)}
    rules_to_write = {
        "rules_version": int(rules.get("rules_version", 1)),
        "patterns": list(rules.get("patterns") or []),
        "exact": sorted_exact,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(rules_to_write, f, indent=2, sort_keys=False)
        f.write("\n")


def _compile_pattern(entry: Dict[str, object]) -> re.Pattern:
    flags_str = str(entry.get("flags", ""))
    flags = 0
    for ch in flags_str:
        if ch.lower() == "i":
            flags |= re.IGNORECASE
        elif ch.lower() == "m":
            flags |= re.MULTILINE
        elif ch.lower() == "s":
            flags |= re.DOTALL
        elif ch.lower() == "x":
            flags |= re.VERBOSE
    pattern = entry.get("pattern", "")
    return re.compile(pattern, flags)


def _detect_columns(header: List[str]) -> Dict[str, int]:
    """Detect key columns in a flexible activity CSV.

    Returns mapping from logical name -> index:
      - date
      - amount
      - payee   (merchant/payee/description)
      - notes   (optional)
      - category (optional)
    """
    normalized = [h.strip().lower() for h in header]

    def find_any(candidates: Iterable[str]) -> int:
        for i, name in enumerate(normalized):
            for cand in candidates:
                if name == cand:
                    return i
                # Loose match: ignore spaces and some punctuation
                if name.replace(" ", "") == cand.replace(" ", ""):
                    return i
        return -1

    date_idx = find_any(
        ["date", "transaction date", "posted date", "post date", "statement date"]
    )
    amount_idx = find_any(
        ["amount", "transaction amount", "charge amount", "payment amount"]
    )
    payee_idx = find_any(
        ["merchant", "payee", "description", "transaction description"]
    )
    notes_idx = find_any(["notes", "note", "memo", "mem", "details"])
    category_idx = find_any(["category", "categories"])

    if date_idx < 0 or amount_idx < 0 or payee_idx < 0:
        raise ValueError(
            "Could not detect required columns. Need Date, Amount, and a Merchant/Payee/Description."
        )

    return {
        "date": date_idx,
        "amount": amount_idx,
        "payee": payee_idx,
        "notes": notes_idx,
        "category": category_idx,
    }


def _iter_activity_files(path: Path) -> Iterable[Path]:
    if path.is_dir():
        for p in sorted(path.glob("*.activity.csv")):
            if p.is_file():
                yield p
    else:
        if path.suffix.lower() == ".csv":
            yield path
        else:
            raise ValueError(f"activity path {path} is not a .csv file or directory")


def _apply_rules_to_row(
    payee_raw: str,
    incoming_category: Optional[str],
    rules: Dict[str, object],
    categories: List[str],
    allow_rule_updates: bool,
) -> Tuple[str, str, List[str], List[str]]:
    """Return (normalized_payee, final_category, new_categories, new_stub_merchants)."""
    payee = (payee_raw or "").strip()
    if not payee:
        payee = "Unknown"

    new_categories: List[str] = []
    new_stub_merchants: List[str] = []

    patterns = list(rules.get("patterns") or [])
    exact_rules: Dict[str, Dict[str, object]] = dict(rules.get("exact") or {})

    # Build case-insensitive lookup for exact rules
    exact_lookup = {k.lower(): (k, v) for k, v in exact_rules.items()}

    def ensure_category(cat: str) -> None:
        if cat and cat not in categories:
            categories.append(cat)
            new_categories.append(cat)

    # 1) If CSV already has a category, that wins and we update rules
    if incoming_category:
        cat = incoming_category.strip()
        if cat:
            ensure_category(cat)
            if allow_rule_updates:
                # refresh or create exact rule
                key_lower = payee.lower()
                if key_lower in exact_lookup:
                    canonical, entry = exact_lookup[key_lower]
                    entry["category"] = cat
                    exact_rules[canonical] = entry
                else:
                    exact_rules[payee] = {"category": cat}
            return payee, cat, new_categories, new_stub_merchants

    # 2) Try regex patterns (first match wins)
    for entry in patterns:
        try:
            pat = _compile_pattern(entry)
        except re.error:
            continue
        if pat.search(payee):
            cat = str(entry.get("category") or "").strip()
            normalized = str(entry.get("normalized") or "") or payee
            if cat:
                ensure_category(cat)
                return normalized, cat, new_categories, new_stub_merchants
            return normalized, "Uncategorized", new_categories, new_stub_merchants

    # 3) Try exact rules
    key_lower = payee.lower()
    if key_lower in exact_lookup:
        canonical, entry = exact_lookup[key_lower]
        cat = str(entry.get("category") or "").strip()
        if cat:
            ensure_category(cat)
            return canonical, cat, new_categories, new_stub_merchants
        # explicit stub: merchant known but not yet categorized
        return canonical, "Uncategorized", new_categories, new_stub_merchants

    # 4) New merchant: create stub exact rule with null category
    if allow_rule_updates:
        exact_rules[payee] = {"category": None}
        new_stub_merchants.append(payee)

    # Merge updated exact back into rules
    rules["exact"] = exact_rules

    ensure_category("Uncategorized")
    return payee, "Uncategorized", new_categories, new_stub_merchants

def cmd_categorize(ns: argparse.Namespace) -> int:
    categories_path = Path(ns.categories)
    rules_path = Path(ns.rules)
    activity_path = Path(ns.activity)

    categories = _load_categories(categories_path)
    rules = _load_rules(rules_path)

    allow_updates = not getattr(ns, "no_update_rules", False)

    all_new_categories: List[str] = []
    all_new_stub_merchants: set[str] = set()
    # Track all rows that end up Uncategorized, for a review report
    uncategorized_counts: Dict[str, int] = {}

    try:
        activity_files = list(_iter_activity_files(activity_path))
    except ValueError as e:
        print(f"Error: {e}")
        return 2
    if not activity_files:
        print(f"No .activity.csv files found under {activity_path}")
        return 2

    for act_file in activity_files:
        with act_file.open("r", encoding="utf-8", newline="") as f_in:
            reader = csv.reader(f_in)
            try:
                header = next(reader)
            except StopIteration:
                print(f"Warning: {act_file} is empty; skipping.")
                continue

            try:
                cols = _detect_columns(header)
            except ValueError as e:
                print(f"Error in {act_file}: {e}")
                return 2

            out_rows: List[List[str]] = []
            out_header = ["Date", "Payee", "Category", "Notes", "Amount"]
            out_rows.append(out_header)

            for row in reader:
                if not any(row):
                    continue
                # protect against short rows
                row_extended = row + [""] * max(0, max(cols.values()) + 1 - len(row))

                date_val = row_extended[cols["date"]].strip()
                amount_val = row_extended[cols["amount"]].strip()
                payee_raw = row_extended[cols["payee"]].strip()

                notes_val = ""
                if cols["notes"] >= 0:
                    notes_val = row_extended[cols["notes"]].strip()

                incoming_category = ""
                if cols["category"] >= 0:
                    incoming_category = row_extended[cols["category"]].strip()

                normalized_payee, final_category, new_cats, new_stubs = _apply_rules_to_row(
                    payee_raw,
                    incoming_category,
                    rules,
                    categories,
                    allow_updates,
                )
                all_new_categories.extend(new_cats)
                for m in new_stubs:
                    all_new_stub_merchants.add(m)

                if final_category == "Uncategorized":
                    uncategorized_counts[normalized_payee] = uncategorized_counts.get(normalized_payee, 0) + 1

                # Build Notes column
                notes_parts: List[str] = []
                if notes_val:
                    notes_parts.append(notes_val)
                if normalized_payee != payee_raw and payee_raw:
                    notes_parts.append(f"Original: {payee_raw}")
                notes_field = " | ".join(notes_parts)

                out_row = [date_val, normalized_payee, final_category, notes_field, amount_val]
                out_rows.append(out_row)

        # Write Monarch CSV next to the activity file
        monarch_path = act_file.with_suffix(".monarch.csv")
        monarch_path.parent.mkdir(parents=True, exist_ok=True)
        with monarch_path.open("w", encoding="utf-8", newline="") as f_out:
            writer = csv.writer(f_out)
            writer.writerows(out_rows)
        print(f"Wrote {monarch_path}")

        # Also keep per-activity snapshots of categories and rules
        if allow_updates:
            local_cat = act_file.with_suffix(".categories.txt")
            local_rules = act_file.with_suffix(".rules.json")
            _save_categories(local_cat, categories)
            _save_rules(local_rules, rules)
            print(f"Updated local {local_cat} and {local_rules}")

    # After processing all files, update master categories/rules
    if allow_updates:
        _save_categories(categories_path, categories)
        _save_rules(rules_path, rules)
        print(f"Updated master {categories_path} and {rules_path}")

    # Fold in any merchants from rules.json that still have no category at all
    exact_rules: Dict[str, Dict[str, object]] = dict(rules.get("exact") or {})
    for name, entry in exact_rules.items():
        if entry.get("category") is None and name not in uncategorized_counts:
            uncategorized_counts[name] = 0

    # Summary
    unique_new_categories = sorted(set(all_new_categories))
    if unique_new_categories:
        print("\nNew categories discovered:")
        for c in unique_new_categories:
            print(f"  {c}")

    if all_new_stub_merchants:
        print("\nNew merchants added as stubs (category=null in rules.json):")
        for m in sorted(all_new_stub_merchants, key=str.lower):
            print(f"  {m}")

    # Build a review list of all merchants that are still effectively uncategorized
    if uncategorized_counts:
        print("\nMerchants still Uncategorized (review these in rules.json):")
        # Sort by frequency (desc) then name
        unresolved = sorted(
            uncategorized_counts.items(),
            key=lambda kv: (-kv[1], kv[0].lower()),
        )
        for name, count in unresolved:
            print(f"  {name}  (count this run: {count})")

        # Also write a CSV next to rules.json for spreadsheet review
        review_path = rules_path.with_suffix(".review.csv")
        review_rows: List[List[str]] = [["Merchant", "CurrentCategory", "CountInThisRun"]]
        for name, count in unresolved:
            entry = exact_rules.get(name)
            current_cat = ""
            if entry is not None:
                current_cat = (entry.get("category") or "") or ""
            elif count > 0:
                current_cat = "Uncategorized"
            review_rows.append([name, current_cat, str(count)])

        review_path.parent.mkdir(parents=True, exist_ok=True)
        with review_path.open("w", encoding="utf-8", newline="") as f_rev:
            writer = csv.writer(f_rev)
            writer.writerows(review_rows)
        print(f"\nWrote review CSV: {review_path}")

    return 0


def main():
    parser = build_parser()
    ns = parser.parse_args()
    return ns.func(ns)


if __name__ == "__main__":
    raise SystemExit(main())
