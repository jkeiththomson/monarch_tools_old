from __future__ import annotations

import argparse
import curses
import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# ---------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------

@dataclass
class Tx:
    num: int
    statement_date: str
    txn_date: str
    amount: str
    description: str
    category: str
    group: str
    raw: dict


# ---------------------------------------------------------------------
# File loading / saving
# ---------------------------------------------------------------------

def load_categories(path: Path) -> List[str]:
    if not path.exists():
        return []
    out: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(line)
    return out


def load_groups(path: Path) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    if not path.exists():
        return groups

    cur: Optional[str] = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if not line.startswith(" "):
            # Group line "Name:" or "Name"
            g = line.strip()
            if g.endswith(":"):
                g = g[:-1].strip()
            cur = g
            groups.setdefault(cur, [])
        else:
            if cur is None:
                continue
            c = line.strip()
            if c:
                groups[cur].append(c)
    return groups


def save_groups(path: Path, groups: Dict[str, List[str]]) -> None:
    parts: List[str] = []
    for g in sorted(groups.keys(), key=lambda x: x.lower()):
        parts.append(f"{g}:")
        cats = sorted(groups[g], key=lambda x: x.lower())
        for c in cats:
            parts.append(f"  {c}")
        parts.append("")
    path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")


def load_rules(path: Path) -> List[dict]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, list):
        return data
    return []


