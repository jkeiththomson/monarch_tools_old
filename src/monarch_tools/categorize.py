"""Categorize command implementation for monarch_tools.

This version is intentionally simple and text-based. It:

- Reads:
  - data/categories.txt
  - data/groups.txt
  - data/rules.json
  - an <stem>.activity.csv file (from the `activity` command; columns: Date, Description, Amount)
- Walks each row of the activity file.
- For each row, ensures:
  - There is a canonical merchant name for the raw Description.
  - There is a category assigned to that canonical name.
- Writes back updated:
  - categories.txt
  - groups.txt
  - rules.json

The rules.json format is:

{
  "exact": {
    "<canonical_merchant>": {
      "category": "<category_name>"
    }
  },
  "patterns": [
    {
      "pattern": "<regex>",
      "canonical": "<canonical_merchant>"
    }
  ],
  "raw_to_canonical": {
    "<raw_description>": "<canonical_merchant>"
  },
  "rules_version": 1
}

"""
# Developer note:
# This command is designed to be an interactive, keyboard-driven categorization tool.
#
# Key ideas:
# - We normalize raw Description strings into "canonical" merchant names.
# - Each canonical merchant is assigned a category, and each category belongs to a group.
# - The user can type substrings to filter existing categories and groups. The longer the
#   substring, the fewer matches will be shown. When the user hits Enter on an empty line,
#   the current typed filter string is accepted as the category/group name (existing or new).
# - At any interactive prompt, typing the quit token (QUIT_TOKEN, default ":q") raises
#   UserAbort and the top-level cmd_categorize() handler will:
#     * Ask whether to save progress so far.
#     * If the user answers "y", write categories.txt, groups.txt, and rules.json.
#     * Otherwise, exit without writing any changes from this run.
#
# The interactive flow is primarily handled by:
#   - _pick_canonical(...)      – canonical merchant names
#   - _pick_category(...)       – category assignment with type-ahead filtering
#   - _pick_group_for_category – group assignment with type-ahead filtering
#   - cmd_categorize(...)       – main loop, error handling, and persistence
#
# If you change how input is read or how categories/groups are stored, be sure to audit the
# above functions together so the UI, rules.json, categories.txt, and groups.txt stay in sync.


import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


QUIT_TOKEN = ":q"


class UserAbort(Exception):
    """Raised when the user requests to stop categorizing early."""
    pass


def _check_quit(text: str) -> None:
    """Raise UserAbort if the user typed the quit token."""
    if text.strip() == QUIT_TOKEN:
        raise UserAbort

def _load_categories(path: Path) -> List[str]:
    cats: List[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            cats.append(s)
    return cats


def _save_categories(path: Path, categories: List[str]) -> None:
    text = "\n".join(categories) + "\n"
    path.write_text(text, encoding="utf-8")


def _load_groups(path: Path) -> Tuple[List[str], Dict[str, str], Dict[str, List[str]]]:
    """Return (groups_in_order, category_to_group, group_to_categories)."""
    groups: List[str] = []
    category_to_group: Dict[str, str] = {}
    group_to_categories: Dict[str, List[str]] = {}

    if not path.exists():
        return groups, category_to_group, group_to_categories

    current_group: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("*"):
            current_group = line.lstrip("*").strip()
            if current_group not in groups:
                groups.append(current_group)
            group_to_categories.setdefault(current_group, [])
        else:
            cat = line
            if current_group is None:
                # Ungrouped category; create a default group bucket.
                current_group = "Ungrouped"
                if current_group not in groups:
                    groups.append(current_group)
                group_to_categories.setdefault(current_group, [])
            category_to_group[cat] = current_group
            group_to_categories.setdefault(current_group, []).append(cat)

    return groups, category_to_group, group_to_categories


def _save_groups(path: Path, groups: List[str], group_to_categories: Dict[str, List[str]]) -> None:
    lines: List[str] = []
    for grp in groups:
        lines.append(f"*{grp}")
        for cat in group_to_categories.get(grp, []):
            lines.append(cat)
        lines.append("")  # blank line between groups
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _load_rules(path: Path) -> Dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}
    # Normalize structure
    data.setdefault("exact", {})
    data.setdefault("patterns", [])
    data.setdefault("raw_to_canonical", {})
    data.setdefault("rules_version", 1)
    return data


