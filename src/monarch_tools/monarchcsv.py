"""Export Monarch Money-compatible CSV from an activity file and rules.json."""

import argparse
import csv
import json
import re
import datetime
from pathlib import Path
from typing import Dict, List

from .activity import _amount_to_value
from .categorize import _load_rules
from .config import ensure_account_opening_balance


def _iter_activity_transactions(activity_path: Path):
    """Yield transactional rows from an <stem>.activity.csv file.

    This skips the blank line and summary rows that _write_activity_csv()
    appends at the end of the file. We only yield rows whose Date field
    looks like YYYY-MM-DD.
    """
    with activity_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = (row.get("Date") or "").strip()
            if not date:
                continue
            # Activity writer uses yyyy-mm-dd dates; ignore anything else.
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                continue
            yield row


def cmd_monarch(ns: argparse.Namespace) -> int:
    """Export a Monarch-compatible CSV for a single account.

    We follow Monarch Money's "single-account" import format:

        Date, Merchant, Category, Account, Original Statement, Notes, Amount, Tags

    See their help center docs for details on required order and sign
    conventions for Amount.
    """
    activity_path = Path(ns.activity_csv)
    rules_path = Path(ns.rules_json)
    out_path = Path(ns.out) if ns.out else None

    if not activity_path.exists():
        print(f"ERROR: Activity CSV not found: {activity_path}")
        return 1

    if not rules_path.exists():
        print(f"ERROR: rules.json not found: {rules_path}")
        return 1

    if out_path is None:
        # Derive <stem>.monarch.csv from an <stem>.activity.csv filename.
        # If the user passes something that doesn't end in .activity.csv, we
        # just append .monarch.csv to the stem.
        name = activity_path.name
        if name.endswith(".activity.csv"):
            base = name[: -len(".activity.csv")]
        else:
            base = activity_path.stem
        out_path = activity_path.with_name(base + ".monarch.csv")

    rules = _load_rules(rules_path)
    raw_to_canonical: Dict[str, str] = rules.get("raw_to_canonical", {})
    exact: Dict[str, Dict[str, str]] = rules.get("exact", {})
    patterns = rules.get("patterns", [])

    account_name = ns.account
    # Make sure we have an opening balance recorded for this account.
    opening_balance = ensure_account_opening_balance(account_name)

    def _canonical_for(raw_desc: str) -> str:
        canonical = raw_to_canonical.get(raw_desc)
        if canonical:
            return canonical
        # Try regex patterns as a fallback, mirroring categorize.py.
        for rule in patterns:
            pat = rule.get("pattern")
            if not pat:
                continue
            try:
                if re.search(pat, raw_desc, flags=re.IGNORECASE):
                    canonical = rule.get("canonical") or raw_desc
                    return canonical
            except re.error:
                # Ignore bad patterns; categorize() should catch these.
                continue
        return raw_desc

    # First collect all real statement transactions and track the earliest date.
    tx_rows: List[List[str]] = []
    earliest_date = None

    for row in _iter_activity_transactions(activity_path):
        date = (row.get("Date") or "").strip()
        raw_desc = (row.get("Description") or "").strip()
        amt_str = (row.get("Amount") or "").strip()

        if not date or not amt_str:
            continue

        try:
            val = _amount_to_value(amt_str)
        except Exception as e:  # pragma: no cover - defensive
            print(f"WARNING: Skipping row with unparsable amount {amt_str!r}: {e}")
            continue

        # Map to Monarch's sign convention:
        # - Debits / purchases / fees   → negative
        # - Credits / payments / refunds → positive
        if val > 0:
            amount = -abs(val)
        elif val < 0:
            amount = abs(val)
        else:
            amount = 0.0

        canonical = _canonical_for(raw_desc)
        info = exact.get(canonical) or {}
        category = info.get("category", "")

        merchant = canonical
        original = raw_desc
        notes = ""
        tags = ""

        tx_rows.append(
            [
                date,
                merchant,
                category,
                account_name,
                original,
                notes,
                f"{amount:.2f}",
                tags,
            ]
        )

        # Track earliest transaction date for placing opening balance.
        try:
            d = datetime.date.fromisoformat(date)
        except Exception:
            d = None
        if d is not None:
            if earliest_date is None or d < earliest_date:
                earliest_date = d

    # If an opening balance is defined, add a synthetic transaction row.
    if opening_balance is not None:
        ob_value = float(opening_balance)
        if earliest_date is not None:
            opening_date = earliest_date - datetime.timedelta(days=1)
            opening_date_str = opening_date.isoformat()
        else:
            # Fallback: arbitrary stable date if no transactions exist.
            opening_date_str = "1970-01-01"

        if ob_value > 0:
            # Positive balance means you already owed this amount: treat as a purchase.
            ob_amount = -abs(ob_value)
        elif ob_value < 0:
            # Negative balance means a credit in your favor.
            ob_amount = abs(ob_value)
        else:
            ob_amount = 0.0

        merchant = "Opening Balance"
        category = ""
        original = "Opening balance imported from config.toml"
        notes = "Synthetic opening balance transaction (not in original statement)"
        tags = ""

        tx_rows.insert(
            0,
            [
                opening_date_str,
                merchant,
                category,
                account_name,
                original,
                notes,
                f"{ob_amount:.2f}",
                tags,
            ],
        )

    tx_count = len(tx_rows)

    with out_path.open("w", encoding="utf-8", newline="") as f_out:
        w = csv.writer(f_out)
        # Monarch single-account required header & order.
        w.writerow(
            [
                "Date",
                "Merchant",
                "Category",
                "Account",
                "Original Statement",
                "Notes",
                "Amount",
                "Tags",
            ]
        )

        for row in tx_rows:
            w.writerow(row)

    print(f"Wrote Monarch CSV: {out_path} ({tx_count} transactions)")
    print("Reminder: In Monarch, use the *single-account* CSV import flow.")
    return 0
