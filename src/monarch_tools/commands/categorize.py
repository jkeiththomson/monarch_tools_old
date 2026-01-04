from __future__ import annotations

import argparse
import curses
from pathlib import Path
from typing import Optional

from ..ui.categorize_ui import run_categorize_ui

def cmd_categorize(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="monarch-tools categorize")
    p.add_argument("--in", dest="in_csv", required=True, help="Input transactions CSV (out/*.monarch.csv)")
    p.add_argument("--rules", default="data/rules.json", help="Path to rules.json (default: data/rules.json)")
    p.add_argument("--categories", default="data/categories.txt", help="Path to categories.txt (default: data/categories.txt)")
    p.add_argument("--groups", default="data/groups.txt", help="Path to groups.txt (default: data/groups.txt)")
    p.add_argument("--out", dest="out_csv", default=None, help="Optional output CSV path (defaults to overwrite --in)")
    args = p.parse_args(argv)

    in_csv = Path(args.in_csv)
    rules = Path(args.rules)
    categories = Path(args.categories)
    groups = Path(args.groups)
    out_csv: Optional[Path] = Path(args.out_csv) if args.out_csv else None

    # Ensure the data/ directory exists when using defaults
    for pth in (rules, categories, groups):
        if pth.parent and str(pth.parent) not in (".", ""):
            pth.parent.mkdir(parents=True, exist_ok=True)

    def _wrapped(stdscr):
        return run_categorize_ui(stdscr, in_csv, rules, categories, groups, out_csv)

    return curses.wrapper(_wrapped)