def _save_rules(path: Path, rules: Dict) -> None:
    path.write_text(json.dumps(rules, indent=2, sort_keys=True) + "\n", encoding="utf-8")



def _pick_canonical(raw_desc: str, existing_canonical: str | None) -> str:
    print()
    print(f"Raw merchant: {raw_desc}")
    if existing_canonical:
        prompt = f"Canonical merchant name [{existing_canonical}]: "
        entered = input(prompt).strip()
        _check_quit(entered)
        if entered == "":
            return existing_canonical
        return entered
    else:
        entered = input("Canonical merchant name (leave blank to use raw): ").strip()
        _check_quit(entered)
        if entered == "":
            return raw_desc
        return entered




def _pick_group_for_category(
    category: str,
    groups: List[str],
    group_to_categories: Dict[str, List[str]],
    category_to_group: Dict[str, str],
) -> str:
    """Interactively pick (or create) a group for a category, with filter-style typing."""
    print()
    print(f"Choose group for category '{category}':")
    if not groups:
        print("No groups defined yet.")
    print(f"Type {QUIT_TOKEN!r} at any prompt to stop categorizing and optionally save.")
    print("Type part of a group name to narrow the list; Enter accepts the current filter.")

    typed = ""

    while True:
        if groups:
            if typed:
                filt = typed.lower()
                matches = [g for g in groups if filt in g.lower()]
            else:
                matches = list(groups)

            print()
            if typed:
                print(f"Existing groups matching {typed!r}:")
            else:
                print("Existing groups:")
            for idx, g in enumerate(matches, start=1):
                print(f"  {idx:2d}. {g}")
            if not matches:
                print("  (no matches)")
        else:
            print()
            print("No groups defined yet. You will create a new one.")

        print()
        prompt = "Group filter / name (Enter to accept, or new text to refine) [Other]: "
        entered = input(prompt).strip()
        _check_quit(entered)

        # If nothing typed yet and user just hits Enter, default to "Other".
        if entered == "" and not typed:
            group = "Other"
            break

        # Empty input with an existing typed value => accept typed as group name.
        if entered == "" and typed:
            group = typed
            break

        # Non-empty: refine the filter.
        typed = entered

    # Ensure group is in list.
    if group not in groups:
        groups.append(group)
    group_to_categories.setdefault(group, [])
    if category not in group_to_categories[group]:
        group_to_categories[group].append(category)
    category_to_group[category] = group

    return group



def _pick_category(
    canonical: str,
    categories: List[str],
    category_to_group: Dict[str, str],
    groups: List[str],
    group_to_categories: Dict[str, List[str]],
) -> Tuple[str, str]:
    """Interactively pick (or create) a category for a merchant.

    Behaviour:

    - Shows existing categories.
    - Lets the user type a *filter string*; we show only categories containing that
      substring (case-insensitive).
    - As the user types a longer filter and re-enters it, they see fewer matches.
    - When they press Enter on a non-empty filter, that value becomes the category
      name to use (existing or new).
    - At any prompt, typing the quit token (e.g. ":q") aborts the whole categorize
      session and is handled by the caller via UserAbort.
    """
    print()
    print(f"Assign category for merchant: {canonical}")
    if not categories:
        print("No categories defined yet.")

    print()
    print("Type part of a category name to narrow the list.")
    print(f"Type {QUIT_TOKEN!r} at any prompt to stop categorizing and optionally save.")

    typed = ""

    while True:
        # Compute matches based on current filter string.
        if categories:
            if typed:
                filt = typed.lower()
                matches = [c for c in categories if filt in c.lower()]
            else:
                matches = list(categories)

            print()
            if typed:
                print(f"Existing categories matching {typed!r}:")
            else:
                print("Existing categories:")
            for idx, cat in enumerate(matches, start=1):
                grp = category_to_group.get(cat, "(no group)")
                print(f"  {idx:2d}. {cat} [{grp}]")
            if not matches:
                print("  (no matches)")
        else:
            print()
            print("No categories defined yet. You will create a new one.")

        print()
        prompt = "Category filter / name (Enter to accept, or new text to refine): "
        entered = input(prompt).strip()
        _check_quit(entered)

        # Empty input with an existing typed value = accept that as the category.
        if entered == "" and typed:
            category = typed
            break

        # Empty with nothing typed yet → ask again.
        if entered == "" and not typed:
            print("Please type at least one character (or {q} to quit).".format(q=QUIT_TOKEN))
            continue

        # Non-empty: update the filter string and loop again to show matches.
        typed = entered

    # Ensure the category exists in the list.
    if category not in categories:
        categories.append(category)

    # If the category already has a group, just reuse it.
    grp = category_to_group.get(category)
    if grp:
        return category, grp

    # Need to choose a group for this category using the same style of filter UI.
    grp = _pick_group_for_category(category, groups, group_to_categories, category_to_group)
    return category, grp



