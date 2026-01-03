from __future__ import annotations

import argparse
from pathlib import Path
import curses

from monarch_tools.ui.categorize_ui import run_categorize_ui

def cmd_categorize(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="monarch-tools categorize")
    p.add_argument("--in", dest="in_csv", required=True, help="Input transactions CSV (out/*.monarch.csv)")
    p.add_argument("--rules", required=True, help="Path to rules.json")
    p.add_argument("--categories", required=True, help="Path to categories.txt")
    p.add_argument("--groups", required=True, help="Path to groups.txt")
    p.add_argument("--out", dest="out_csv", required=False, help="Optional output CSV path (defaults to overwrite --in)")
    args = p.parse_args(argv)

    in_csv = Path(args.in_csv)
    rules = Path(args.rules)
    categories = Path(args.categories)
    groups = Path(args.groups)
    out_csv = Path(args.out_csv) if args.out_csv else None

    def _wrapped(stdscr):
        return run_categorize_ui(stdscr, in_csv, rules, categories, groups, out_csv)

    return curses.wrapper(_wrapped)
