from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from monarch_tools.categorize_engine import normalize_merchant


@dataclass
class MerchantItem:
    merchant: str
    count: int
    example: str  # "YYYY-MM-DD | AMOUNT | DESCRIPTION"


@dataclass
class RulesData:
    version: int
    merchants: Dict[str, str]
    patterns: List[dict]


def _ascii(s: str) -> str:
    return (s or "").encode("ascii", "replace").decode("ascii")


def load_categories(path: Path) -> List[str]:
    if not path.exists():
        return ["Uncategorized"]
    cats: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        cats.append(s)
    if "Uncategorized" not in cats:
        cats.insert(0, "Uncategorized")
    seen = set()
    out: List[str] = []
    for c in cats:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def write_categories(path: Path, cats: List[str]) -> None:
    rest = sorted([c for c in cats if c != "Uncategorized"])
    out = ["Uncategorized"] + rest
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def load_groups(path: Path) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    if not path.exists():
        return groups
    current: Optional[str] = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":"):
            current = line[:-1].strip()
            groups.setdefault(current, [])
        else:
            if current is None:
                continue
            groups.setdefault(current, []).append(line)

    for g in list(groups.keys()):
        seen = set()
        dedup: List[str] = []
        for c in groups[g]:
            if c not in seen:
                dedup.append(c)
                seen.add(c)
        groups[g] = dedup
    return groups


def write_groups(path: Path, groups: Dict[str, List[str]]) -> None:
    def sort_key(g: str) -> Tuple[int, str]:
        return (1, g) if g != "Other" else (2, g)

    lines: List[str] = []
    for g in sorted(groups.keys(), key=sort_key):
        lines.append(f"{g}:")
        for c in sorted(groups[g]):
            lines.append(c)
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def ensure_other_uncategorized(groups: Dict[str, List[str]]) -> None:
    groups.setdefault("Other", [])
    if "Uncategorized" not in groups["Other"]:
        groups["Other"].append("Uncategorized")


def load_rules(path: Path) -> RulesData:
    if not path.exists():
        return RulesData(version=1, merchants={}, patterns=[])
    data = json.loads(path.read_text(encoding="utf-8"))
    version = int(data.get("version", 1))
    merchants = data.get("merchants", {})
    patterns = data.get("patterns", [])
    if not isinstance(merchants, dict):
        merchants = {}
    if not isinstance(patterns, list):
        patterns = []
    m2: Dict[str, str] = {}
    for k, v in merchants.items():
        if isinstance(k, str) and isinstance(v, str):
            m2[k] = v
    return RulesData(version=version, merchants=m2, patterns=list(patterns))