def _iter_activity_rows(activity_csv: Path):
    with activity_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        if "Description" not in headers:
            raise SystemExit(
                f"activity CSV {activity_csv} does not have a 'Description' column; "
                f"headers={headers}"
            )
        for row in reader:
            yield row



def _validate_state(
    categories: List[str],
    groups: List[str],
    category_to_group: Dict[str, str],
    group_to_categories: Dict[str, List[str]],
    rules: dict,
) -> bool:
    """Check basic consistency of categories, groups, and rules.

    - Every category should belong to exactly one group.
    - Every group should have at least one category.
    - Category/group maps should be internally consistent.
    - rules["exact"] categories should all exist in the categories list.
    - rules["patterns"] regex patterns should compile.
    """
    issues: List[str] = []
    ok = True

    cat_set = set(categories)
    group_set = set(groups)

    # Each category appears in exactly one group.
    for cat in categories:
        grp = category_to_group.get(cat)
        if not grp:
            ok = False
            issues.append(f"Category {cat!r} is not assigned to any group.")
        elif grp not in group_set:
            ok = False
            issues.append(f"Category {cat!r} is assigned to unknown group {grp!r}.")

    # Extra categories in category_to_group that are not in the categories list.
    for cat, grp in category_to_group.items():
        if cat not in cat_set:
            ok = False
            issues.append(f"Mapping has category {cat!r} -> {grp!r} but {cat!r} is not in categories list.")

    # Each group has at least one category.
    for grp in groups:
        cats = group_to_categories.get(grp, [])
        cats_in_list = [c for c in cats if c in cat_set]
        if not cats_in_list:
            ok = False
            issues.append(f"Group {grp!r} has no categories.")

    # Groups in group_to_categories should all exist.
    for grp in group_to_categories:
        if grp not in group_set:
            ok = False
            issues.append(f"group_to_categories has unknown group {grp!r}.")

    # Categories in group_to_categories should exist and agree with category_to_group.
    for grp, cats in group_to_categories.items():
        for cat in cats:
            if cat not in cat_set:
                ok = False
                issues.append(f"Group {grp!r} lists unknown category {cat!r}.")
            elif category_to_group.get(cat) != grp:
                ok = False
                issues.append(
                    f"Category {cat!r} appears in group_to_categories[{grp!r}] "
                    f"but category_to_group says {category_to_group.get(cat)!r}."
                )

    # Validate rules.json contents a bit.
    exact = rules.get("exact", {})
    raw_to_canonical = rules.get("raw_to_canonical", {})
    patterns = rules.get("patterns", [])

    for canonical, info in exact.items():
        if not isinstance(info, dict):
            ok = False
            issues.append(f"Exact rule for {canonical!r} is not a dict.")
            continue
        cat = info.get("category")
        if not cat:
            ok = False
            issues.append(f"Exact rule for {canonical!r} has no 'category'.")
        elif cat not in cat_set:
            ok = False
            issues.append(f"Exact rule for {canonical!r} uses unknown category {cat!r}.")

    import re as _re
    for idx, rule in enumerate(patterns):
        if not isinstance(rule, dict):
            ok = False
            issues.append(f"Pattern #{idx} is not a dict.")
            continue
        pat = rule.get("pattern")
        if not pat:
            continue
        try:
            _re.compile(pat)
        except _re.error as e:
            ok = False
            issues.append(f"Pattern #{idx} {pat!r} is not a valid regex: {e}.")

    for raw, canonical in raw_to_canonical.items():
        if not canonical:
            ok = False
            issues.append(f"raw_to_canonical entry for {raw!r} has empty canonical.")

    if issues:
        print()
        print("Consistency check found the following issues:")
        for msg in issues:
            print("  -", msg)
        print()
        print("You may want to review categories.txt, groups.txt, and rules.json.")
    else:
        print()
        print("Consistency check: OK. Categories, groups, and rules.json look coherent.")

    return ok


