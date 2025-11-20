"""Sanity-check totals between activity CSV and Monarch CSV."""

import argparse
import csv
from pathlib import Path
from typing import Tuple

from .activity import _amount_to_value


def _activity_stats(activity_path: Path) -> Tuple[int, float, int, float]:
    """Return (payments_count, payments_total, purchases_count, purchases_total)
    based on the raw activity CSV.
    """
    payments_count = 0
    payments_total = 0.0
    purchases_count = 0
    purchases_total = 0.0

    with activity_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = (row.get("Date") or "").strip()
            amt_str = (row.get("Amount") or "").strip()
            if not date or not amt_str:
                continue
            # Skip summary rows or anything that isn't a yyyy-mm-dd date.
            if len(date) != 10 or date.count("-") != 2:
                continue
            try:
                val = _amount_to_value(amt_str)
            except Exception:
                continue

            if val > 0:
                # Purchase / fee / interest
                purchases_count += 1
                purchases_total += val
            elif val < 0:
                # Payment / credit / refund
                payments_count += 1
                payments_total += -val  # store as positive magnitude

    return payments_count, payments_total, purchases_count, purchases_total


def _monarch_stats(monarch_path: Path) -> Tuple[int, float, int, float]:
    """Return (payments_count, payments_total, purchases_count, purchases_total)
    based on the Monarch-import CSV (signs already normalized).
    """
    payments_count = 0
    payments_total = 0.0
    purchases_count = 0
    purchases_total = 0.0

    with monarch_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            merchant = (row.get("Merchant") or "").strip()
            amt_str = (row.get("Amount") or "").strip()
            if not amt_str:
                continue
            # Skip synthetic opening balance row; we want to compare only
            # the statement-derived transactions against the activity file.
            if merchant == "Opening Balance":
                continue
            try:
                amount = float(amt_str)
            except ValueError:
                continue

            if amount > 0:
                payments_count += 1
                payments_total += amount
            elif amount < 0:
                purchases_count += 1
                purchases_total += -amount  # store as positive magnitude

    return payments_count, payments_total, purchases_count, purchases_total


def cmd_sanity(ns: argparse.Namespace) -> int:
    """Compare totals and counts between activity and Monarch CSVs.

    This is intended as a final "does this make sense?" check:

    - Payments/credits should have similar counts and totals in both files.
    - Purchases/fees should have similar counts and totals in both files.
    """
    activity_path = Path(ns.activity_csv)
    if ns.monarch_csv:
        monarch_path = Path(ns.monarch_csv)
    else:
        # Derive from activity filename as <stem>.monarch.csv
        name = activity_path.name
        if name.endswith(".activity.csv"):
            base = name[: -len(".activity.csv")]
        else:
            base = activity_path.stem
        monarch_path = activity_path.with_name(base + ".monarch.csv")

    if not activity_path.exists():
        print(f"ERROR: Activity CSV not found: {activity_path}")
        return 1
    if not monarch_path.exists():
        print(f"ERROR: Monarch CSV not found: {monarch_path}")
        return 1

    a_pay_cnt, a_pay_tot, a_pur_cnt, a_pur_tot = _activity_stats(activity_path)
    m_pay_cnt, m_pay_tot, m_pur_cnt, m_pur_tot = _monarch_stats(monarch_path)

    def fmt(x: float) -> str:
        return f"{x:,.2f}"

    print(f"Activity file : {activity_path}")
    print(f"Monarch file  : {monarch_path}")
    print()
    print("Payments and credits:")
    print(f"  Activity: count={a_pay_cnt:4d}, total={fmt(a_pay_tot)}")
    print(f"  Monarch : count={m_pay_cnt:4d}, total={fmt(m_pay_tot)}")
    print()
    print("Purchases and fees:")
    print(f"  Activity: count={a_pur_cnt:4d}, total={fmt(a_pur_tot)}")
    print(f"  Monarch : count={m_pur_cnt:4d}, total={fmt(m_pur_tot)}")

    # Show differences (Monarch - Activity)
    diff_pay_cnt = m_pay_cnt - a_pay_cnt
    diff_pay_tot = m_pay_tot - a_pay_tot
    diff_pur_cnt = m_pur_cnt - a_pur_cnt
    diff_pur_tot = m_pur_tot - a_pur_tot

    print()
    print("Differences (Monarch - Activity):")
    print(f"  Payments:  count={diff_pay_cnt:+4d}, total={fmt(diff_pay_tot)}")
    print(f"  Purchases: count={diff_pur_cnt:+4d}, total={fmt(diff_pur_tot)}")

    # Light heuristic: if totals differ by more than a few cents, warn.
    eps = 0.05
    if abs(diff_pay_tot) > eps or abs(diff_pur_tot) > eps:
        print()
        print("WARNING: Totals differ by more than a few cents. You may want to double-check.")
        return 1

    print()
    print("Sanity check: OK (differences are within a few cents).")
    return 0
