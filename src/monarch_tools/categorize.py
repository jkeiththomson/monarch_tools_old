# src/monarch_tools/categorize.py
from __future__ import annotations
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Tuple

MONARCH_COLUMNS = ["Date", "Payee", "Category", "Notes", "Amount"]


@dataclass
class RuleMatch:
    payee_out: str
    category: Optional[str]  # can be None for stub rules


@dataclass
class RuleSet:
    patterns: List[Dict]
    exact: Dict[str, Dict]  # case-insensitive keys in logic


def run_categorize(
    categories_path: str, rules_path: str, inputs: List[str], out_dir: Optional[str]
) -> int:
    cats = load_categories(Path(categories_path))
    rules = load_rules(Path(rules_path))

    files = collect_inputs([Path(p) for p in inputs])
    if not files:
        print("No input CSVs found (looking for *_activity.csv under provided dirs).")
        return 2

    updated_merchants: Dict[
        str, str
    ] = {}  # merchant -> category decided (for exact rules)
    created_outputs: List[Path] = []

    for f in files:
        rows = read_activity_csv(f)
        out_rows, file_updates = transform_rows(rows, rules, cats)
        updated_merchants.update(file_updates)
        out_csv = write_monarch_csv(f, out_rows, out_dir)
        created_outputs.append(out_csv)
        print(f"Wrote: {out_csv}")

    # Update categories.txt (sorted, dedup)
    save_categories(Path(categories_path), cats)

    # Update rules.json (respect regex order; add/refresh exact rules)
    update_rules_exact(rules, updated_merchants)
    save_rules(Path(rules_path), rules)

    # Small console summary
    print("\nUpdated files:")
    print(f"  categories.txt -> {categories_path}")
    print(f"  rules.json     -> {rules_path}")
    print("  outputs:")
    for p in created_outputs:
        print(f"    - {p}")

    return 0


# ---------- IO helpers ----------


def collect_inputs(paths: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(p.rglob("*_activity.csv")))
        elif p.suffix.lower() == ".csv":
            out.append(p)
    return out


def load_categories(path: Path) -> List[str]:
    if not path.exists():
        return []
    cats = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return dedup_sorted(cats)


def save_categories(path: Path, cats: List[str]) -> None:
    cats2 = dedup_sorted(cats)
    path.write_text("\n".join(cats2) + "\n", encoding="utf-8")


def load_rules(path: Path) -> RuleSet:
    if not path.exists():
        data = {"rules_version": 1, "patterns": [], "exact": {}}
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    return RuleSet(patterns=data.get("patterns", []), exact=data.get("exact", {}))


def save_rules(path: Path, rules: RuleSet) -> None:
    data = {"rules_version": 1, "patterns": rules.patterns, "exact": rules.exact}
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_activity_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        rdr = csv.DictReader(fh)
        return [clean_row(d) for d in rdr]


def write_monarch_csv(
    src_csv: Path, rows: List[Dict[str, str]], out_dir: Optional[str]
) -> Path:
    out_dir_p = Path(out_dir) if out_dir else src_csv.parent
    out_dir_p.mkdir(parents=True, exist_ok=True)
    stem = (
        src_csv.stem.replace(".activity", "")
        if src_csv.name.endswith("_activity.csv")
        else src_csv.stem
    )
    out_path = out_dir_p / f"{stem}.monarch.csv"
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MONARCH_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in MONARCH_COLUMNS})
    return out_path


# ---------- Transform ----------


def transform_rows(
    rows: List[Dict[str, str]], rules: RuleSet, cats: List[str]
) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    out: List[Dict[str, str]] = []
    updated_merchants: Dict[str, str] = {}  # merchant -> category

    for r in rows:
        date, amount = (
            pick(r, ["Date", "Posted Date", "Transaction Date"]),
            pick(r, ["Amount"]),
        )
        desc = pick(r, ["Merchant", "Payee", "Description", "Memo", "Notes"])
        notes = pick(r, ["Notes", "Memo", "Description"])

        if not date or not amount or not desc:
            # Skip malformed line; could also log
            continue

        # Existing category from input?
        existing_cat = pick(r, ["Category"])
        if existing_cat:
            ensure_category(cats, existing_cat)
            payee = normalized_payee(
                desc, existing_cat, rules
            )  # will respect exact rule if found
            out.append(monarch_row(date, payee, existing_cat, notes, amount))
            updated_merchants[payee] = existing_cat
            continue

        # Apply rules (patterns first, then exact)
        match = match_rules(desc, rules)
        if match:
            cat = match.category or "Uncategorized"
            ensure_category(cats, cat)
            payee = match.payee_out or desc
            out.append(monarch_row(date, payee, cat, notes, amount))
            if match.category:
                updated_merchants[payee] = cat
        else:
            # No rule & no incoming category → Uncategorized + stub exact rule (null category)
            ensure_category(cats, "Uncategorized")
            payee = desc.strip()
            out.append(monarch_row(date, payee, "Uncategorized", notes, amount))
            # Leave category null to flag for future fill-in
            updated_merchants.setdefault(payee, None)  # type: ignore[assignment]

    return out, updated_merchants


def monarch_row(
    date: str, payee: str, category: str, notes: str, amount: str
) -> Dict[str, str]:
    return {
        "Date": date,
        "Payee": payee,
        "Category": category,
        "Notes": notes or "",
        "Amount": amount,
    }


def match_rules(desc: str, rules: RuleSet) -> Optional[RuleMatch]:
    text = desc or ""
    # 1) patterns (ordered, first match wins)
    for pat in rules.patterns:
        flags = re.IGNORECASE if "i" in (pat.get("flags") or "") else 0
        if re.search(pat["pattern"], text, flags):
            return RuleMatch(
                payee_out=pat.get("normalized") or desc,
                category=pat.get("category"),
            )
    # 2) exact (case-insensitive)
    lowered = {k.lower(): v for k, v in rules.exact.items()}
    if text.strip().lower() in lowered:
        info = lowered[text.strip().lower()]
        return RuleMatch(payee_out=text.strip(), category=info.get("category"))
    return None


def normalized_payee(payee_in: str, cat: str, rules: RuleSet) -> str:
    """
    If an existing exact rule exists for this payee (case-insensitive) with a normalized name,
    we could honor that here. For now, keep the literal payee_in unless a pattern provides normalized.
    """
    return payee_in.strip()


# ---------- Rules & categories updates ----------


def update_rules_exact(
    rules: RuleSet, merchant_to_category: Dict[str, Optional[str]]
) -> None:
    # Maintain case-insensitive map; preserve existing if present, update category value
    existing_ci = {k.lower(): (k, v) for k, v in rules.exact.items()}
    for merchant, cat in merchant_to_category.items():
        key_ci = merchant.strip().lower()
        if key_ci in existing_ci:
            orig_key, data = existing_ci[key_ci]
            # refresh category only if provided
            if cat is not None:
                data["category"] = cat
            rules.exact[orig_key] = data
        else:
            rules.exact[merchant.strip()] = {"category": cat}  # may remain null


def ensure_category(cats: List[str], name: str) -> None:
    n = (name or "").strip()
    if not n:
        return
    if n not in cats:
        cats.append(n)


def dedup_sorted(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for c in sorted(items, key=lambda s: s.lower()):
        if c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


# ---------- CSV utils ----------


def clean_row(d: Dict[str, str]) -> Dict[str, str]:
    return {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in d.items()}


def pick(d: Dict[str, str], keys: List[str]) -> str:
    for k in keys:
        v = d.get(k)
        if v:
            return v.strip()
    return ""