def cmd_categorize(ns: argparse.Namespace) -> int:
    categories_path = Path(ns.categories_txt)
    groups_path = Path(ns.groups_txt)
    rules_path = Path(ns.rules_json)
    activity_path = Path(ns.activity_csv)

    categories = _load_categories(categories_path)
    groups, category_to_group, group_to_categories = _load_groups(groups_path)
    rules = _load_rules(rules_path)

    raw_to_canonical: Dict[str, str] = rules.setdefault("raw_to_canonical", {})
    exact: Dict[str, Dict[str, str]] = rules.setdefault("exact", {})
    patterns = rules.setdefault("patterns", [])

    print(f"Loaded {len(categories)} categories, {len(groups)} groups, "
          f"{len(raw_to_canonical)} raw→canonical mappings, {len(exact)} canonical rules.")
    print(f"Type {QUIT_TOKEN!r} at any prompt to stop categorizing and optionally save.
")

    seen_canonical: Dict[str, str] = {}  # canonical -> category

    try:
        for row in _iter_activity_rows(activity_path):
            raw_desc = (row.get("Description") or "").strip()
            if not raw_desc:
                continue

            # First, see if we already have a canonical + category fully defined.
            canonical = raw_to_canonical.get(raw_desc)

            # Try patterns only if no explicit mapping.
            if not canonical and patterns:
                for rule in patterns:
                    pat = rule.get("pattern")
                    if not pat:
                        continue
                    try:
                        if re.search(pat, raw_desc, flags=re.IGNORECASE):
                            canonical = rule.get("canonical") or raw_desc
                            break
                    except re.error:
                        # Ignore bad patterns
                        continue

            # If still no canonical, interact with the user.
            canonical = _pick_canonical(raw_desc, canonical)
            raw_to_canonical[raw_desc] = canonical

            # If we have already assigned a category for this canonical in this run, reuse it.
            if canonical in seen_canonical:
                continue

            info = exact.get(canonical)
            category = info.get("category") if info else None

            if category is None:
                cat, grp = _pick_category(
                    canonical,
                    categories,
                    category_to_group,
                    groups,
                    group_to_categories,
                )
                category = cat
                exact[canonical] = {"category": category}
            else:
                # Ensure the category appears in our category/group structures.
                if category not in categories:
                    categories.append(category)
                grp = category_to_group.get(category)
                if grp is None:
                    # Put into a default group.
                    grp = "Other"
                    if grp not in groups:
                        groups.append(grp)
                    group_to_categories.setdefault(grp, []).append(category)
                    category_to_group[category] = grp

            seen_canonical[canonical] = category

    except UserAbort:
        print()
        if getattr(ns, "dry_run", False):
            print("DRY RUN: Quit received; nothing written.")
            return 0
        answer = input(f"{QUIT_TOKEN} received. Save categorizations so far? [y/N]: ").strip().lower()
        if not answer.startswith("y"):
            print("Aborting without writing any changes.")
            return 1

    # Run a consistency check on categories, groups, and rules.
    _validate_state(categories, groups, category_to_group, group_to_categories, rules)

    # Persist files or simulate, depending on dry-run.
    if getattr(ns, "dry_run", False):
        print("\nDRY RUN: No files were written.")
        print("Would write:")
        print(f"  {categories_path}")
        print(f"  {groups_path}")
        print(f"  {rules_path}")
        return 0

    _save_categories(categories_path, categories)
    _save_groups(groups_path, groups, group_to_categories)
    _save_rules(rules_path, rules)

    print()
    print("Updated:")
    print(f"  {categories_path}")
    print(f"  {groups_path}")
    print(f"  {rules_path}")
    return 0
