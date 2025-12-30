from __future__ import annotations

import argparse
import csv
import curses
import json
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ----------------------------
# ASCII + safe curses helpers
# ----------------------------

def _ascii(s: str) -> str:
    return (s or "").encode("ascii", "replace").decode("ascii")


def safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
    """Best-effort addstr that never raises for width/bounds."""
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        maxlen = max(0, w - x - 1)  # avoid last column curses ERR
        if maxlen <= 0:
            return
        win.addstr(y, x, _ascii(s)[:maxlen], attr)
    except Exception:
        return


def draw_modal_confirm(stdscr, lines: List[str], prompt: str = "Confirm? (y/n)") -> bool:
    """Centered modal confirm. Returns True for y, False for n/ESC."""
    h, w = stdscr.getmaxyx()
    body_w = max(len(prompt), *(len(l) for l in lines)) if lines else len(prompt)
    box_w = min(max(body_w + 4, 30), max(20, w - 4))
    box_h = min(max(len(lines) + 4, 7), max(7, h - 2))

    y0 = max(0, (h - box_h) // 2)
    x0 = max(0, (w - box_w) // 2)

    # Dim overlay
    for y in range(h):
        safe_addstr(stdscr, y, 0, " " * (w - 1), curses.A_DIM)

    win = curses.newwin(box_h, box_w, y0, x0)
    try:
        win.keypad(True)
        win.border()
        for i, line in enumerate(lines[: box_h - 4]):
            safe_addstr(win, 1 + i, 2, line)
        safe_addstr(win, box_h - 2, 2, prompt, curses.A_BOLD)
        win.refresh()

        while True:
            ch = win.getch()
            if ch in (ord("y"), ord("Y")):
                return True
            if ch in (ord("n"), ord("N"), 27):
                return False
    finally:
        try:
            del win
        except Exception:
            pass


# ----------------------------
# Normalization
# ----------------------------

_SPACE_RE = re.compile(r"\s+")
_NONPRINT_RE = re.compile(r"[^\x20-\x7E]")


def normalize_merchant(s: str) -> str:
    s = s or ""
    s = _NONPRINT_RE.sub(" ", s)
    s = s.strip()
    s = _SPACE_RE.sub(" ", s)
    return s.upper()


def normalize_name(s: str) -> str:
    return " ".join((s or "").strip().split())


def match_ci(name: str, options: List[str]) -> Optional[str]:
    n = normalize_name(name).lower()
    for o in options:
        if normalize_name(o).lower() == n:
            return o
    return None


# ----------------------------
# Rules / taxonomy persistence
# ----------------------------

@dataclass
class RulesData:
    version: int
    merchants: Dict[str, str]  # normalized_merchant -> category
    patterns: List[dict]


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
            m2[_ascii(k)] = _ascii(v)
    return RulesData(version=version, merchants=m2, patterns=list(patterns))


def write_rules(path: Path, rules: RulesData) -> None:
    out = {"version": rules.version, "merchants": rules.merchants, "patterns": rules.patterns}
    path.write_text(json.dumps(out, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def load_categories(path: Path) -> List[str]:
    if not path.exists():
        return ["Uncategorized"]
    cats: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        cats.append(_ascii(s))
    if match_ci("Uncategorized", cats) is None:
        cats.insert(0, "Uncategorized")
    seen = set()
    out: List[str] = []
    for c in cats:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def write_categories(path: Path, cats: List[str]) -> None:
    unc = match_ci("Uncategorized", cats) or "Uncategorized"
    rest = sorted([c for c in cats if normalize_name(c).lower() != "uncategorized"], key=lambda x: x.lower())
    out = [unc] + rest
    path.write_text("\n".join(_ascii(c) for c in out) + "\n", encoding="utf-8")


def load_groups(path: Path) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    if not path.exists():
        return groups
    current: Optional[str] = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.strip().endswith(":") and not line.startswith(" "):
            current = _ascii(line.strip()[:-1].strip())
            groups.setdefault(current, [])
            continue
        if current is None:
            continue
        cat = _ascii(line.strip())
        if cat:
            groups.setdefault(current, []).append(cat)
    for g in list(groups.keys()):
        seen = set()
        out: List[str] = []
        for c in groups[g]:
            if c not in seen:
                out.append(c)
                seen.add(c)
        groups[g] = out
    return groups


def write_groups(path: Path, groups: Dict[str, List[str]]) -> None:
    def sort_key(g: str) -> Tuple[int, str]:
        return (2, g.lower()) if g.lower() == "other" else (1, g.lower())

    lines: List[str] = []
    for g in sorted(groups.keys(), key=sort_key):
        lines.append(_ascii(g) + ":")
        for c in sorted(set(groups[g]), key=lambda x: x.lower()):
            lines.append("  " + _ascii(c))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def ensure_other_uncategorized(groups: Dict[str, List[str]]) -> None:
    other = match_ci("Other", list(groups.keys())) or "Other"
    groups.setdefault(other, [])
    if match_ci("Uncategorized", groups[other]) is None:
        groups[other].append("Uncategorized")


def remove_category_from_all_groups(groups: Dict[str, List[str]], cat: str) -> None:
    for g in list(groups.keys()):
        groups[g] = [c for c in groups[g] if normalize_name(c).lower() != normalize_name(cat).lower()]


def move_category_to_group(groups: Dict[str, List[str]], group: str, cat: str) -> None:
    remove_category_from_all_groups(groups, cat)
    group = match_ci(group, list(groups.keys())) or group
    groups.setdefault(group, [])
    if match_ci(cat, groups[group]) is None:
        groups[group].append(cat)
    ensure_other_uncategorized(groups)


def group_for_category(groups: Dict[str, List[str]], category: str) -> str:
    c = normalize_name(category).lower()
    for g, cats in groups.items():
        for cat in cats:
            if normalize_name(cat).lower() == c:
                return g
    return match_ci("Other", list(groups.keys())) or "Other"


# ----------------------------
# CSV IO (support both schemas)
# ----------------------------

def read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        fieldnames = list(r.fieldnames or [])
        rows: List[Dict[str, str]] = []
        for row in r:
            rows.append({(k or ""): (v or "") for k, v in row.items()})
    return fieldnames, rows


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            clean = {k: _ascii(str(row.get(k, ""))) for k in fieldnames}
            w.writerow(clean)


def get_date(row: Dict[str, str]) -> str:
    return (row.get("date") or row.get("Date") or "").strip()


def get_amount(row: Dict[str, str]) -> str:
    return (row.get("amount") or row.get("Amount") or "").strip()


def get_desc(row: Dict[str, str]) -> str:
    return (row.get("description") or row.get("Merchant") or row.get("Description") or "").strip()


def get_group(row: Dict[str, str]) -> str:
    return (row.get("group") or row.get("Group") or "").strip()


def get_category(row: Dict[str, str]) -> str:
    return (row.get("category") or row.get("Category") or "").strip()


def set_group(row: Dict[str, str], g: str) -> None:
    if "group" in row:
        row["group"] = g
    elif "Group" in row:
        row["Group"] = g
    else:
        row["group"] = g


def set_category(row: Dict[str, str], c: str) -> None:
    if "category" in row:
        row["category"] = c
    elif "Category" in row:
        row["Category"] = c
    else:
        row["category"] = c


def ensure_group_category_columns(fieldnames: List[str], rows: List[Dict[str, str]]) -> List[str]:
    fset = set(fieldnames)
    use_lower = "category" in fset or "group" in fset
    cat_key = "category" if use_lower else "Category"
    grp_key = "group" if use_lower else "Group"

    if cat_key not in fset:
        fieldnames.append(cat_key)
        fset.add(cat_key)
    if grp_key not in fset:
        fieldnames.append(grp_key)
        fset.add(grp_key)

    for row in rows:
        row.setdefault(cat_key, row.get("category") or row.get("Category") or "")
        row.setdefault(grp_key, row.get("group") or row.get("Group") or "")

    return fieldnames


# ----------------------------
# Categorize TUI
# ----------------------------

class Status:
    NONE = 0
    AUTO = 1
    MANUAL = 2


def cmd_categorize(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="monarch-tools categorize")
    ap.add_argument("--in", dest="in_csv", required=True, help="Input transactions CSV (out/*.monarch.csv)")
    ap.add_argument("--rules", required=True, help="Path to rules.json")
    ap.add_argument("--categories", required=True, help="Path to categories.txt")
    ap.add_argument("--groups", required=True, help="Path to groups.txt")
    ap.add_argument("--out", dest="out_csv", default="", help="Output categorized CSV (optional)")
    ap.add_argument("--unmatched", dest="unmatched_csv", default="", help="Output unmatched merchants CSV (optional)")
    ns = ap.parse_args(argv)

    in_csv = Path(ns.in_csv)
    rules_path = Path(ns.rules)
    cats_path = Path(ns.categories)
    groups_path = Path(ns.groups)

    fieldnames, rows = read_csv(in_csv)
    fieldnames = ensure_group_category_columns(fieldnames, rows)

    rules = load_rules(rules_path)
    cats = load_categories(cats_path)
    groups = load_groups(groups_path)
    ensure_other_uncategorized(groups)

    status: List[int] = [Status.NONE for _ in rows]

    # Auto-fill from rules where possible
    for i, row in enumerate(rows):
        m = normalize_merchant(get_desc(row))
        if not m:
            continue

        if get_category(row).strip():
            if normalize_name(get_category(row)).lower() != "uncategorized":
                status[i] = Status.MANUAL
            continue

        cat = rules.merchants.get(m, "")
        if cat:
            cat = match_ci(cat, cats) or cat
            if match_ci(cat, cats) is None:
                cats.append(cat)
            grp = group_for_category(groups, cat)
            set_category(row, cat)
            set_group(row, grp)
            status[i] = Status.AUTO

    out_csv = Path(ns.out_csv) if ns.out_csv else in_csv.with_suffix("").with_suffix(".categorized.csv")
    unmatched_csv = Path(ns.unmatched_csv) if ns.unmatched_csv else in_csv.with_suffix("").with_suffix(".unmatched_merchants.csv")

    sel = 0
    scroll = 0
    col = 0  # 0=Category, 1=Group

    edit_mode = False
    edit_buf = ""
    edit_pos = 0  # caret position within edit_buf
    digit_buf = ""

    # original values for active field; cancel restores
    edit_orig_cat = ""
    edit_orig_grp = ""

    undo: List[Tuple[RulesData, List[str], Dict[str, List[str]], List[Dict[str, str]], List[int]]] = []

    def push_undo() -> None:
        undo.append((deepcopy(rules), deepcopy(cats), deepcopy(groups), deepcopy(rows), list(status)))

    def do_undo() -> str:
        nonlocal rules, cats, groups, rows, status
        if not undo:
            return "Nothing to undo."
        rules, cats, groups, rows, status = undo.pop()
        ensure_other_uncategorized(groups)
        return "Undo."

    def rebuild_cat_id_map() -> Tuple[List[str], Dict[int, str]]:
        lines: List[str] = []
        cat_id_map: Dict[int, str] = {}
        cid = 1

        def gkey(g: str) -> Tuple[int, str]:
            return (2, g.lower()) if g.lower() == "other" else (1, g.lower())

        for g in sorted(groups.keys(), key=gkey):
            lines.append(g)
            for c in sorted(set(groups[g]), key=lambda x: x.lower()):
                lines.append("  %d) %s" % (cid, c))
                cat_id_map[cid] = c
                cid += 1
        return lines, cat_id_map

    def compute_col_widths() -> Tuple[int, int]:
        cat_max = max([len("Category")] + [len(c) for c in cats] + [len(get_category(r) or "") for r in rows])
        grp_max = max([len("Group")] + [len(g) for g in groups.keys()] + [len(get_group(r) or "") for r in rows])
        return min(48, max(12, cat_max + 2)), min(32, max(10, grp_max + 2))

    def row_color(i: int) -> int:
        c = normalize_name(get_category(rows[i]))
        g = normalize_name(get_group(rows[i]))
        if not c or c.lower() == "uncategorized" or not g:
            return Status.NONE
        return status[i]

    def is_valid_cat(cat: str) -> bool:
        c = normalize_name(cat)
        return bool(c) and c.lower() != "uncategorized"

    def is_valid_group(grp: str) -> bool:
        g = normalize_name(grp)
        if not g:
            return False
        return match_ci(g, list(groups.keys())) is not None

    def assign_category(i: int, cat: str, mark_manual: bool = True) -> str:
        nonlocal cats, groups
        cat = normalize_name(cat)
        if not cat:
            set_category(rows[i], "")
            set_group(rows[i], "")
            status[i] = Status.NONE
            return "Cleared."

        ex = match_ci(cat, cats)
        cat = ex or cat
        if match_ci(cat, cats) is None:
            cats.append(cat)

        grp = normalize_name(get_group(rows[i]))
        if grp:
            grp = match_ci(grp, list(groups.keys())) or grp
            groups.setdefault(grp, [])
            move_category_to_group(groups, grp, cat)
        else:
            grp = group_for_category(groups, cat)
            move_category_to_group(groups, grp, cat)

        set_category(rows[i], cat)
        set_group(rows[i], grp)
        status[i] = Status.MANUAL if mark_manual else Status.AUTO
        return "Set %s / %s" % (grp, cat)

    def assign_group(i: int, grp: str, mark_manual: bool = True) -> str:
        nonlocal groups, cats
        grp = normalize_name(grp)
        if not grp:
            cat = normalize_name(get_category(rows[i]))
            if cat and cat.lower() != "uncategorized":
                grp2 = group_for_category(groups, cat)
                set_group(rows[i], grp2)
                if mark_manual:
                    status[i] = Status.MANUAL
                return "Group -> %s" % grp2
            set_group(rows[i], "")
            status[i] = Status.NONE
            return "Cleared group."

        exg = match_ci(grp, list(groups.keys()))
        grp = exg or grp
        groups.setdefault(grp, [])

        cat = normalize_name(get_category(rows[i]))
        if cat and cat.lower() != "uncategorized":
            cat = match_ci(cat, cats) or cat
            if match_ci(cat, cats) is None:
                cats.append(cat)
            move_category_to_group(groups, grp, cat)
            set_group(rows[i], grp)
            if mark_manual:
                status[i] = Status.MANUAL
            return "Moved %s -> %s" % (cat, grp)

        set_group(rows[i], grp)
        if mark_manual:
            status[i] = Status.MANUAL
        return "Group -> %s" % grp

    def save_all() -> Tuple[Path, Path, int]:
        updated = 0
        for i, row in enumerate(rows):
            if status[i] != Status.MANUAL:
                continue
            cat = normalize_name(get_category(row))
            grp = normalize_name(get_group(row))
            if not cat or cat.lower() == "uncategorized" or not grp:
                continue
            m = normalize_merchant(get_desc(row))
            if not m:
                continue
            if rules.merchants.get(m) != cat:
                rules.merchants[m] = cat
                updated += 1

        write_csv(out_csv, fieldnames, rows)

        counts: Dict[str, int] = {}
        for row in rows:
            cat = normalize_name(get_category(row))
            grp = normalize_name(get_group(row))
            if not cat or cat.lower() == "uncategorized" or not grp:
                m = get_desc(row)
                if m:
                    counts[m] = counts.get(m, 0) + 1

        with unmatched_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Merchant", "Count"])
            for m in sorted(counts.keys()):
                w.writerow([_ascii(m), counts[m]])

        write_categories(cats_path, cats)
        write_groups(groups_path, groups)
        write_rules(rules_path, rules)
        return out_csv, unmatched_csv, updated

    def clamp() -> None:
        nonlocal sel, scroll
        if not rows:
            sel = 0
            scroll = 0
            return
        sel = max(0, min(sel, len(rows) - 1))

    def cancel_edit_restore() -> None:
        nonlocal edit_mode, edit_buf, edit_pos, digit_buf
        if not edit_mode:
            return
        if col == 0:
            set_category(rows[sel], edit_orig_cat)
        else:
            set_group(rows[sel], edit_orig_grp)
        edit_mode = False
        edit_buf = ""
        edit_pos = 0
        digit_buf = ""

    def begin_edit_with_initial(initial: str) -> None:
        nonlocal edit_mode, edit_buf, edit_pos, digit_buf, edit_orig_cat, edit_orig_grp
        edit_mode = True
        edit_buf = initial
        edit_pos = len(edit_buf)
        digit_buf = ""
        edit_orig_cat = get_category(rows[sel])
        edit_orig_grp = get_group(rows[sel])

    def draw(stdscr, msg: str) -> Dict[int, str]:
        nonlocal scroll
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        tax_lines, cat_id_map = rebuild_cat_id_map()
        cat_w, grp_w = compute_col_widths()

        # Dynamic top section height (remove the big blank gap under taxonomy)
        # Keep at least 4 rows for bottom headers/status.
        min_bottom = 14
        max_top = max(6, h - min_bottom)
        needed_top = min(len(tax_lines) + 1, max_top)  # +1 for title
        top_h = max(3, needed_top)
        bot_h = h - top_h - 1  # -1 status line

        if h < 18 or w < 100 or bot_h < 6:
            safe_addstr(stdscr, 0, 0, "Terminal too small. Resize larger (suggested >= 100x18).", curses.A_BOLD)
            safe_addstr(stdscr, 1, 0, "Current size: %dx%d" % (w, h), curses.A_BOLD)
            stdscr.refresh()
            return {}

        safe_addstr(stdscr, 0, 0, "Groups / Categories (CatID):", curses.A_BOLD)
        for i in range(min(top_h - 1, len(tax_lines))):
            safe_addstr(stdscr, 1 + i, 0, tax_lines[i])

        y0 = top_h
        safe_addstr(stdscr, y0, 0, "Transactions:", curses.A_BOLD)

        x_date = 0
        x_amt = 12
        x_cat = 26
        x_grp = x_cat + cat_w
        x_desc = x_grp + grp_w

        safe_addstr(stdscr, y0 + 1, x_date, "Date", curses.A_BOLD)
        safe_addstr(stdscr, y0 + 1, x_amt, "Amount", curses.A_BOLD)
        safe_addstr(stdscr, y0 + 1, x_cat, "Category".ljust(cat_w), curses.A_BOLD)
        safe_addstr(stdscr, y0 + 1, x_grp, "Group".ljust(grp_w), curses.A_BOLD)
        safe_addstr(stdscr, y0 + 1, x_desc, "Description", curses.A_BOLD)

        legend_x = min(max(x_desc + 40, w - 40), w - 40)
        legend = [
            "Keys:",
            "UP/DOWN move",
            "LEFT/RIGHT: Cat/Grp",
            "TAB / Shift+TAB: next/prev (cancel edit)",
            "digits+Enter: CatID",
            "letters: edit cell",
            "Enter: commit/confirm",
            "Backspace: undo",
            "s: save+exit",
            "q: quit",
        ]
        for j, line in enumerate(legend):
            safe_addstr(stdscr, y0 + 2 + j, legend_x, line, curses.A_DIM)
        if digit_buf:
            safe_addstr(stdscr, y0 + 2 + len(legend) + 1, legend_x, "CatID buf: %s" % digit_buf, curses.A_DIM)

        tx_visible = bot_h - 3
        if tx_visible < 1:
            tx_visible = 1

        # Scroll management
        nonlocal_scroll = scroll
        if sel < nonlocal_scroll:
            nonlocal_scroll = sel
        if sel >= nonlocal_scroll + tx_visible:
            nonlocal_scroll = sel - tx_visible + 1
        nonlocal_scroll = max(0, min(nonlocal_scroll, max(0, len(rows) - tx_visible)))
        scroll = nonlocal_scroll

        for i in range(tx_visible):
            idx = scroll + i
            if idx >= len(rows):
                break

            row = rows[idx]
            dt = get_date(row)
            amt = get_amount(row)
            cat = get_category(row)
            grp = get_group(row)
            desc = get_desc(row)

            # show live edit buffer
            if edit_mode and idx == sel:
                if col == 0:
                    cat = edit_buf
                else:
                    grp = edit_buf

            base = 0
            if curses.has_colors():
                st = row_color(idx)
                if st == Status.NONE:
                    base = curses.color_pair(1)
                elif st == Status.AUTO:
                    base = curses.color_pair(2)
                else:
                    base = curses.color_pair(3)

            is_sel = idx == sel
            row_attr = base | (curses.A_REVERSE if is_sel else 0)

            # Selected-cell highlight: cyan background + WHITE text (bold)
            cat_cell_attr = row_attr
            grp_cell_attr = row_attr
            if curses.has_colors() and is_sel:
                if col == 0:
                    cat_cell_attr = curses.color_pair(4) | curses.A_BOLD
                else:
                    grp_cell_attr = curses.color_pair(4) | curses.A_BOLD

            y = y0 + 2 + i
            safe_addstr(stdscr, y, x_date, dt.ljust(10)[:10], row_attr)
            safe_addstr(stdscr, y, x_amt, amt.rjust(12)[:12], row_attr)
            safe_addstr(stdscr, y, x_cat, (cat or "").ljust(cat_w)[:cat_w], cat_cell_attr)
            safe_addstr(stdscr, y, x_grp, (grp or "").ljust(grp_w)[:grp_w], grp_cell_attr)
            safe_addstr(stdscr, y, x_desc, desc, row_attr)

            # caret indicator (subtle) in selected edit cell: invert the character under caret
            if edit_mode and is_sel:
                caret_x = None
                if col == 0:
                    caret_x = x_cat + min(edit_pos, cat_w - 1)
                else:
                    caret_x = x_grp + min(edit_pos, grp_w - 1)
                if caret_x is not None:
                    safe_addstr(stdscr, y, caret_x, " ", curses.A_REVERSE)

        safe_addstr(stdscr, h - 1, 0, _ascii(msg), curses.A_DIM)
        stdscr.refresh()
        return cat_id_map

    def run(stdscr) -> int:
        nonlocal sel, scroll, col, edit_mode, edit_buf, edit_pos, digit_buf

        curses.curs_set(0)
        stdscr.keypad(True)

        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
            except Exception:
                pass
            # Status colors (text)
            curses.init_pair(1, curses.COLOR_RED, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_GREEN, -1)
            # Selected cell: WHITE on CYAN
            curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_CYAN)

        msg = "Ready."
        while True:
            clamp()
            cat_id_map = draw(stdscr, msg)
            ch = stdscr.getch()

            # q / s confirm (only if not in edit)
            if not edit_mode and ch == ord("q"):
                if draw_modal_confirm(stdscr, ["Quit without saving?"], "y=quit, n=cancel"):
                    return 0
                msg = "Canceled."
                continue

            if not edit_mode and ch == ord("s"):
                if draw_modal_confirm(stdscr, ["Save changes and exit?"], "y=save, n=cancel"):
                    outp, ump, updated = save_all()
                    msg = "Saved: %s | %s | rules updated: %d" % (outp.name, ump.name, updated)
                    draw(stdscr, msg)
                    return 0
                msg = "Canceled."
                continue

            # TAB / Shift+TAB: move field WITHOUT saving (cancel edit + restore)
            if ch in (9, curses.KEY_BTAB):
                if edit_mode:
                    cancel_edit_restore()
                if ch == 9:
                    col = 1 if col == 0 else 0
                else:
                    col = 0 if col == 1 else 1
                digit_buf = ""
                msg = ""
                continue

            # Edit-mode navigation within string (LEFT/RIGHT move caret)
            if edit_mode and ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
                if ch == curses.KEY_LEFT:
                    edit_pos = max(0, edit_pos - 1)
                else:
                    edit_pos = min(len(edit_buf), edit_pos + 1)
                msg = ""
                continue

            # Movement: if editing and you move off row (UP/DOWN), cancel edit and restore
            if ch in (curses.KEY_UP, curses.KEY_DOWN):
                if edit_mode:
                    cancel_edit_restore()
                if ch == curses.KEY_UP:
                    sel = max(0, sel - 1)
                else:
                    sel = min(max(0, len(rows) - 1), sel + 1)
                digit_buf = ""
                msg = ""
                continue

            # Movement between fields when NOT editing
            if not edit_mode and ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
                col = 0 if ch == curses.KEY_LEFT else 1
                digit_buf = ""
                msg = ""
                continue

            # undo
            if not edit_mode and ch in (curses.KEY_BACKSPACE, 127, 8):
                digit_buf = ""
                msg = do_undo()
                continue

            # start editing by typing a letter
            if not edit_mode and 32 <= ch <= 126 and chr(ch).isalpha():
                begin_edit_with_initial(chr(ch))
                msg = "Editing... Enter=commit. TAB cancels+move. UP/DOWN cancels+move."
                continue

            # edit mode keystrokes
            if edit_mode:
                if ch in (27,):  # ESC cancels edit only
                    cancel_edit_restore()
                    msg = "Edit canceled."
                    continue
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    if edit_pos > 0:
                        edit_buf = edit_buf[: edit_pos - 1] + edit_buf[edit_pos:]
                        edit_pos -= 1
                    continue
                if ch in (10, 13):
                    # Commit edit
                    push_undo()
                    if col == 0:
                        msg = assign_category(sel, edit_buf, mark_manual=True)
                    else:
                        msg = assign_group(sel, edit_buf, mark_manual=True)
                    edit_mode = False
                    edit_buf = ""
                    edit_pos = 0
                    digit_buf = ""
                    continue
                if 32 <= ch <= 126:
                    # insert at caret
                    edit_buf = edit_buf[:edit_pos] + chr(ch) + edit_buf[edit_pos:]
                    edit_pos += 1
                continue

            # numeric CatID buffer
            if ord("0") <= ch <= ord("9"):
                digit_buf += chr(ch)
                msg = ""
                continue

            # ENTER behavior:
            # - if digit_buf: apply CatID assignment (manual)
            # - else if on Cat field: confirm-or-jump-to-grp based on validity
            # - else if AUTO row: confirm -> green, move next
            # - else: confirm if assigned
            if ch in (10, 13):
                if digit_buf:
                    try:
                        cid = int(digit_buf)
                    except Exception:
                        cid = 0
                    digit_buf = ""
                    cat = cat_id_map.get(cid, "")
                    if not cat:
                        msg = "Invalid CatID."
                        continue
                    push_undo()
                    msg = assign_category(sel, cat, mark_manual=True)
                    continue

                # If on Category field: your requested logic
                if col == 0:
                    c = normalize_name(get_category(rows[sel]))
                    g = normalize_name(get_group(rows[sel]))
                    if is_valid_cat(c) and is_valid_group(g):
                        push_undo()
                        status[sel] = Status.MANUAL
                        msg = "Confirmed."
                        sel = min(max(0, len(rows) - 1), sel + 1)
                        continue
                    if is_valid_cat(c) and not is_valid_group(g):
                        # make row yellow (AUTO) and move to Group field
                        status[sel] = Status.AUTO
                        col = 1
                        msg = "Group invalid/missing; please set Group."
                        continue
                    msg = "Category invalid/missing."
                    continue

                # AUTO confirm + auto-advance (if not on Cat field)
                if status[sel] == Status.AUTO:
                    c = normalize_name(get_category(rows[sel]))
                    g = normalize_name(get_group(rows[sel]))
                    if is_valid_cat(c) and is_valid_group(g):
                        push_undo()
                        status[sel] = Status.MANUAL
                        msg = "Confirmed."
                        sel = min(max(0, len(rows) - 1), sel + 1)
                        continue

                # regular confirm
                c = normalize_name(get_category(rows[sel]))
                g = normalize_name(get_group(rows[sel]))
                if is_valid_cat(c) and is_valid_group(g):
                    push_undo()
                    status[sel] = Status.MANUAL
                    msg = "Confirmed."
                else:
                    msg = "Nothing to confirm."
                continue

            msg = ""

    try:
        return curses.wrapper(run)
    except curses.error as e:
        print(_ascii("ERROR: curses failed: %s" % e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cmd_categorize([]))