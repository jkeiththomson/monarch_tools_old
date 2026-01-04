from __future__ import annotations

import curses
import time
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict

from .taxonomy import Taxonomy, DEFAULT_CATEGORY, DEFAULT_GROUP
from .transactions import Txn, load_transactions, write_transactions
from .rules import (
    load_rules,
    save_rules,
    upsert_rule_literal_description,
    find_rule_for_description,
)
from .text_utils import norm_key, titleish

COLUMN_CAT = 0
COLUMN_GRP = 1


@dataclass
class UIState:
    row: int = 0
    col: int = COLUMN_CAT
    scroll: int = 0

    edit_buffer: str = ""
    edit_mode: bool = False
    edit_pos: int = 0  # caret position within edit_buffer

    digit_buffer: str = ""
    digit_ts: float = 0.0

    message: str = ""
    message_ts: float = 0.0


def run_categorize_ui(
    stdscr,
    in_csv: Path,
    rules_path: Path,
    categories_path: Path,
    groups_path: Path,
    out_csv: Optional[Path] = None,
) -> int:
    curses.curs_set(0)
    curses.use_default_colors()
    curses.start_color()
    _init_colors()

    txns, orig_cols, meta = load_transactions(in_csv)
    taxonomy = _load_taxonomy(categories_path, groups_path)

    rules = load_rules(rules_path)

    # mark confirmed based on existing rules.json matches (literal description mapping)
    for t in txns:
        r = find_rule_for_description(rules, t.description)
        if (
            r
            and norm_key(str(r.get("category", ""))) == norm_key(t.category)
            and norm_key(str(r.get("group", ""))) == norm_key(t.group)
        ):
            t.confirmed = True

    state = UIState()
    out_csv = out_csv or in_csv

    while True:
        _maybe_expire_digit_buffer(state)
        _draw(stdscr, taxonomy, txns, state)
        ch = stdscr.getch()

        if ch == curses.KEY_RESIZE:
            continue

        if ch in (ord("q"), ord("Q")):
            if _confirm_quit(
                stdscr,
                taxonomy,
                txns,
                state,
                rules_path,
                rules,
                categories_path,
                groups_path,
                out_csv,
                orig_cols,
                meta,
            ):
                return 0
            continue

        if _handle_nav(ch, txns, state):
            continue

        # Delete clears cat/grp and prunes unused taxonomy entries.
        if ch in (curses.KEY_DC, 127) and not state.edit_mode:
            _handle_delete(txns, taxonomy, state)
            _flash(state, "Cleared. (Del)")
            continue

        # Tab switches between Category and Group columns (when not actively editing).
        if ch == 9 and not state.edit_mode:
            state.col = COLUMN_GRP if state.col == COLUMN_CAT else COLUMN_CAT
            state.edit_mode = False
            state.edit_buffer = ""
            state.edit_pos = 0
            continue

        # Left/Right are caret movement within the current cell (and can start editing).
        if ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
            t = txns[state.row]
            cur_val = t.category if state.col == COLUMN_CAT else t.group
            if not state.edit_mode:
                state.edit_mode = True
                state.edit_buffer = cur_val or ""
                state.edit_pos = 0
            if ch == curses.KEY_LEFT:
                state.edit_pos = max(0, state.edit_pos - 1)
            else:
                state.edit_pos = min(len(state.edit_buffer), state.edit_pos + 1)
            continue

        # Backspace behavior per spec:
        # - If digit buffer exists, backspace edits the digit buffer.
        # - Otherwise, backspace enters edit mode at the RIGHT edge and deletes the last char.
        if ch in (curses.KEY_BACKSPACE, 8, 127):
            if state.digit_buffer and not state.edit_mode:
                state.digit_buffer = state.digit_buffer[:-1]
                state.digit_ts = time.time()
                continue

            t = txns[state.row]
            cur_val = t.category if state.col == COLUMN_CAT else t.group
            if not state.edit_mode:
                state.edit_mode = True
                state.edit_buffer = cur_val or ""
                state.edit_pos = len(state.edit_buffer)

            if state.edit_pos > 0 and state.edit_buffer:
                # delete char before caret
                state.edit_buffer = state.edit_buffer[: state.edit_pos - 1] + state.edit_buffer[state.edit_pos :]
                state.edit_pos = max(0, state.edit_pos - 1)
            continue

        # digits: CatID buffer (Category column only, and only when not editing)
        if (not state.edit_mode) and (state.col == COLUMN_CAT) and (48 <= ch <= 57):
            _push_digit(state, chr(ch))
            continue

        # text entry (letters/digits/space/&/-):
        # - first typed character clears the field and starts at leftmost
        # - thereafter, left/right move caret; typing inserts at caret
        if 32 <= ch <= 126:
            c = chr(ch)
            if c.isalnum() or c in (" ", "-", "&"):
                if not state.edit_mode:
                    state.edit_mode = True
                    state.edit_buffer = ""
                    state.edit_pos = 0
                # If this is the first character (field just entered), we treat it as replace-all.
                if state.edit_buffer == "" and state.edit_pos == 0:
                    state.edit_buffer = c
                    state.edit_pos = 1
                else:
                    state.edit_buffer = state.edit_buffer[: state.edit_pos] + c + state.edit_buffer[state.edit_pos :]
                    state.edit_pos += 1
                continue

        # Enter approves (only Enter approves).
        if ch in (curses.KEY_ENTER, 10, 13):
            _handle_enter(taxonomy, txns, state, rules)
            if _all_confirmed(txns):
                _flash(state, "All confirmed — press S to SAVE.")
            continue

        # Save when all confirmed.
        if ch in (ord("s"), ord("S")) and _all_confirmed(txns):
            _save_all(
                taxonomy,
                txns,
                state,
                rules_path,
                rules,
                categories_path,
                groups_path,
                out_csv,
                orig_cols,
                meta,
            )
            return 0


