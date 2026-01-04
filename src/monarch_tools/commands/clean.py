from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_GROUPS = ['Aaa:', '  Uncategorized']
DEFAULT_CATEGORIES = ['Uncategorized']
DEFAULT_RULES = {'merchants': {}}

def _write_text(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def cmd_clean(argv: list[str] | None = None) -> int:
    """Reset taxonomy + rules to project defaults.

    Defaults:
      - data/groups.txt
      - data/categories.txt
      - data/rules.json
    """
    p = argparse.ArgumentParser(prog="monarch-tools clean")
    p.add_argument("--rules", default="data/rules.json", help="Path to rules.json (default: data/rules.json)")
    p.add_argument("--categories", default="data/categories.txt", help="Path to categories.txt (default: data/categories.txt)")
    p.add_argument("--groups", default="data/groups.txt", help="Path to groups.txt (default: data/groups.txt)")
    p.add_argument("--yes", action="store_true", help="Do not prompt (for scripts)")
    args = p.parse_args(argv)

    rules_path = Path(args.rules)
    categories_path = Path(args.categories)
    groups_path = Path(args.groups)

    if not args.yes:
        print("This will reset:")
        print(f"  {groups_path} -> {DEFAULT_GROUPS}")
        print(f"  {categories_path} -> {DEFAULT_CATEGORIES}")
        print(f"  {rules_path} -> (defaults from your provided rules.json)")
        resp = input("Proceed? (y/N): ").strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.")
            return 1

    _write_text(groups_path, DEFAULT_GROUPS)
    _write_text(categories_path, DEFAULT_CATEGORIES)
    _write_json(rules_path, DEFAULT_RULES)

    print("clean: reset complete")
    print(f"  groups: {groups_path}")
    print(f"  categories: {categories_path}")
    print(f"  rules: {rules_path}")
    return 0