def write_rules(path: Path, rules: RulesData) -> None:
    out = {"version": rules.version, "merchants": rules.merchants, "patterns": rules.patterns}
    path.write_text(json.dumps(out, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def read_unmatched(path: Path) -> List[Tuple[str, int]]:
    rows: List[Tuple[str, int]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            m = normalize_merchant(row.get("Merchant", "") or "")
            if not m:
                continue
            try:
                cnt = int(row.get("Count", "0") or "0")
            except ValueError:
                cnt = 0
            rows.append((m, cnt))
    rows.sort(key=lambda x: (-x[1], x[0]))
    return rows


def tx_example_map(tx_path: Path) -> Dict[str, str]:
    examples: Dict[str, str] = {}
    if not tx_path.exists():
        return examples
    with tx_path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if not r.fieldnames:
            return examples
        fields = set(r.fieldnames)
        if "Merchant" in fields:
            col_m, col_d, col_a, col_desc = "Merchant", "Date", "Amount", "Merchant"
        else:
            col_m, col_d, col_a, col_desc = "description", "date", "amount", "description"
        for row in r:
            m = normalize_merchant(row.get(col_m, "") or "")
            if not m or m in examples:
                continue
            d = (row.get(col_d, "") or "").strip()
            a = (row.get(col_a, "") or "").strip()
            desc = (row.get(col_desc, "") or "").strip()
            examples[m] = f"{d} | {a} | {desc}"
    return examples


def cmd_assign_tui(argv: List[str]) -> int:
    import curses

    ap = argparse.ArgumentParser(prog="monarch-tools assign_tui")
    ap.add_argument("--unmatched", required=True, help="Input .unmatched_merchants.csv")
    ap.add_argument("--tx", required=True, help="Transactions CSV for examples")
    ap.add_argument("--rules", required=True, help="rules.json to update on exit")
    ap.add_argument("--categories", required=True, help="categories.txt")
    ap.add_argument("--groups", required=True, help="groups.txt")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = ap.parse_args(argv)

    unmatched_path = Path(args.unmatched).expanduser()
    tx_path = Path(args.tx).expanduser()
    rules_path = Path(args.rules).expanduser()
    cats_path = Path(args.categories).expanduser()
    groups_path = Path(args.groups).expanduser()

    cats = load_categories(cats_path)
    groups = load_groups(groups_path)
    ensure_other_uncategorized(groups)
    rules = load_rules(rules_path)

    raw = read_unmatched(unmatched_path)
    if args.limit and args.limit > 0:
        raw = raw[: args.limit]

    exmap = tx_example_map(tx_path)

    merchants: List[MerchantItem] = []
    for m, cnt in raw:
        if m in rules.merchants:
            continue
        merchants.append(MerchantItem(m, cnt, exmap.get(m, "")))

    focus = "merchants"  # taxonomy|merchants
    status = "TAB focus | Enter assign | g add group | c add category | D del category | X del group | q save+quit"

    group_names: List[str] = []
    g_idx = 0
    c_idx = 0

    merchant_idx = 0
    merchant_scroll = 0

    def rebuild_groups_sorted() -> None:
        nonlocal group_names, g_idx, c_idx
        group_names = sorted(groups.keys(), key=lambda g: (1, g) if g != "Other" else (2, g))
        if not group_names:
            g_idx = 0
            c_idx = 0
            return
        if g_idx >= len(group_names):
            g_idx = len(group_names) - 1
        g = group_names[g_idx]
        cats_in_group = sorted(groups.get(g, []))
        if not cats_in_group:
            c_idx = 0
        else:
            c_idx = max(0, min(c_idx, len(cats_in_group) - 1))

    def selected_group() -> Optional[str]:
        if not group_names:
            return None
        return group_names[g_idx]

    def selected_category() -> Optional[str]:
        g = selected_group()
        if not g:
            return None
        cats_in_group = sorted(groups.get(g, []))
        if not cats_in_group:
            return None
        if c_idx < 0 or c_idx >= len(cats_in_group):
            return None
        return cats_in_group[c_idx]

    def safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
        h2, w2 = win.getmaxyx()
        if y < 0 or y >= h2 or x < 0 or x >= w2:
            return
        maxlen = max(0, w2 - x - 1)
        if maxlen <= 0:
            return
        try:
            win.addstr(y, x, _ascii(s)[:maxlen], attr)
        except Exception:
            pass

    def prompt_input(stdscr, prompt: str) -> str:
        stdscr.erase()
        safe_addstr(stdscr, 0, 0, prompt)
        safe_addstr(stdscr, 1, 0, "> ")
        stdscr.refresh()
        curses.echo()
        try:
            b = stdscr.getstr(1, 2)
        finally:
            curses.noecho()
        try:
            return (b.decode("utf-8", errors="ignore")).strip()
        except Exception:
            return ""

    def confirm_yes(stdscr, prompt: str) -> bool:
        ans = prompt_input(stdscr, prompt + " Type 'yes' to confirm:")
        return ans.strip().lower() == "yes"

    def is_category_used_anywhere(cat: str) -> bool:
        for g, clist in groups.items():
            if cat in clist:
                return True
        return False

    def delete_category(stdscr) -> None:
        nonlocal status, c_idx
        if focus != "taxonomy":
            status = "TAB to taxonomy to delete categories/groups."
            return

        cat = selected_category()
        g = selected_group()
        if not cat or not g:
            status = "No category selected."
            return
        if cat == "Uncategorized":
            status = "Cannot delete Uncategorized."
            return

        if not confirm_yes(stdscr, f"Delete category '{cat}' from group '{g}'?"):
            status = "Canceled."
            return

        # Remove from the group
        groups[g] = [x for x in groups.get(g, []) if x != cat]

        # Any rules pointing to this category -> Uncategorized
        changed = 0
        for m, c in list(rules.merchants.items()):
            if c == cat:
                rules.merchants[m] = "Uncategorized"
                changed += 1

        # If category not in any group anymore, drop from categories.txt list
        if not is_category_used_anywhere(cat):
            cats[:] = [x for x in cats if x != cat]

        rebuild_groups_sorted()
        status = f"Deleted category '{cat}'. Remapped {changed} rules to Uncategorized."

    def delete_group(stdscr) -> None:
        nonlocal status, g_idx, c_idx
        if focus != "taxonomy":
            status = "TAB to taxonomy to delete categories/groups."
            return

        g = selected_group()
        if not g:
            status = "No group selected."
            return
        if g in ("Other",):
            status = "Cannot delete group 'Other'."
            return

        if not confirm_yes(stdscr, f"Delete group '{g}' and its category memberships?"):
            status = "Canceled."
            return

        cats_in_group = list(groups.get(g, []))
        # Remove the group entirely
        if g in groups:
            del groups[g]

        # For any category that is now in no group, rules must be remapped and category removed
        changed = 0
        for cat in cats_in_group:
            if cat == "Uncategorized":
                continue
            if not is_category_used_anywhere(cat):
                # remap rules
                for m, c in list(rules.merchants.items()):
                    if c == cat:
                        rules.merchants[m] = "Uncategorized"
                        changed += 1
                # remove category from categories list
                cats[:] = [x for x in cats if x != cat]

        ensure_other_uncategorized(groups)
        rebuild_groups_sorted()
        g_idx = min(g_idx, max(0, len(group_names) - 1))
        c_idx = 0
        status = f"Deleted group '{g}'. Remapped {changed} rules to Uncategorized."

    def assign_current() -> None:
        nonlocal merchant_idx, merchant_scroll, status
        if not merchants:
            status = "No merchants left."
            return
        cat = selected_category()
        if not cat:
            status = "No category selected."
            return
        m = merchants[merchant_idx].merchant
        rules.merchants[m] = cat
        merchants.pop(merchant_idx)
        if merchant_idx >= len(merchants):
            merchant_idx = max(0, len(merchants) - 1)
        if merchant_scroll > merchant_idx:
            merchant_scroll = merchant_idx
        status = f"Assigned: {m} -> {cat}"

    def add_group(stdscr) -> None:
        nonlocal g_idx, c_idx, status
        name = prompt_input(stdscr, "New group name (ASCII):")
        name = name.strip()
        if not name:
            status = "Canceled new group."
            return
        if name in groups:
            status = f"Group exists: {name}"
            return
        groups[name] = []
        ensure_other_uncategorized(groups)
        rebuild_groups_sorted()
        g_idx = group_names.index(name)
        c_idx = 0
        status = f"Created group: {name}"

    def add_category(stdscr) -> None:
        nonlocal c_idx, status
        g = selected_group()
        if not g:
            status = "No group selected. (taxonomy focus) Use arrows then press c."
            return
        name = prompt_input(stdscr, f"New category name under group '{g}' (ASCII):")
        name = name.strip()
        if not name:
            status = "Canceled new category."
            return

        if name not in cats:
            cats.append(name)

        groups.setdefault(g, [])
        if name not in groups[g]:
            groups[g].append(name)

        ensure_other_uncategorized(groups)
        rebuild_groups_sorted()
        cats_in_group = sorted(groups[g])
        c_idx = cats_in_group.index(name)
        status = f"Created category: {name} under {g}"

    def draw(stdscr) -> None:
        nonlocal merchant_scroll

        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 12 or w < 50:
            safe_addstr(stdscr, 0, 0, "Terminal too small. Resize bigger.")
            safe_addstr(stdscr, 2, 0, f"Current size: {w}x{h}")
            safe_addstr(stdscr, h - 1, 0, "q to quit (saves on quit)")
            stdscr.refresh()
            return

        top_h = max(8, h // 2)
        bot_h = h - top_h - 1

        safe_addstr(stdscr, 0, 0, "Groups / Categories" + (" (FOCUS)" if focus == "taxonomy" else ""))
        safe_addstr(stdscr, top_h, 0, "Unmatched merchants" + (" (FOCUS)" if focus == "merchants" else ""))

        row = 1
        if not group_names:
            safe_addstr(stdscr, row, 0, "(no groups) press g to add a group")
        else:
            for gi, g in enumerate(group_names):
                if row >= top_h:
                    break
                g_sel = (focus == "taxonomy" and gi == g_idx)
                g_attr = curses.A_REVERSE if g_sel else 0
                safe_addstr(stdscr, row, 0, ("> " if g_sel else "  ") + g, g_attr)
                row += 1

                cats_in_group = sorted(groups.get(g, []))
                for ci, c in enumerate(cats_in_group):
                    if row >= top_h:
                        break
                    c_sel = (focus == "taxonomy" and gi == g_idx and ci == c_idx)
                    c_attr = curses.A_BOLD if c_sel else 0
                    prefix = "    -> " if c_sel else "       "
                    safe_addstr(stdscr, row, 0, prefix + c, c_attr)
                    row += 1

        start_row = top_h + 1
        if not merchants:
            safe_addstr(stdscr, start_row, 0, "(no unmatched merchants)")
        else:
            merchant_idx_clamped = max(0, min(merchant_idx, len(merchants) - 1))
            max_visible = max(1, bot_h)

            if merchant_idx_clamped < merchant_scroll:
                merchant_scroll = merchant_idx_clamped
            if merchant_idx_clamped >= merchant_scroll + max_visible:
                merchant_scroll = merchant_idx_clamped - max_visible + 1

            for i in range(max_visible):
                mi = merchant_scroll + i
                if mi >= len(merchants):
                    break
                item = merchants[mi]
                is_sel = (focus == "merchants" and mi == merchant_idx_clamped)
                attr = curses.A_REVERSE if is_sel else 0

                left = f"{item.merchant} ({item.count})"
                right = item.example
                line = left if not right else (left + "   " + right)
                safe_addstr(stdscr, start_row + i, 0, line, attr)

        safe_addstr(stdscr, h - 1, 0, status, curses.A_DIM)
        stdscr.refresh()

    def run(stdscr) -> int:
        nonlocal focus, g_idx, c_idx, merchant_idx, status

        curses.curs_set(0)
        stdscr.nodelay(False)
        stdscr.keypad(True)

        rebuild_groups_sorted()
        ensure_other_uncategorized(groups)

        while True:
            draw(stdscr)
            ch = stdscr.getch()

            if ch in (ord("q"), ord("Q")):
                ensure_other_uncategorized(groups)
                write_categories(cats_path, cats)
                write_groups(groups_path, groups)
                write_rules(rules_path, rules)
                return 0

            if ch == 9:  # TAB
                focus = "taxonomy" if focus == "merchants" else "merchants"
                status = "Focus: " + focus
                continue

            if ch in (ord("g"), ord("G")):
                add_group(stdscr)
                rebuild_groups_sorted()
                continue

            if ch in (ord("c"), ord("C")):
                add_category(stdscr)
                rebuild_groups_sorted()
                continue

            if ch == ord("D"):
                delete_category(stdscr)
                rebuild_groups_sorted()
                continue

            if ch == ord("X"):
                delete_group(stdscr)
                rebuild_groups_sorted()
                continue

            if ch in (10, 13):  # Enter
                if focus == "merchants":
                    assign_current()
                else:
                    status = "TAB to merchants, then Enter assigns."
                continue

            if focus == "taxonomy":
                if ch == curses.KEY_UP:
                    if not group_names:
                        continue
                    g = group_names[g_idx]
                    cats_in_group = sorted(groups.get(g, []))
                    if cats_in_group and c_idx > 0:
                        c_idx -= 1
                    else:
                        if g_idx > 0:
                            g_idx -= 1
                            g2 = group_names[g_idx]
                            cats2 = sorted(groups.get(g2, []))
                            c_idx = min(c_idx, max(0, len(cats2) - 1))
                    continue

                if ch == curses.KEY_DOWN:
                    if not group_names:
                        continue
                    g = group_names[g_idx]
                    cats_in_group = sorted(groups.get(g, []))
                    if cats_in_group and c_idx < len(cats_in_group) - 1:
                        c_idx += 1
                    else:
                        if g_idx < len(group_names) - 1:
                            g_idx += 1
                            g2 = group_names[g_idx]
                            cats2 = sorted(groups.get(g2, []))
                            c_idx = min(c_idx, max(0, len(cats2) - 1))
                    continue

                if ch == curses.KEY_LEFT:
                    c_idx = 0
                    continue

                if ch == curses.KEY_RIGHT:
                    if not group_names:
                        continue
                    g = group_names[g_idx]
                    cats_in_group = sorted(groups.get(g, []))
                    if cats_in_group:
                        c_idx = min(c_idx, len(cats_in_group) - 1)
                    continue

            else:  # merchants focus
                if ch == curses.KEY_UP:
                    if merchants:
                        merchant_idx = max(0, merchant_idx - 1)
                    continue
                if ch == curses.KEY_DOWN:
                    if merchants:
                        merchant_idx = min(len(merchants) - 1, merchant_idx + 1)
                    continue
                if ch == curses.KEY_PPAGE:
                    if merchants:
                        merchant_idx = max(0, merchant_idx - 10)
                    continue
                if ch == curses.KEY_NPAGE:
                    if merchants:
                        merchant_idx = min(len(merchants) - 1, merchant_idx + 10)
                    continue

    return curses.wrapper(run)


def cmd_assign_tui_entry(argv: List[str]) -> int:
    return cmd_assign_tui(argv)