def _init_colors() -> None:
    """
    We keep it simple and high-contrast:
      - pair 6: focused/edit cell (black on very light background)
      - pair 9: taxonomy + legend text (same as focused background; user liked these)
      - pair 4: headers
      - pair 5: SAVE button
    """
    try:
        # Status colors for transaction rows
        curses.init_pair(1, curses.COLOR_RED, -1)     # missing cat/group
        curses.init_pair(2, curses.COLOR_GREEN, -1)   # confirmed
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # has cat+group but not confirmed

        # High-contrast UI blocks (taxonomy/legend/focus)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)  # focused/edit cell
        curses.init_pair(9, curses.COLOR_BLACK, curses.COLOR_WHITE)  # taxonomy/legend text
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)   # headings
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)   # SAVE button
    except curses.error:
        # Fallback: terminal may not support colors; use defaults.
        pass


def _load_taxonomy(categories_path: Path, groups_path: Path) -> Taxonomy:
    taxonomy = Taxonomy(groups=[], group_to_cats={})
    taxonomy.ensure_defaults()

    cur_group: Optional[str] = None

    # groups.txt authoritative
    if groups_path.exists():
        for raw in groups_path.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue

            # Group header: "Finance:" (not indented)
            if not line.startswith((" ", "\t")) and line.strip().endswith(":"):
                cur_group = titleish(line.strip()[:-1].strip())
                if norm_key(cur_group) == norm_key(DEFAULT_GROUP):
                    cur_group = DEFAULT_GROUP
                taxonomy.add_group(cur_group)
                continue

            # Indented category under current group
            if line.startswith((" ", "\t")) and cur_group:
                cat = line.strip()
                m = re.match(r"^(\d+)\s+(.*)$", cat)
                if m:
                    cat = m.group(2).strip()
                if cat and norm_key(cat) != norm_key(DEFAULT_CATEGORY):
                    taxonomy.add_category(cat, cur_group)
                continue

            # Fallback: bare group name
            if not line.startswith((" ", "\t")):
                cur_group = titleish(line.strip().rstrip(":"))
                if norm_key(cur_group) == norm_key(DEFAULT_GROUP):
                    cur_group = DEFAULT_GROUP
                taxonomy.add_group(cur_group)

    # categories.txt is currently empty in your golden zip; if populated later, we keep it non-authoritative:
    # any categories not present in groups are placed into a generated group called "Other".
    if categories_path.exists():
        flat = [ln.strip() for ln in categories_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if flat:
            cat_to_grp = taxonomy.category_to_group()
            for cat in flat:
                if norm_key(cat) in cat_to_grp or norm_key(cat) == norm_key(DEFAULT_CATEGORY):
                    continue
                taxonomy.add_group("Other")
                taxonomy.add_category(cat, "Other")

    taxonomy.normalize_display()
    taxonomy.sort_alpha()
    return taxonomy


def _all_confirmed(txns: List[Txn]) -> bool:
    return all(t.confirmed and _is_legit(t) for t in txns)


def _is_legit(t: Txn) -> bool:
    # Treat default placeholders as not legit (so they must be filled).
    if norm_key(t.category) == norm_key(DEFAULT_CATEGORY):
        return False
    if norm_key(t.group) == norm_key(DEFAULT_GROUP):
        return False
    return True


def _flash(state: UIState, msg: str, seconds: float = 1.2) -> None:
    state.message = msg
    state.message_ts = time.time() + seconds


def _maybe_expire_digit_buffer(state: UIState, timeout: float = 1.2) -> None:
    if state.digit_buffer and (time.time() - state.digit_ts) > timeout:
        state.digit_buffer = ""


def _push_digit(state: UIState, digit: str) -> None:
    now = time.time()
    if state.digit_buffer and (now - state.digit_ts) > 1.2:
        state.digit_buffer = ""
    if len(state.digit_buffer) >= 3:
        state.digit_buffer = ""
    state.digit_buffer += digit
    state.digit_ts = now


def _handle_nav(ch: int, txns: List[Txn], state: UIState) -> bool:
    """Row navigation (UP/DOWN). Left/Right are used for caret movement while editing."""
    max_row = max(0, len(txns) - 1)
    if ch == curses.KEY_UP:
        state.row = max(0, state.row - 1)
        state.edit_mode = False
        state.edit_buffer = ""
        state.edit_pos = 0
        return True
    if ch == curses.KEY_DOWN:
        state.row = min(max_row, state.row + 1)
        state.edit_mode = False
        state.edit_buffer = ""
        state.edit_pos = 0
        return True
    return False


def _handle_delete(txns: List[Txn], taxonomy: Taxonomy, state: UIState) -> None:
    t = txns[state.row]
    old_cat = t.category
    old_grp = t.group
    t.category = DEFAULT_CATEGORY
    t.group = DEFAULT_GROUP
    t.confirmed = False

    # prune taxonomy for now-unused entries
    used_cats = [x.category for x in txns if x.category]
    used_grps = [x.group for x in txns if x.group]

    taxonomy.remove_category_if_unused(old_cat, used_cats)
    taxonomy.remove_group_if_unused(old_grp, used_grps)


def _handle_enter(taxonomy: Taxonomy, txns: List[Txn], state: UIState, rules) -> None:
    t = txns[state.row]
    cat_items = taxonomy.compute_cat_ids()
    max_row = max(0, len(txns) - 1)

    def _advance_row() -> None:
        # move to next transaction's CATEGORY (unless already last row)
        if state.row < max_row:
            state.row += 1
        state.col = COLUMN_CAT
        state.edit_mode = False
        state.edit_buffer = ""
        state.edit_pos = 0
        state.digit_buffer = ""

    def _focus_group_same_row() -> None:
        state.col = COLUMN_GRP
        state.edit_mode = False
        state.edit_buffer = ""
        state.edit_pos = 0
        state.digit_buffer = ""

    # 1) digit buffer takes precedence (CatID)
    if state.digit_buffer:
        try:
            wanted = int(state.digit_buffer)
        except ValueError:
            wanted = -1
        match = next((x for x in cat_items if x[0] == wanted), None)
        state.digit_buffer = ""
        if not match:
            _flash(state, "No such CatID.")
            return
        _, cat, grp = match
        t.category = cat
        t.group = grp
        t.confirmed = True
        upsert_rule_literal_description(rules, t.description, t.category, t.group)
        _advance_row()
        return

    # 2) typed text: autocomplete / edit commit
    if state.edit_mode:
        typed = (state.edit_buffer or "").strip()
        state.edit_mode = False
        state.edit_buffer = ""
        state.edit_pos = 0

        if not typed:
            return

        if state.col == COLUMN_CAT:
            chosen = _autocomplete_category(taxonomy, typed)
            t.category = chosen
            cat_to_grp = taxonomy.category_to_group()
            mapped_grp = cat_to_grp.get(norm_key(chosen), "")
            if mapped_grp:
                t.group = mapped_grp

            # ensure taxonomy knows about chosen category if it has a real group
            if norm_key(chosen) != norm_key(DEFAULT_CATEGORY) and norm_key(t.group) != norm_key(DEFAULT_GROUP):
                taxonomy.add_category(chosen, t.group)

            t.confirmed = _is_legit(t)
            if t.confirmed:
                upsert_rule_literal_description(rules, t.description, t.category, t.group)

            # Navigation behavior:
            # - If we still don't have a real group, go to GROUP on same row.
            # - Otherwise advance to next row/category.
            if norm_key(t.group) == norm_key(DEFAULT_GROUP) or not t.group.strip():
                _focus_group_same_row()
            else:
                _advance_row()
            return

        # COLUMN_GRP edit
        chosen_grp = _autocomplete_group(taxonomy, typed)
        old_grp = t.group
        t.group = chosen_grp

        # If category is set and group changed, move mapping so it doesn't 'snap back'.
        if norm_key(t.category) != norm_key(DEFAULT_CATEGORY):
            _move_category_group(taxonomy, t.category, old_grp, t.group)

        t.confirmed = _is_legit(t)
        if t.confirmed:
            upsert_rule_literal_description(rules, t.description, t.category, t.group)

        _advance_row()
        return

    # 3) No digit / no edit: approve existing row if legit
    if _is_legit(t):
        t.confirmed = True
        upsert_rule_literal_description(rules, t.description, t.category, t.group)
        _advance_row()
    else:
        _flash(state, "Missing category/group.")


def _autocomplete_category(taxonomy: Taxonomy, typed: str) -> str:
    typedk = norm_key(typed)
    # exact/prefix match by display name
    for _, cat, _ in taxonomy.compute_cat_ids():
        if norm_key(cat).startswith(typedk):
            return titleish(cat)
    return titleish(typed)


def _autocomplete_group(taxonomy: Taxonomy, typed: str) -> str:
    typedk = norm_key(typed)
    for g in taxonomy.groups:
        if norm_key(g).startswith(typedk):
            return titleish(g) if norm_key(g) != norm_key(DEFAULT_GROUP) else DEFAULT_GROUP
    return titleish(typed)


def _ghost_completion_category(taxonomy: Taxonomy, typed: str) -> str:
    typed = typed or ""
    typedk = norm_key(typed)
    if not typedk:
        return typed
    for _, cat, _ in taxonomy.compute_cat_ids():
        if norm_key(cat).startswith(typedk):
            return titleish(cat)
    return titleish(typed)


def _ghost_completion_group(taxonomy: Taxonomy, typed: str) -> str:
    typed = typed or ""
    typedk = norm_key(typed)
    if not typedk:
        return typed
    for g in taxonomy.groups:
        if norm_key(g).startswith(typedk):
            return g
    return titleish(typed)


def _move_category_group(taxonomy: Taxonomy, cat: str, old_group: str, new_group: str) -> None:
    if norm_key(new_group) == norm_key(DEFAULT_GROUP):
        return
    new_group_disp = DEFAULT_GROUP if norm_key(new_group) == norm_key(DEFAULT_GROUP) else titleish(new_group)
    old_group_disp = DEFAULT_GROUP if norm_key(old_group) == norm_key(DEFAULT_GROUP) else titleish(old_group)

    taxonomy.add_group(new_group_disp)

    g2c = taxonomy.group_to_cats
    # remove from old
    if old_group_disp in g2c:
        g2c[old_group_disp] = [c for c in g2c.get(old_group_disp, []) if norm_key(c) != norm_key(cat)]
        if not g2c[old_group_disp] and norm_key(old_group_disp) != norm_key(DEFAULT_GROUP):
            g2c.pop(old_group_disp, None)
            taxonomy.groups = [g for g in taxonomy.groups if norm_key(g) != norm_key(old_group_disp)]

    # add to new
    lst = g2c.get(new_group_disp, [])
    if not any(norm_key(c) == norm_key(cat) for c in lst):
        lst.append(titleish(cat))
    g2c[new_group_disp] = lst

    taxonomy.sort_alpha()


def _save_all(
    taxonomy: Taxonomy,
    txns: List[Txn],
    state: UIState,
    rules_path: Path,
    rules,
    categories_path: Path,
    groups_path: Path,
    out_csv: Path,
    orig_cols: List[str],
    meta: Dict[str, str],
) -> None:
    # Persist rules.json
    save_rules(rules_path, rules)

    # Persist groups.txt as authoritative
    _write_groups(groups_path, taxonomy)

    # Persist categories.txt as flat list (optional)
    _write_categories(categories_path, taxonomy)

    # Persist transactions
    write_transactions(out_csv, orig_cols, meta, txns)

    _flash(state, "Saved.")


def _write_groups(path: Path, taxonomy: Taxonomy) -> None:
    lines: List[str] = []
    for g in taxonomy.groups:
        gdisp = g.rstrip(":")
        lines.append(f"{gdisp}:")
        cats = taxonomy.group_to_cats.get(gdisp, taxonomy.group_to_cats.get(g, []))
        # Blank line between groups requested (after categories block)
        for c in cats:
            if norm_key(gdisp) == norm_key(DEFAULT_GROUP):
                continue
            if norm_key(c) == norm_key(DEFAULT_CATEGORY):
                continue
            lines.append(f"  {c}")
        lines.append("")  # blank line between groups
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_categories(path: Path, taxonomy: Taxonomy) -> None:
    cats: List[str] = []
    for _, cat, _ in taxonomy.compute_cat_ids():
        if norm_key(cat) == norm_key(DEFAULT_CATEGORY):
            continue
        cats.append(cat)
    # unique, alpha
    seen = set()
    out = []
    for c in cats:
        k = norm_key(c)
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    out.sort(key=norm_key)
    path.write_text("\n".join(out).rstrip() + ("\n" if out else ""), encoding="utf-8")


def _confirm_quit(
    stdscr,
    taxonomy: Taxonomy,
    txns: List[Txn],
    state: UIState,
    rules_path: Path,
    rules,
    categories_path: Path,
    groups_path: Path,
    out_csv: Path,
    orig_cols: List[str],
    meta: Dict[str, str],
) -> bool:
    h, w = stdscr.getmaxyx()
    msg = "Quit without saving? (y/N)"
    y = max(0, h // 2)
    x = max(0, (w - len(msg)) // 2)
    stdscr.addstr(y, 0, " " * (w - 1))
    stdscr.addstr(y, x, msg[: w - 1], curses.A_BOLD | curses.color_pair(4))
    stdscr.refresh()
    ch = stdscr.getch()
    return ch in (ord("y"), ord("Y"))


def _pad(s: str, w: int) -> str:
    s = s or ""
    if len(s) >= w:
        return s[:w]
    return s + (" " * (w - len(s)))


def _draw(stdscr, taxonomy: Taxonomy, txns: List[Txn], state: UIState) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    # Compute column widths per your spec
    col0 = 3
    col_stmt = 10
    col_txn = 10
    col_desc = 40
    col_catid = 5
    col_cat = max((len(c) for _, c, _ in taxonomy.compute_cat_ids()), default=0) + 1
    col_grp = max((len(g) for g in taxonomy.groups), default=0) + 1

    # Layout: taxonomy at top, transactions below, legend right
    # Layout: split screen roughly in half (taxonomy top, transactions bottom).
    # We keep one footer line at the very bottom.
    tax_h = max(6, (h - 1) // 2)
    list_y0 = tax_h
    list_h = max(3, h - tax_h - 1)

    # Taxonomy block
    _draw_taxonomy(stdscr, taxonomy, 0, 0, w, tax_h)

    # Transaction list block (left side)
    list_w = min(w - 1, col0 + 1 + col_stmt + 1 + col_txn + 1 + col_desc + 1 + col_catid + 1 + col_cat + 1 + col_grp + 1)
    _draw_txns(
        stdscr,
        taxonomy,
        txns,
        state,
        y0=list_y0,
        x0=0,
        width=list_w,
        height=list_h,
        col0=col0,
        col_stmt=col_stmt,
        col_txn=col_txn,
        col_desc=col_desc,
        col_catid=col_catid,
        col_cat=col_cat,
        col_grp=col_grp,
    )

    # Legend on bottom-right (same colors as taxonomy)
    _draw_legend(stdscr, list_y0 + max(0, list_h - 4), max(0, list_w + 1), w - list_w - 1, 4)

    # Footer message / save prompt
    footer_y = h - 1
    if _all_confirmed(txns):
        btn = "   [  SAVE  ]   (press S)   "
        x = max(0, (w - len(btn)) // 2)
        stdscr.addstr(footer_y, 0, " " * (w - 1))
        stdscr.addstr(footer_y, x, btn[: w - 1], curses.A_BOLD | curses.color_pair(5))
    else:
        msg = ""
        if state.message and time.time() < state.message_ts:
            msg = state.message
        elif state.digit_buffer:
            msg = f"CatID: {state.digit_buffer}"
        elif state.edit_mode:
            msg = f"Typing: {state.edit_buffer}"
        stdscr.addstr(footer_y, 0, msg[: w - 1].ljust(w - 1), curses.A_DIM)

    try:
        curses.curs_set(1 if state.edit_mode else 0)
    except Exception:
        pass

    stdscr.refresh()


def _draw_taxonomy(stdscr, taxonomy: Taxonomy, y0: int, x0: int, width: int, height: int) -> None:
    # Header
    title = "Taxonomy (Groups → Categories)"
    stdscr.addstr(y0, x0, _pad(title, min(width - 1, len(title))), curses.A_BOLD | curses.color_pair(4))

    # Build lines: group header + categories indented, blank line between groups.
    # Build lines: group header + categories indented, blank line between groups.
    lines: List[str] = []
    cat_items = taxonomy.compute_cat_ids()
    cat_id = {norm_key(cat): cid for cid, cat, _grp in cat_items}

    grp_to_cats = taxonomy.group_to_cats
    # Preserve taxonomy group ordering (Aaa first), and ensure uniqueness.
    groups_ordered = []
    seen = set()
    for g in taxonomy.groups:
        k = norm_key(g)
        if k in seen:
            continue
        seen.add(k)
        groups_ordered.append(g)
    for g in groups_ordered:
        g_label = "Aaa" if norm_key(g) == norm_key(DEFAULT_GROUP) else g
        lines.append(f"{g_label}:")
        cats = grp_to_cats.get(g, [])
        for c in cats:
            cid = cat_id.get(norm_key(c), 0)
            # Category line includes CatID at left of name
            lines.append(f"  {cid:>3} {c}")
        lines.append("")  # blank line between groups

    # remove trailing blank line for nicer rendering
    while lines and lines[-1] == "":
        lines.pop()
    col_w = max(20, min(width // 2, width - 2))
    cols = max(1, width // col_w)
    # compute how many lines per column = usable_h
    for idx, line in enumerate(lines):
        col = idx // usable_h
        row = idx % usable_h
        if col >= cols:
            break
        x = x0 + col * col_w
        y = start_y + row
        if y > maxy:
            continue
        stdscr.addstr(y, x, _pad(line, min(col_w - 1, width - x - 1)), curses.color_pair(9) | curses.A_BOLD)


def _draw_txns(
    stdscr,
    taxonomy: Taxonomy,
    txns: List[Txn],
    state: UIState,
    y0: int,
    x0: int,
    width: int,
    height: int,
    col0: int,
    col_stmt: int,
    col_txn: int,
    col_desc: int,
    col_catid: int,
    col_cat: int,
    col_grp: int,
) -> None:
    # Header row
    header = (
        _pad("#", col0)
        + " "
        + _pad("StmtDate", col_stmt)
        + " "
        + _pad("TxnDate", col_txn)
        + " "
        + _pad("Description", col_desc)
        + " "
        + _pad("CatID", col_catid)
        + " "
        + _pad("Category", col_cat)
        + " "
        + _pad("Group", col_grp)
    )
    stdscr.addstr(y0, x0, header[: width - 1], curses.A_BOLD | curses.color_pair(4))

    # Scroll
    visible = max(1, height - 1)
    if state.row < state.scroll:
        state.scroll = state.row
    if state.row >= state.scroll + visible:
        state.scroll = state.row - visible + 1

    cat_ids = taxonomy.compute_cat_ids()
    cat_to_id = {norm_key(cat): cid for cid, cat, _ in cat_ids}

    for i in range(visible):
        idx = state.scroll + i
        y = y0 + 1 + i
        if y >= y0 + height or idx >= len(txns):
            break
        t = txns[idx]

        cid = cat_to_id.get(norm_key(t.category), 0)
        cid_str = str(cid) if cid else ""

        row_prefix = (
            _pad(str(t.idx), col0)
            + " "
            + _pad(t.statement_date, col_stmt)
            + " "
            + _pad(t.transaction_date, col_txn)
            + " "
            + _pad(t.description, col_desc)
            + " "
            + _pad(cid_str, col_catid)
            + " "
        )

        # Base line with cat/grp (non-focused)
        line = row_prefix + _pad(t.category, col_cat) + " " + _pad(t.group, col_grp)
        status_pair = 1
        if t.confirmed:
            status_pair = 2
        elif norm_key(t.category) != norm_key(DEFAULT_CATEGORY) and norm_key(t.group) != norm_key(DEFAULT_GROUP):
            status_pair = 3

        attr = curses.color_pair(status_pair)
        if t.confirmed:
            attr |= curses.A_BOLD
        stdscr.addstr(y, x0, line[: width - 1], attr)

        # Focus overlays for cat/group cell only
        is_focus_row = (idx == state.row)
        if not is_focus_row:
            continue

        cat_x = x0 + len(row_prefix)
        grp_x = cat_x + col_cat + 1

        focus_attr = curses.color_pair(6) | curses.A_BOLD  # same family as taxonomy/legend

        if state.col == COLUMN_CAT:
            _draw_focus_cell(
                stdscr,
                y,
                cat_x,
                col_cat,
                value=t.category,
                edit_mode=state.edit_mode,
                edit_buffer=state.edit_buffer,
                ghost=_ghost_completion_category(taxonomy, state.edit_buffer) if state.edit_mode else "",
                attr=focus_attr,
            )
            if state.edit_mode:
                try:
                    stdscr.move(y, cat_x + min(state.edit_pos, max(0, col_cat - 1)))
                except Exception:
                    pass
        else:
            _draw_focus_cell(
                stdscr,
                y,
                grp_x,
                col_grp,
                value=t.group,
                edit_mode=state.edit_mode,
                edit_buffer=state.edit_buffer,
                ghost=_ghost_completion_group(taxonomy, state.edit_buffer) if state.edit_mode else "",
                attr=focus_attr,
            )
            if state.edit_mode:
                try:
                    stdscr.move(y, grp_x + min(state.edit_pos, max(0, col_grp - 1)))
                except Exception:
                    pass


def _draw_focus_cell(
    stdscr,
    y: int,
    x: int,
    width: int,
    value: str,
    edit_mode: bool,
    edit_buffer: str,
    ghost: str,
    attr: int,
) -> None:
    # Paint background for entire cell
    stdscr.addstr(y, x, " " * width, attr)

    if not edit_mode:
        stdscr.addstr(y, x, _pad(value, width), attr)
        return

    buf = edit_buffer or ""
    stdscr.addstr(y, x, buf[:width], attr)  # typed text should be DARK (black via color pair)

    # Ghost suffix: render only the remainder (dim), after typed prefix.
    if ghost and ghost.lower().startswith(buf.lower()) and len(ghost) > len(buf):
        suffix = ghost[len(buf):]
        sx = x + min(len(buf), width)
        max_suffix = max(0, width - min(len(buf), width))
        if max_suffix > 0:
            stdscr.addstr(y, sx, suffix[:max_suffix], (attr & ~curses.A_BOLD) | curses.A_DIM)


def _draw_legend(stdscr, y0: int, x0: int, width: int, height: int) -> None:
    if width <= 10 or height <= 1:
        return
    stdscr.addstr(y0, x0, _pad("Legend", min(width - 1, 6)), curses.A_BOLD | curses.color_pair(4))
    lines = [
        "Enter: approve / assign",
        "0-9: CatID buffer",
        "Del: clear cat/grp",
        "q: quit",
    ]
    for i, ln in enumerate(lines[: max(0, height - 1)]):
        stdscr.addstr(y0 + 1 + i, x0, _pad(ln, width - 1), curses.color_pair(9) | curses.A_BOLD)
