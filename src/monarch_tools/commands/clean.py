from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List


def cmd_clean(argv: List[str]) -> int:
    """
    Reset categories, groups, and rules to a clean baseline.
    """

    parser = argparse.ArgumentParser(prog="monarch-tools clean")
    parser.add_argument("--categories", required=True)
    parser.add_argument("--groups", required=True)
    parser.add_argument("--rules", required=True)

    args = parser.parse_args(argv)

    categories_path = Path(args.categories)
    groups_path = Path(args.groups)
    rules_path = Path(args.rules)

    # --- Write groups ---
    groups_path.write_text(
        "Other\n",
        encoding="utf-8",
    )

    # --- Write categories ---
    categories_path.write_text(
        "Uncategorized\tOther\n",
        encoding="utf-8",
    )

    # --- Write rules ---
    rules_path.write_text(
        json.dumps([], indent=2) + "\n",
        encoding="utf-8",
    )

    print("Cleaned:")
    print(f"  categories -> {categories_path}")
    print(f"  groups     -> {groups_path}")
    print(f"  rules      -> {rules_path}")
    print("\nBaseline:")
    print("  Group: Other")
    print("  Category: Uncategorized -> Other")

    return 0