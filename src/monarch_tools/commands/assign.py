from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple

from monarch_tools.categorize_engine import normalize_merchant


# -----------------------------
# file readers / writers
# -----------------------------

def _read_unmatched(path: Path) -> List[Tuple[str, int]]:
    rows: List[Tuple[str, int]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append((row["Merchant"], int(row["Count"])))
    return rows


def _read_categories(path: Path) -> List[str]:
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _read_groups(path: Path) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    if not path.exists():
        return groups

    current = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.endswith(":"):
            current = line[:-1]
            groups.setdefault(current, [])
        else:
            groups.setdefault(current, []).append(line)
    return groups


def _write_categories(path: Path, cats: List[str]) -> None:
    path.write_text("\n".join(sorted(set(cats))) + "\n", encoding="utf-8")


def _write_groups(path: Path, groups: Dict[str, List[str]]) -> None:
    lines: List[str] = []
    for g in sorted(groups):
        lines.append(f"{g}:")
        for c in sorted(groups[g]):
            lines.append(c)
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _read_rules(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_rules(path: Path, rules: Dict[str, str]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, sort_keys=True)
        f.write("\n")


# -----------------------------
# transaction examples
# -----------------------------

def _tx_examples_by_merchant(
    tx_path: Path,
) -> Dict[str, List[Tuple[str, str, str]]]:
    """
    merchant -> list of (date, amount, description)

    Supports schemas:
      - Date,Merchant,Amount,...
      - date,description,amount,...
    """
    examples: Dict[str, List[Tuple[str, str, str]]] = {}
    if not tx_path.exists():
        return examples

    with tx_path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if not r.fieldnames:
            return examples

        fields = set(r.fieldnames)

        if "Merchant" in fields:
            col_m = "Merchant"
            col_d = "Date"
            col_a = "Amount"
            col_desc = "Merchant"
        else:
            col_m = "description"
            col_d = "date"
            col_a = "amount"
            col_desc = "description"

        for row in r:
            merchant = normalize_merchant(row.get(col_m, "") or "")
            if not merchant:
                continue

            date = (row.get(col_d, "") or "").strip()
            amount = (row.get(col_a, "") or "").strip()
            desc = (row.get(col_desc, "") or "").strip()

            examples.setdefault(merchant, []).append((date, amount, desc))

    return examples


# -----------------------------
# command
# -----------------------------

def cmd_assign(argv: List[str]) -> int:
    p = argparse.ArgumentParser(prog="monarch-tools assign")
    p.add_argument("--unmatched", required=True)
    p.add_argument("--tx", default="")
    p.add_argument("--rules", required=True)
    p.add_argument("--categories", required=True)
    p.add_argument("--groups", required=True)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args(argv)

    unmatched = _read_unmatched(Path(args.unmatched))
    if args.limit > 0:
        unmatched = unmatched[: args.limit]

    categories = _read_categories(Path(args.categories))
    groups = _read_groups(Path(args.groups))
    rules = _read_rules(Path(args.rules))
    tx_examples = (
        _tx_examples_by_merchant(Path(args.tx)) if args.tx else {}
    )

    for merchant, count in unmatched:
        print()
        print(f"Merchant: {merchant}")
        print(f"Count:    {count}")

        ex = tx_examples.get(merchant, [])
        if ex:
            print("Examples:")
            for d, a, desc in ex[:5]:
                print(f"  {d} | {a} | {desc}")

        while True:
            print()
            print("Categories:")
            for i, c in enumerate(categories, 1):
                grp = next((g for g, cs in groups.items() if c in cs), "")
                suffix = f" [{grp}]" if grp else ""
                print(f"  {i}) {c}{suffix}")

            print()
            print("Commands:")
            print("  <number>     assign category")
            print("  nc <name>    new category")
            print("  ng <name>    new group")
            print("  q            quit")

            choice = input("> ").strip()
            if not choice:
                continue

            if choice == "q":
                _write_rules(Path(args.rules), rules)
                _write_categories(Path(args.categories), categories)
                _write_groups(Path(args.groups), groups)
                print("Wrote rules, categories, groups")
                return 0

            if choice.startswith("ng "):
                gname = choice[3:].strip()
                groups.setdefault(gname, [])
                print(f"Created group: {gname}")
                continue

            if choice.startswith("nc "):
                cname = choice[3:].strip()
                if cname not in categories:
                    categories.append(cname)

                print("Assign category to group:")
                for i, g in enumerate(groups, 1):
                    print(f"  {i}) {g}")

                gsel = input("> ").strip()
                try:
                    gname = list(groups.keys())[int(gsel) - 1]
                except Exception:
                    print("Invalid group")
                    continue

                groups.setdefault(gname, [])
                if cname not in groups[gname]:
                    groups[gname].append(cname)

                rules[merchant] = cname
                print(f"Assigned {merchant} -> {cname} [{gname}]")
                break

            try:
                idx = int(choice) - 1
                cname = categories[idx]
                rules[merchant] = cname
                print(f"Assigned {merchant} -> {cname}")
                break
            except Exception:
                print("Invalid input")

    _write_rules(Path(args.rules), rules)
    _write_categories(Path(args.categories), categories)
    _write_groups(Path(args.groups), groups)
    print("Wrote rules, categories, groups")
    return 0