def save_rules(path: Path, rules: List[dict]) -> None:
    path.write_text(json.dumps(rules, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_transactions_csv(path: Path) -> Tuple[List[str], List[Tx]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        fieldnames = r.fieldnames or []
        rows = list(r)

    txs: List[Tx] = []

    def get(row: dict, *keys: str) -> str:
        for k in keys:
            if k in row and row[k] is not None:
                return str(row[k])
        return ""

    for i, row in enumerate(rows):
        stmt = get(row, "statement_date", "StatementDate", "StmtDate")
        txn = get(row, "txn_date", "TxnDate", "date", "Date")
        amt = get(row, "amount", "Amount")
        desc = get(row, "description", "Description", "merchant", "Merchant", "name", "Name")
        cat = get(row, "category", "Category")
        grp = get(row, "group", "Group")

        txs.append(
            Tx(
                num=i + 1,
                statement_date=stmt,
                txn_date=txn,
                amount=amt,
                description=desc,
                category=cat,
                group=grp,
                raw=row,
            )
        )

    return fieldnames, txs


def save_transactions_csv(path: Path, fieldnames: List[str], txs: List[Tx]) -> None:
    # Preserve original columns if possible, but ensure category/group exist.
    fns = list(fieldnames)
    for must in ("category", "group"):
        if must not in fns:
            fns.append(must)

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fns)
        w.writeheader()
        for t in txs:
            row = dict(t.raw)
            row["category"] = t.category
            row["group"] = t.group
            w.writerow(row)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def autocomplete_suffix(prefix: str, options: List[str]) -> str:
    p = (prefix or "").strip()
    if not p:
        return ""
    pl = p.lower()
    for opt in options:
        if opt.lower().startswith(pl):
            return opt[len(p):]
    return ""


def ensure_uncategorized(cats: List[str], groups: Dict[str, List[str]]) -> None:
    if not any(c.lower() == "uncategorized" for c in cats):
        cats.insert(0, "Uncategorized")

    # Ensure group "Other" exists and contains Uncategorized
    if "Other" not in groups:
        groups["Other"] = []
    if not any(c.lower() == "uncategorized" for c in groups["Other"]):
        groups["Other"].insert(0, "Uncategorized")

    # Remove Uncategorized from any other group
    for g in list(groups.keys()):
        if g == "Other":
            continue
        groups[g] = [c for c in groups[g] if c.lower() != "uncategorized"]


def ensure_category_in_group(category: str, group: str, cats: List[str], groups: Dict[str, List[str]]) -> None:
    category = (category or "").strip()
    group = (group or "").strip()
    if not category or not group:
        return

    if not any(c.lower() == category.lower() for c in cats):
        cats.append(category)

    if group not in groups:
        groups[group] = []

    # Remove category from other groups
    for g in list(groups.keys()):
        if g == group:
            continue
        groups[g] = [c for c in groups[g] if c.lower() != category.lower()]

    if not any(c.lower() == category.lower() for c in groups[group]):
        groups[group].append(category)


def cattr_for(t: Tx, has_colors: bool) -> int:
    # Color by assignment status
    cat = (t.category or "").strip()
    grp = (t.group or "").strip()
    if has_colors:
        if cat and grp:
            return curses.color_pair(3) | curses.A_BOLD
        if cat or grp:
            return curses.color_pair(2) | curses.A_BOLD
        return curses.color_pair(1) | curses.A_BOLD
    else:
        if cat and grp:
            return curses.A_BOLD
        return curses.A_NORMAL


# ---------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------

def cmd_categorize(cmd_argv: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="monarch-tools categorize")
    ap.add_argument("--in", dest="in_csv", required=True)
    ap.add_argument("--rules", dest="rules", required=True)
    ap.add_argument("--categories", dest="categories", required=True)
    ap.add_argument("--groups", dest="groups", required=True)
    ap.add_argument("--out", dest="out_csv", default="")
    ns = ap.parse_args(cmd_argv)

    in_csv = Path(ns.in_csv)
    out_csv = Path(ns.out_csv) if ns.out_csv else in_csv

    rules_path = Path(ns.rules)
    cats_path = Path(ns.categories)
    groups_path = Path(ns.groups)

    fieldnames, txs = load_transactions_csv(in_csv)
    cats = load_categories(cats_path)
    groups = load_groups(groups_path)
    rules = load_rules(rules_path)

    ensure_uncategorized(cats, groups)

    # UI state
    sel = 0          # absolute index into txs
    scroll = 0       # absolute top index into txs
    field = "cat"    # "cat" or "grp"
    editing = False
    buf = ""
    cur = 0
    status = ""

    def draw(stdscr) -> None:
        nonlocal scroll, status, sel, field, editing, buf

        stdscr.erase()
        h, w = stdscr.getmaxyx()
        top_h = max(10, min(18, h // 3))
        bot_h = h - top_h
        bot_y = top_h
        table_w = w - 1

        # Build sorted category list (CatID order)
        cats_sorted = sorted(cats, key=lambda x: x.lower())

        # TOP
        stdscr.addstr(0, 0, "Categories / Groups", curses.A_BOLD)
        x = 0
        y = 2
        col_w = max(20, min(36, w // 3))
        max_y = top_h - 2

        # Group listing
        for g in sorted(groups.keys(), key=lambda x: x.lower()):
            if y >= max_y:
                x += col_w
                y = 2
            if x >= w - 10:
                break
            stdscr.addstr(y, x, f"{g}:", curses.A_BOLD)
            y += 1
            for c in sorted(groups[g], key=lambda z: z.lower()):
                if y >= max_y:
                    x += col_w
                    y = 2
                if x >= w - 10:
                    break
                stdscr.addstr(y, x, f"  {c}"[: col_w - 1])
                y += 1

        # TRANSACTIONS
        if bot_h <= 3:
            stdscr.addstr(top_h, 0, "Terminal too small. Resize taller.", curses.A_BOLD)
            stdscr.refresh()
            return

        try:
            stdscr.addstr(top_h, 0, (" " * w))
        except curses.error:
            pass

        header = "Num  StmtDate     TxnDate      Amount      Description                           Category               Group"
        stdscr.addstr(bot_y, 0, header[: table_w], curses.A_BOLD)

        visible_n = bot_h - 2

        # Keep scroll aligned to selection
        if sel < scroll:
            scroll = sel
        if sel >= scroll + visible_n:
            scroll = sel - visible_n + 1

        # Column widths (constant)
        cat_w = max(16, min(28, max((len(c) for c in cats_sorted), default=12)))
        grp_w = max(12, min(24, max((len(g) for g in groups.keys()), default=5)))

        # Column starts (aligned with header format)
        cat_x = 3 + 2 + 10 + 2 + 10 + 2 + 10 + 2 + 35 + 2
        grp_x = cat_x + cat_w + 2

        # Draw rows
        has_colors = curses.has_colors()
        for i in range(visible_n):
            idx = scroll + i
            y = bot_y + 1 + i
            if idx >= len(txs):
                break

            t = txs[idx]
            base_attr = cattr_for(t, has_colors)
            if idx == sel:
                base_attr |= curses.A_BOLD

            num = f"{idx+1:>3d}"
            stmt = f"{(t.statement_date or ''):10.10s}"
            txd = f"{(t.txn_date or ''):10.10s}"
            amt = f"{(t.amount or ''):>10.10s}"
            desc = ((t.description or "")[:35]).ljust(35)

            cat_val = (t.category or "")
            grp_val = (t.group or "")

            cat_cell = cat_val[:cat_w].ljust(cat_w)
            grp_cell = grp_val[:grp_w].ljust(grp_w)

            if idx == sel and editing:
                if field == "cat":
                    cat_cell = buf[:cat_w].ljust(cat_w)
                else:
                    grp_cell = buf[:grp_w].ljust(grp_w)

            line = f"{num}  {stmt}  {txd}  {amt}  {desc}  {cat_cell}  {grp_cell}"
            stdscr.addstr(y, 0, line[: table_w], base_attr)

        # Focused cell highlight (FIXED: sel is absolute; convert to screen-relative)
        has_focus = True
        if has_focus and bot_h >= 3:
            sel_row = sel - scroll
            if 0 <= sel_row < visible_n and 0 <= sel < len(txs):
                y = bot_y + 1 + sel_row

                focus_base = curses.A_REVERSE | curses.A_BOLD
                if curses.has_colors():
                    focus_base = curses.color_pair(4) | curses.A_BOLD

                tsel = txs[sel]
                cat_text = (tsel.category or "")
                grp_text = (tsel.group or "")

                if editing and field == "cat":
                    suf = autocomplete_suffix(buf, cats)
                    cat_text = buf + suf
                if editing and field == "grp":
                    suf = autocomplete_suffix(buf, list(groups.keys()))
                    grp_text = buf + suf

                if field == "cat":
                    suf = ""
                    typed = cat_text
                    if editing:
                        suf = autocomplete_suffix(buf, cats)
                        typed = buf
                    typed = typed[:cat_w]
                    suf = suf[: max(0, cat_w - len(typed))]
                    stdscr.addstr(
                        y,
                        cat_x,
                        typed.ljust(cat_w)[: max(0, min(cat_w, table_w - cat_x))],
                        focus_base,
                    )
                    if suf and (cat_x + len(typed)) < table_w:
                        stdscr.addstr(y, cat_x + len(typed), suf, focus_base | curses.A_DIM)
                else:
                    suf = ""
                    typed = grp_text
                    if editing:
                        suf = autocomplete_suffix(buf, list(groups.keys()))
                        typed = buf
                    typed = typed[:grp_w]
                    suf = suf[: max(0, grp_w - len(typed))]
                    stdscr.addstr(
                        y,
                        grp_x,
                        typed.ljust(grp_w)[: max(0, min(grp_w, table_w - grp_x))],
                        focus_base,
                    )
                    if suf and (grp_x + len(typed)) < table_w:
                        stdscr.addstr(y, grp_x + len(typed), suf, focus_base | curses.A_DIM)

        # Footer / status
        help_text = "Arrows=move  Tab=switch field  Enter=confirm  e=edit  ESC=save/quit"
        left = status or ""
        right = help_text
        if len(left) + 3 + len(right) > w:
            right = right[: max(0, w - len(left) - 3)]
        line = (left + (" " * 3) + right)[: w - 1]
        try:
            stdscr.addstr(h - 1, 0, line)
        except curses.error:
            pass

        stdscr.refresh()

    def run(stdscr) -> int:
        nonlocal sel, field, editing, buf, cur, status, scroll

        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_RED, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_GREEN, -1)
            curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)

        curses.curs_set(1)
        stdscr.keypad(True)

        sel = 0
        field = "cat"
        editing = False
        buf = ""
        cur = 0
        esc_armed = False
        scroll = 0

        while True:
            draw(stdscr)
            ch = stdscr.getch()

            # ESC-armed commands (ESC then q/s)
            if ch == 27:  # ESC
                esc_armed = True
                status = "ESC: press q to quit, s to save."
                continue

            if esc_armed:
                if ch in (ord("q"), ord("Q")):
                    status = "Quit."
                    return 0
                if ch in (ord("s"), ord("S")):
                    status = "Saved."
                    return 0
                esc_armed = False
                status = ""

            # Editing mode
            if editing:
                if ch in (curses.KEY_ENTER, 10, 13):
                    # Commit typed buffer
                    if field == "cat":
                        txs[sel].category = buf.strip()
                    else:
                        txs[sel].group = buf.strip()
                    editing = False
                    buf = ""
                    continue

                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    buf = buf[:-1]
                    continue

                if ch == 9:  # Tab
                    # Switch field while editing
                    if field == "cat":
                        txs[sel].category = buf.strip()
                        field = "grp"
                        buf = txs[sel].group or ""
                    else:
                        txs[sel].group = buf.strip()
                        field = "cat"
                        buf = txs[sel].category or ""
                    continue

                if 32 <= ch <= 126:
                    buf += chr(ch)
                    continue

                continue

            # Not editing
            if ch == curses.KEY_UP:
                sel = max(0, sel - 1)
            elif ch == curses.KEY_DOWN:
                sel = min(len(txs) - 1, sel + 1)
            elif ch == 9:  # Tab
                field = "grp" if field == "cat" else "cat"
            elif ch in (ord("e"), ord("E")):
                editing = True
                buf = (txs[sel].category if field == "cat" else txs[sel].group) or ""
            elif ch in (curses.KEY_ENTER, 10, 13):
                # Confirm row: enforce taxonomy (category belongs to exactly one group)
                t = txs[sel]
                cat = (t.category or "").strip()
                grp = (t.group or "").strip()
                if cat and grp:
                    ensure_category_in_group(cat, grp, cats, groups)
                    status = "Confirmed."
                    # Move to next row
                    sel = min(len(txs) - 1, sel + 1)
                else:
                    status = "Need both Category and Group."
            elif ch in (ord("a"), ord("A")):
                # Accept autocomplete suggestion (quick)
                if field == "cat":
                    src = txs[sel].category or ""
                    suf = autocomplete_suffix(src, cats)
                    if suf:
                        txs[sel].category = src + suf
                else:
                    src = txs[sel].group or ""
                    suf = autocomplete_suffix(src, list(groups.keys()))
                    if suf:
                        txs[sel].group = src + suf

        # unreachable
        # return 0

    curses.wrapper(run)

    # Save outputs
    save_rules(rules_path, rules)
    cats_path.write_text("\n".join(cats).rstrip() + "\n", encoding="utf-8")
    save_groups(groups_path, groups)
    save_transactions_csv(out_csv, fieldnames, txs)

    return 0