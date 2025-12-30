from __future__ import annotations

import argparse
import csv
import curses
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# ----------------------------
# File formats / utilities
# ----------------------------

def normalize_merchant(s: str) -> str:
    # Keep it simple + stable: uppercase + collapse whitespace
    return " ".join((s or "").strip().upper().split())


def load_rules(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    # Support either {"merchants": {...}} or flat dict
    if isinstance(data, dict) and "merchants" in data and isinstance(data["merchants"], dict):
        return {str(k): str(v) for k, v in data["merchants"].items()}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    return {}


def save_rules(path: Path, merchants: Dict[str, str]) -> None:
    payload = {"merchants": merchants}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_categories(path: Path) -> List[str]:
    if not path.exists():
        return ["Uncategorized"]
    cats: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cats.append(line)
    if "Uncategorized" not in cats:
        cats.append("Uncategorized")
    # preserve order but de-dupe (case-insensitive)
    seen = set()
    out = []
    for c in cats:
        k = c.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out


def save_categories(path: Path, cats: List[str]) -> None:
    # Keep Uncategorized present, last
    cats2 = [c for c in cats if c.lower() != "uncategorized"]
    cats2.sort(key=lambda x: x.lower())
    cats2.append("Uncategorized")
    path.write_text("\n".join(cats2) + "\n", encoding="utf-8")


def load_groups(path: Path) -> Dict[str, List[str]]:
    # groups.txt format:
    # Group:
    #   Cat
    #   Cat
    if not path.exists():
        return {}
    groups: Dict[str, List[str]] = {}
    cur: Optional[str] = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")) and line.endswith(":"):
            cur = line[:-1].strip()
            if cur:
                groups.setdefault(cur, [])
            continue
        if cur is None:
            continue
        cat = line.strip()
        if cat:
            groups.setdefault(cur, []).append(cat)
    # de-dupe cats in each group
    for g in list(groups.keys()):
        seen = set()
        new = []
        for c in groups[g]:
            k = c.lower()
            if k in seen:
                continue
            seen.add(k)
            new.append(c)
        groups[g] = new
    return groups


def save_groups(path: Path, groups: Dict[str, List[str]]) -> None:
    # Sort groups, cats
    parts: List[str] = []
    for g in sorted(groups.keys(), key=lambda x: x.lower()):
        parts.append(f"{g}:")
        cats = sorted(groups[g], key=lambda x: x.lower())
        for c in cats:
            parts.append(f"  {c}")
        parts.append("")
    text = "\n".join(parts).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")


def move_category_to_group(groups: Dict[str, List[str]], group: str, category: str) -> None:
    # Ensure category belongs to exactly one group
    for g, cats in groups.items():
        groups[g] = [c for c in cats if c.lower() != category.lower()]
    groups.setdefault(group, [])
    if not any(c.lower() == category.lower() for c in groups[group]):
        groups[group].append(category)


def find_existing(name: str, pool: List[str]) -> str:
    lo = name.lower()
    for x in pool:
        if x.lower() == lo:
            return x
    return name


def find_existing_key(name: str, keys: List[str]) -> str:
    lo = name.lower()
    for x in keys:
        if x.lower() == lo:
            return x
    return name


# ----------------------------
# Domain model
# ----------------------------

@dataclass
class Tx:
    statement_date: str
    txn_date: str
    description: str
    amount: str
    category: str
    group: str

    # UI state
    status: str  # "red" | "yellow" | "green"
    suggested_category: str = ""
    suggested_group: str = ""


def load_transactions_csv(path: Path) -> Tuple[List[Dict[str, str]], List[Tx]]:
    rows: List[Dict[str, str]] = []
    txs: List[Tx] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
            txs.append(
                Tx(
                    statement_date=r.get("statement_date", r.get("StatementDate", "")) or "",
                    txn_date=r.get("date", r.get("TxnDate", "")) or "",
                    description=r.get("description", r.get("Merchant", r.get("Description", ""))) or "",
                    amount=r.get("amount", r.get("Amount", "")) or "",
                    category=r.get("category", r.get("Category", "")) or "",
                    group=r.get("group", r.get("Group", "")) or "",
                    status="red",
                )
            )
    return rows, txs


def write_transactions_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # Ensure columns exist
    for r in rows:
        r.setdefault("category", "")
        r.setdefault("group", "")
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def apply_auto_suggestions(
    txs: List[Tx],
    rules: Dict[str, str],
    groups: Dict[str, List[str]],
) -> None:
    # Build cat->group lookup (first match wins)
    cat_to_group: Dict[str, str] = {}
    for g, cats in groups.items():
        for c in cats:
            cat_to_group.setdefault(c.lower(), g)

    for t in txs:
        t.suggested_category = ""
        t.suggested_group = ""

        if t.category and t.group:
            t.status = "green"
            continue

        merch = normalize_merchant(t.description)
        if merch and merch in rules:
            cat = rules[merch]
            grp = cat_to_group.get(cat.lower(), "")
            t.suggested_category = cat
            t.suggested_group = grp
            # show as yellow until confirmed
            if not t.category:
                t.category = cat
            if not t.group and grp:
                t.group = grp
            t.status = "yellow"
        else:
            t.status = "red"


# ----------------------------
# Curses UI
# ----------------------------

def cmd_categorize(argv: List[str]) -> int:
    """
    Categorize transactions using rules + taxonomy (interactive TUI).
    """
    ap = argparse.ArgumentParser(prog="monarch-tools categorize")
    ap.add_argument("--in", dest="in_csv", required=True, help="Input transactions CSV (out/*.monarch.csv)")
    ap.add_argument("--rules", required=True, help="Path to rules.json")
    ap.add_argument("--categories", required=True, help="Path to categories.txt")
    ap.add_argument("--groups", required=True, help="Path to groups.txt")
    ap.add_argument("--out", dest="out_csv", default="", help="Optional output CSV path (defaults to overwrite --in)")
    ns = ap.parse_args(argv)

    in_csv = Path(ns.in_csv)
    rules_path = Path(ns.rules)
    cats_path = Path(ns.categories)
    groups_path = Path(ns.groups)
    out_csv = Path(ns.out_csv) if ns.out_csv else in_csv

    rows, txs = load_transactions_csv(in_csv)
    cats = load_categories(cats_path)
    groups = load_groups(groups_path)
    rules = load_rules(rules_path)

    apply_auto_suggestions(txs, rules, groups)

    # --- UI state ---
    sel = 0
    scroll = 0
    field = "cat"  # "cat" or "grp"
    editing = False
    buf = ""
    cur = 0
    status = "Arrows move. Type to edit. Enter confirms. TAB switches Cat/Grp. s=save, q=quit."

    def cancel_edit() -> None:
        nonlocal editing, buf, cur
        editing = False
        buf = ""
        cur = 0

    def begin_edit() -> None:
        nonlocal editing, buf, cur
        editing = True
        buf = (txs[sel].category if field == "cat" else txs[sel].group) or ""
        cur = len(buf)

    def clear_focused() -> None:
        nonlocal status
        t = txs[sel]
        if field == "cat":
            t.category = ""
        else:
            t.group = ""
        t.status = "red"
        status = "Cleared."

    def confirm_row() -> None:
        """Confirm current row if valid; update rules+taxonomy; mark green and advance."""
        nonlocal sel, field, status
        t = txs[sel]
        cat = (t.category or "").strip()
        grp = (t.group or "").strip()

        if not cat:
            t.status = "red"
            field = "cat"
            status = "Category required."
            return

        # Canonicalize category (case-insensitive), creating if needed
        cat = find_existing(cat, cats)
        if cat.lower() not in [c.lower() for c in cats]:
            cats.append(cat)

        # Group required for confirmation
        if not grp:
            t.status = "yellow"
            field = "grp"
            status = "Group required."
            t.category = cat
            return

        grp = find_existing_key(grp, list(groups.keys()))
        if grp not in groups:
            groups[grp] = []

        move_category_to_group(groups, grp, cat)

        # Update rule on confirmation
        merch = normalize_merchant(t.description)
        if merch:
            rules[merch] = cat

        # Persist into backing rows dict
        rows[sel]["category"] = cat
        rows[sel]["group"] = grp

        t.category = cat
        t.group = grp
        t.status = "green"

        # Advance
        if sel < len(txs) - 1:
            sel += 1
        field = "cat"
        status = f"Confirmed: {cat} / {grp}"

    def draw(stdscr) -> None:
        nonlocal scroll, status
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        # Colors
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_RED, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_GREEN, -1)
            curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)  # focused cell

        def cattr_for(t: Tx) -> int:
            if not curses.has_colors():
                return 0
            if t.status == "green":
                return curses.color_pair(3)
            if t.status == "yellow":
                return curses.color_pair(2)
            return curses.color_pair(1)

        # Taxonomy lines
        tax_lines: List[str] = []
        for g in sorted(groups.keys(), key=lambda x: x.lower()):
            tax_lines.append(f"{g}:")
            for c in sorted(groups[g], key=lambda x: x.lower()):
                tax_lines.append(f"  {c}")
            tax_lines.append("")
        if not tax_lines:
            tax_lines = ["(no groups yet)", ""]
        while tax_lines and tax_lines[-1] == "":
            tax_lines.pop()

        # Dynamic split
        top_h = min(h // 2, max(3, len(tax_lines) + 1))
        bot_y = top_h
        bot_h = h - bot_y

        # Taxonomy header
        stdscr.addstr(0, 0, "TAXONOMY", curses.A_BOLD)
        for i, line in enumerate(tax_lines[: top_h - 1], start=1):
            stdscr.addstr(i, 0, line[: w - 1])

        # Transactions header
        if bot_h <= 3:
            stdscr.addstr(top_h, 0, "Terminal too small. Resize taller.", curses.A_BOLD)
            stdscr.refresh()
            return

        header = "Num  StmtDate     TxnDate      Amount      Description                           Category               Group"
        stdscr.addstr(bot_y, 0, header[: w - 1], curses.A_BOLD)

        # Visible rows
        visible = bot_h - 2
        if sel < scroll:
            scroll = sel
        if sel >= scroll + visible:
            scroll = sel - visible + 1

        # Column widths (constant)
        cat_w = max(16, min(28, max((len(c) for c in cats), default=12)))
        grp_w = max(12, min(24, max((len(g) for g in groups.keys()), default=5)))

        # compute start columns based on header pieces
        # We'll format the line ourselves so we can re-draw the focused cell segment.
        for i in range(visible):
            idx = scroll + i
            y = bot_y + 1 + i
            if idx >= len(txs):
                break
            t = txs[idx]
            base_attr = cattr_for(t)
            if idx == sel:
                base_attr |= curses.A_BOLD

            num = f"{idx+1:>3d}"
            stmt = f"{t.statement_date:10.10s}"
            txd = f"{t.txn_date:10.10s}"
            amt = f"{t.amount:>10.10s}"
            desc = (t.description or "")[:35].ljust(35)
            cat = (t.category or "")[:cat_w].ljust(cat_w)
            grp = (t.group or "")[:grp_w].ljust(grp_w)

            # If editing selected field, show live buffer in that cell
            if idx == sel and editing:
                live = (buf[:cat_w] if field == "cat" else buf[:grp_w])
                if field == "cat":
                    cat = live.ljust(cat_w)
                else:
                    grp = live.ljust(grp_w)

            line = f"{num}  {stmt}  {txd}  {amt}  {desc}  {cat}  {grp}"
            stdscr.addstr(y, 0, line[: w - 1], base_attr)

            # Focused cell highlight
            if idx == sel and curses.has_colors():
                focus_attr = curses.color_pair(4) | curses.A_BOLD
                # Calculate x positions
                # prefix: num(3)+2 + stmt(10)+2 + txd(10)+2 + amt(10)+2 + desc(35)+2 = 3+2+10+2+10+2+10+2+35+2 = 78
                cat_x = 78
                grp_x = cat_x + cat_w + 2
                if field == "cat":
                    stdscr.addstr(y, cat_x, cat[: min(cat_w, w - 1 - cat_x)], focus_attr)
                else:
                    stdscr.addstr(y, grp_x, grp[: min(grp_w, w - 1 - grp_x)], focus_attr)

        # Status line
        stdscr.addstr(h - 1, 0, (" " + status)[: w - 1])

        # Put cursor inside the focused cell during editing (best-effort)
        if editing:
            cat_x = 78
            grp_x = cat_x + cat_w + 2
            x0 = cat_x if field == "cat" else grp_x
            maxw = cat_w if field == "cat" else grp_w
            stdscr.move(bot_y + 1 + (sel - scroll), min(x0 + cur, x0 + maxw - 1))

        stdscr.refresh()

    def run(stdscr) -> int:
        nonlocal sel, field, editing, buf, cur, status

        curses.curs_set(1)
        stdscr.keypad(True)

        # Start focused on Cat in first transaction
        sel = 0
        field = "cat"
        editing = False
        buf = ""
        cur = 0

        while True:
            draw(stdscr)
            ch = stdscr.getch()

            # Save / quit
            if ch in (ord("q"),):
                # simple confirm modal
                h, w = stdscr.getmaxyx()
                msg = "Quit without saving? (y/n)"
                stdscr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg, curses.A_REVERSE)
                stdscr.refresh()
                c2 = stdscr.getch()
                if c2 in (ord("y"), ord("Y")):
                    return 0
                status = "Continue."
                continue

            if ch in (ord("s"),):
                # write files
                write_transactions_csv(out_csv, rows)
                save_categories(cats_path, cats)
                save_groups(groups_path, groups)
                save_rules(rules_path, rules)
                status = f"Saved: {out_csv}"
                continue

            # Delete clears focused cell
            if ch in (curses.KEY_DC,):
                cancel_edit()
                clear_focused()
                continue

            # Tab / Shift-Tab switches field without saving pending edits
            if ch == 9 or ch == curses.KEY_BTAB:
                cancel_edit()
                field = "grp" if (field == "cat" and ch == 9) else ("cat" if (field == "grp" and ch == 9) else ("cat" if field == "grp" else "grp"))
                status = f"Field: {field}"
                continue

            # Movement cancels edit (per requirement)
            if ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
                cancel_edit()
                if ch == curses.KEY_UP:
                    sel = max(0, sel - 1)
                elif ch == curses.KEY_DOWN:
                    sel = min(len(txs) - 1, sel + 1)
                elif ch == curses.KEY_PPAGE:
                    sel = max(0, sel - 10)
                elif ch == curses.KEY_NPAGE:
                    sel = min(len(txs) - 1, sel + 10)
                continue

            # Left/Right: in edit mode move cursor, else switch field
            if ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
                if editing:
                    if ch == curses.KEY_LEFT:
                        cur = max(0, cur - 1)
                    else:
                        cur = min(len(buf), cur + 1)
                else:
                    field = "grp" if field == "cat" else "cat"
                continue

            # Enter confirms / commits
            if ch in (10, 13):
                if editing:
                    # Commit buffer into field (but do not confirm unless both valid)
                    val = buf.strip()
                    cancel_edit()
                    t = txs[sel]
                    if field == "cat":
                        if val:
                            val = find_existing(val, cats)
                            t.category = val
                            rows[sel]["category"] = val
                        # After Cat enter: if group invalid -> yellow and move to group
                        grp = (t.group or "").strip()
                        if grp and find_existing_key(grp, list(groups.keys())):
                            grp = find_existing_key(grp, list(groups.keys()))
                            t.group = grp
                            rows[sel]["group"] = grp
                            confirm_row()
                        else:
                            t.status = "yellow"
                            field = "grp"
                            status = "Group required."
                    else:
                        if val:
                            grp = find_existing_key(val, list(groups.keys()))
                            if grp not in groups:
                                groups[grp] = []
                            t.group = grp
                            rows[sel]["group"] = grp
                        # After Grp enter: if cat valid -> confirm else move to cat
                        cat = (t.category or "").strip()
                        if cat:
                            confirm_row()
                        else:
                            t.status = "yellow"
                            field = "cat"
                            status = "Category required."
                else:
                    # If yellow: Enter confirms and advances
                    t = txs[sel]
                    if t.status == "yellow":
                        confirm_row()
                    else:
                        # Green/red: Enter just advances to next row
                        if sel < len(txs) - 1:
                            sel += 1
                        field = "cat"
                continue

            # Backspace in edit mode
            if ch in (curses.KEY_BACKSPACE, 127, 8) and editing:
                if cur > 0:
                    buf = buf[: cur - 1] + buf[cur:]
                    cur -= 1
                continue

            # Start editing on printable chars
            if 32 <= ch <= 126 and ch not in (9, 10, 13):
                if not editing:
                    begin_edit()
                buf = buf[:cur] + chr(ch) + buf[cur:]
                cur += 1
                continue

            status = "Unknown key. Use arrows, type, Enter, TAB, s, q."

    try:
        return curses.wrapper(run)
    except curses.error as e:
        print(f"ERROR: {e}")
        print("Tip: resize terminal larger (e.g. >= 120x20) and try again.")
        return 2


if __name__ == "__main__":
    raise SystemExit(cmd_categorize([]))
