from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_GROUP = "Other"
DEFAULT_CATEGORY = "Uncategorized"

def _write_text(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def cmd_clean(argv: list[str] | None = None) -> int:
    """Reset taxonomy + rules to a clean slate.

    Invariants (per your project conventions):
      - groups.txt contains exactly: Other
      - categories.txt contains exactly: Uncategorized
      - rules.json becomes []
    """
    p = argparse.ArgumentParser(prog="monarch-tools clean")
    p.add_argument("--rules", default="rules.json", help="Path to rules.json (default: rules.json)")
    p.add_argument("--categories", default="categories.txt", help="Path to categories.txt (default: categories.txt)")
    p.add_argument("--groups", default="groups.txt", help="Path to groups.txt (default: groups.txt)")
    p.add_argument("--yes", action="store_true", help="Do not prompt (for scripts)")
    args = p.parse_args(argv)

    rules_path = Path(args.rules)
    categories_path = Path(args.categories)
    groups_path = Path(args.groups)

    if not args.yes:
        print("This will reset:")
        print(f"  {groups_path} -> [{DEFAULT_GROUP}]")
        print(f"  {categories_path} -> [{DEFAULT_CATEGORY}]")
        print(f"  {rules_path} -> []")
        resp = input("Proceed? (y/N): ").strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.")
            return 1

    _write_text(groups_path, [DEFAULT_GROUP])
    _write_text(categories_path, [DEFAULT_CATEGORY])
    _write_json(rules_path, [])

    print("clean: reset complete")
    print(f"  groups: {groups_path}")
    print(f"  categories: {categories_path}")
    print(f"  rules: {rules_path}")
    return 0
