from __future__ import annotations

import curses
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .taxonomy import Taxonomy, DEFAULT_CATEGORY, DEFAULT_GROUP
from .transactions import Txn, load_transactions, write_transactions
from .rules import load_rules, save_rules, upsert_rule_literal_description, find_rule_for_description
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
    taxonomy.normalize_display()
    taxonomy.sort_alpha()

    rules = load_rules(rules_path)

    # mark confirmed based on existing rules.json matches (literal description mapping)
    for t in txns:
        r = find_rule_for_description(rules, t.description)
        if r and norm_key(str(r.get("category",""))) == norm_key(t.category) and norm_key(str(r.get("group",""))) == norm_key(t.group):
            t.confirmed = True

    state = UIState()
    out_csv = out_csv or in_csv

    while True:
        _maybe_expire_digit_buffer(state)
        _draw(stdscr, taxonomy, txns, state)
        ch = stdscr.getch()

        if ch == curses.KEY_RESIZE:
            continue

        if ch in (ord('q'), ord('Q')):
            if _confirm_quit(stdscr, taxonomy, txns, state, rules_path, rules, categories_path, groups_path, out_csv, orig_cols, meta):
                return 0
            continue

        if _handle_nav(ch, txns, state, stdscr):
            continue

        # delete key: remove cat/grp from transaction + prune unused taxonomy entries
        if ch in (curses.KEY_DC, 127) and not state.edit_mode:
            _handle_delete(txns, taxonomy, state, categories_path, groups_path)
            _flash(state, "Cleared. (Del)")

            continue

        # backspace: edit mode deletes characters; otherwise deletes digit buffer
        if ch in (curses.KEY_BACKSPACE, 8, 127):
            if state.edit_mode:
                state.edit_buffer = state.edit_buffer[:-1]
                if not state.edit_buffer:
                    state.edit_mode = False
            else:
                state.digit_buffer = state.digit_buffer[:-1]
                state.digit_ts = time.time()
            continue

        # digits: CatID buffer and highlight
        if not state.edit_mode and 48 <= ch <= 57:
            digit = chr(ch)
            _push_digit(state, digit)
            # if we have 3 digits, try apply cat id immediately? (we still require Enter to approve)
            continue

        # letters: start/continue edit
        if 65 <= ch <= 90 or 97 <= ch <= 122 or ch == ord(' ') or ch == ord('-') or ch == ord('&'):
            c = chr(ch)
            if not state.edit_mode:
                state.edit_mode = True
                state.edit_buffer = ""
            state.edit_buffer += c
            continue

        # Enter: assign/approve (ONLY Enter approves, per A)
        if ch in (curses.KEY_ENTER, 10, 13):
            _handle_enter(taxonomy, txns, state, rules)
            # if all confirmed, show SAVE button and allow 's'
            if _all_confirmed(txns):
                _flash(state, "All confirmed — press S to SAVE.")
            continue

        # Save (only when all confirmed): 's' or 'S'
        if ch in (ord('s'), ord('S')) and _all_confirmed(txns):
            _save_all(taxonomy, txns, state, rules_path, rules, categories_path, groups_path, out_csv, orig_cols, meta)
            return 0

def _init_colors():
    # pair ids
    curses.init_pair(1, curses.COLOR_GREEN, -1)   # confirmed
    curses.init_pair(2, curses.COLOR_YELLOW, -1)  # pending
    curses.init_pair(3, curses.COLOR_RED, -1)     # invalid
    curses.init_pair(4, curses.COLOR_CYAN, -1)    # headers
    curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_GREEN)  # highlight per spec (white on dark green-ish)
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)  # focus cell
    curses.init_pair(7, curses.COLOR_WHITE, -1)   # normal
    curses.init_pair(8, curses.COLOR_MAGENTA, -1) # messages

def _color_for_txn(t: Txn) -> int:
    if t.confirmed and _is_legit(t):
        return curses.color_pair(1)
    if _is_legit(t):
        return curses.color_pair(2)
    return curses.color_pair(3)

def _is_legit(t: Txn) -> bool:
    return norm_key(t.category) != norm_key(DEFAULT_CATEGORY) and norm_key(t.group) != norm_key(DEFAULT_GROUP)

def _all_confirmed(txns: List[Txn]) -> bool:
    for t in txns:
        if not (t.confirmed and _is_legit(t)):
            return False
    return True

def _flash(state: UIState, msg: str, seconds: float = 1.2):
    state.message = msg
    state.message_ts = time.time() + seconds

def _maybe_expire_digit_buffer(state: UIState, timeout: float = 1.2):
    if state.digit_buffer and (time.time() - state.digit_ts) > timeout:
        state.digit_buffer = ""

def _push_digit(state: UIState, digit: str):
    now = time.time()
    if state.digit_buffer and (now - state.digit_ts) > 1.2:
        state.digit_buffer = ""
    if len(state.digit_buffer) >= 3:
        state.digit_buffer = ""
    state.digit_buffer += digit
    state.digit_ts = now

def _handle_nav(ch: int, txns: List[Txn], state: UIState, stdscr) -> bool:
    max_row = len(txns) - 1
    if ch == curses.KEY_UP:
        state.row = max(0, state.row - 1)
        state.edit_mode = False
        state.edit_buffer = ""
        return True
    if ch == curses.KEY_DOWN:
        state.row = min(max_row, state.row + 1)
        state.edit_mode = False
        state.edit_buffer = ""
        return True
    if ch == curses.KEY_LEFT:
        state.col = COLUMN_CAT
        state.edit_mode = False
        state.edit_buffer = ""
        return True
    if ch == curses.KEY_RIGHT:
        state.col = COLUMN_GRP
        state.edit_mode = False
        state.edit_buffer = ""
        return True
    return False

def _handle_enter(taxonomy: Taxonomy, txns: List[Txn], state: UIState, rules) -> None:
    t = txns[state.row]
    cat_items = taxonomy.compute_cat_ids()

    # 1) digit buffer takes precedence
    if state.digit_buffer:
        try:
            wanted = int(state.digit_buffer)
        except ValueError:
            wanted = -1
        match = next((x for x in cat_items if x[0] == wanted), None)
        if match:
            _, cat, grp = match
            if state.col == COLUMN_CAT:
                t.category = cat
                t.group = grp
                t.confirmed = True  # Enter approves
                upsert_rule_literal_description(rules, t.description, t.category, t.group)
                state.row = min(len(txns)-1, state.row + 1)
            else:
                # in Group column: treat as selecting group by category id doesn't make sense
                t.group = grp
                if norm_key(t.group) != norm_key(DEFAULT_GROUP) and norm_key(t.category) != norm_key(DEFAULT_CATEGORY):
                    t.confirmed = True
                    upsert_rule_literal_description(rules, t.description, t.category, t.group)
                    state.row = min(len(txns)-1, state.row + 1)
            state.digit_buffer = ""
            return

    # 2) edit buffer: autocomplete / create
    if state.edit_mode:
        raw = state.edit_buffer.strip()
        state.edit_mode = False
        state.edit_buffer = ""
        if not raw:
            return
        if state.col == COLUMN_CAT:
            cat = _autocomplete_category(taxonomy, raw)
            if cat is None:
                # create new category; then move to group column
                taxonomy.add_category(raw, DEFAULT_GROUP)  # temp group; user will set group next
                t.category = titleish(raw)
                t.group = ""  # blank out group per spec if cat not already in a group
                t.confirmed = False
                state.col = COLUMN_GRP
                return
            # existing category
            t.category = cat
            grp_map = taxonomy.category_to_group()
            g = grp_map.get(norm_key(cat), "")
            if g:
                t.group = g
                t.confirmed = True
                upsert_rule_literal_description(rules, t.description, t.category, t.group)
                state.row = min(len(txns)-1, state.row + 1)
                state.col = COLUMN_CAT
            else:
                t.group = ""
                state.col = COLUMN_GRP
            return
        else:
            grp = _autocomplete_group(taxonomy, raw)
            if grp is None:
                taxonomy.add_group(raw)
                grp = titleish(raw)
            t.group = grp
            # if category just created and isn't in any group yet, attach it now
            if norm_key(t.category) != norm_key(DEFAULT_CATEGORY) and t.category:
                # attach category to this group if it's not in taxonomy yet
                taxonomy.add_category(t.category, grp)
            if _is_legit(t):
                t.confirmed = True
                upsert_rule_literal_description(rules, t.description, t.category, t.group)
                state.row = min(len(txns)-1, state.row + 1)
                state.col = COLUMN_CAT
            return

    # 3) plain Enter on existing value: approve if legit, else no-op
    if _is_legit(t):
        t.confirmed = True
        upsert_rule_literal_description(rules, t.description, t.category, t.group)
        state.row = min(len(txns)-1, state.row + 1)
        state.col = COLUMN_CAT

def _autocomplete_category(taxonomy: Taxonomy, typed: str) -> Optional[str]:
    typedk = norm_key(typed)
    if not typedk:
        return None
    best = None
    best_score = -1
    for _, cat, _ in taxonomy.compute_cat_ids():
        if norm_key(cat) == norm_key(DEFAULT_CATEGORY):
            continue
        ck = norm_key(cat)
        if ck.startswith(typedk):
            score = len(typedk)
        elif typedk in ck:
            score = max(0, len(typedk) - 1)
        else:
            score = 0
        if score > best_score:
            best_score = score
            best = cat
    # only accept if we have a real prefix match
    if best and norm_key(best).startswith(typedk):
        return best
    # exact case-insensitive match
    for _, cat, _ in taxonomy.compute_cat_ids():
        if norm_key(cat) == typedk:
            return cat
    return None

def _autocomplete_group(taxonomy: Taxonomy, typed: str) -> Optional[str]:
    typedk = norm_key(typed)
    if not typedk:
        return None
    for g in taxonomy.groups:
        if norm_key(g) == typedk:
            return g
    # prefix match best
    matches = [g for g in taxonomy.groups if norm_key(g).startswith(typedk)]
    if matches:
        matches.sort(key=lambda s: len(s))
        return matches[0]
    return None

def _handle_delete(txns: List[Txn], taxonomy: Taxonomy, state: UIState, categories_path: Path, groups_path: Path) -> None:
    t = txns[state.row]
    if state.col == COLUMN_CAT:
        t.category = DEFAULT_CATEGORY
        t.group = DEFAULT_GROUP
        t.confirmed = False
    else:
        t.group = ""
        t.confirmed = False

    used_cats = [x.category for x in txns]
    used_grps = [x.group for x in txns]

    taxonomy.remove_category_if_unused(t.category, used_cats)
    taxonomy.remove_group_if_unused(t.group, used_grps)

def _confirm_quit(stdscr, taxonomy: Taxonomy, txns: List[Txn], state: UIState,
                  rules_path: Path, rules, categories_path: Path, groups_path: Path,
                  out_csv: Path, orig_cols, meta) -> bool:
    h, w = stdscr.getmaxyx()
    msg = "Quit: (S)ave & quit, (Q)uit without saving, (Esc) cancel"
    stdscr.attron(curses.color_pair(8))
    stdscr.addstr(h-1, 0, msg[:w-1].ljust(w-1))
    stdscr.attroff(curses.color_pair(8))
    stdscr.refresh()
    while True:
        ch = stdscr.getch()
        if ch in (27,):  # Esc
            return False
        if ch in (ord('q'), ord('Q')):
            return True
        if ch in (ord('s'), ord('S')):
            _save_all(taxonomy, txns, state, rules_path, rules, categories_path, groups_path, out_csv, orig_cols, meta)
            return True

def _save_all(taxonomy: Taxonomy, txns: List[Txn], state: UIState,
              rules_path: Path, rules, categories_path: Path, groups_path: Path,
              out_csv: Path, orig_cols, meta) -> None:
    # persist taxonomy
    _save_taxonomy_files(taxonomy, categories_path, groups_path)
    # persist rules.json (spec: use rules.json)
    save_rules(rules_path, rules)
    # persist updated transactions CSV
    write_transactions(out_csv, orig_cols, meta, txns)

def _load_taxonomy(categories_path: Path, groups_path: Path) -> Taxonomy:
    groups: List[str] = []
    if groups_path.exists():
        groups = [line.strip() for line in groups_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cats: List[str] = []
    if categories_path.exists():
        cats = [line.strip() for line in categories_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Build initial group->cats map (we only have flat categories.txt today; group assignment happens via UI)
    group_to_cats = {g: [] for g in groups}

    # Always have Aaa/Uncategorized reserved per spec
    if not groups:
        groups = [DEFAULT_GROUP]
        group_to_cats = {DEFAULT_GROUP: []}

    # Choose a bucket for existing categories:
    # - Never use Aaa (reserved for Uncategorized only).
    # - Prefer the first non-default group if one exists.
    # - Otherwise create an "Unsorted" bucket group.
    bucket = None
    for g in groups:
        if norm_key(g) != norm_key(DEFAULT_GROUP):
            bucket = g
            break
    if bucket is None:
        bucket = "Unsorted"
        if norm_key(bucket) not in {norm_key(g) for g in groups}:
            groups.append(bucket)
            group_to_cats[bucket] = []

    for c in cats:
        if norm_key(c) == norm_key(DEFAULT_CATEGORY):
            continue
        group_to_cats.setdefault(bucket, []).append(c)

    tax = Taxonomy(groups=groups, group_to_cats=group_to_cats)
    tax.ensure_defaults()
    return tax

def _save_taxonomy_files(taxonomy: Taxonomy, categories_path: Path, groups_path: Path) -> None:
    taxonomy.sort_alpha()
    # groups.txt (one per line)
    groups = taxonomy.groups
    groups_path.write_text("\n".join(groups) + "\n", encoding="utf-8")
    # categories.txt: flat list (one per line) excluding Uncategorized
    cats = []
    for g in taxonomy.groups:
        if norm_key(g) == norm_key(DEFAULT_GROUP):
            continue
        for c in taxonomy.group_to_cats.get(g, []):
            if norm_key(c) == norm_key(DEFAULT_CATEGORY):
                continue
            cats.append(c)
    categories_path.write_text("\n".join(cats) + ("\n" if cats else ""), encoding="utf-8")

def _taxonomy_lines(taxonomy: Taxonomy, col_width: int = 27, max_cols: int = 5, max_rows: int | None = None) -> Tuple[List[List[str]], List[Tuple[int,int,int]]]:
    """Return columns of taxonomy lines and a mapping for highlighting categories by CatID.
    Returns (columns, cat_line_refs) where cat_line_refs contains tuples (cat_id, col_idx, line_idx).
    """
    cat_items = taxonomy.compute_cat_ids()
    # Build per-group blocks
    blocks = []
    cat_line_refs = []
    for g in taxonomy.groups:
        # group header
        header = f"{g}"
        lines = [header]
        # categories in this group
        if norm_key(g) == norm_key(DEFAULT_GROUP):
            cats = [DEFAULT_CATEGORY]
        else:
            cats = taxonomy.group_to_cats.get(g, [])
        for cat_id, cat, grp in cat_items:
            if norm_key(grp) != norm_key(g):
                continue
            if norm_key(cat) == norm_key(DEFAULT_CATEGORY) and norm_key(g) != norm_key(DEFAULT_GROUP):
                continue
            if norm_key(cat) == norm_key(DEFAULT_CATEGORY) and norm_key(g) == norm_key(DEFAULT_GROUP):
                lines.append(f"  {cat_id:>2} {cat}")
                cat_line_refs.append((cat_id, -1, -1))  # patched after layout
            elif norm_key(cat) != norm_key(DEFAULT_CATEGORY):
                lines.append(f"  {cat_id:>2} {cat}")
                cat_line_refs.append((cat_id, -1, -1))
        blocks.append(lines)

    # Flow blocks into columns, never ending a column with a group name
    columns: List[List[str]] = [[]]
    col_idx = 0
    line_idx = 0
    max_lines = None  # computed by caller via screen size; we'll just pack and let caller clip

    # Simple packing: append lines; let caller render top-half height clip and wrap.
    for block in blocks:
        # if last line in current column is group name and we would put group name at bottom, handled by render using available height
        for ln in block:
            columns[col_idx].append(ln)
            # start new column if too wide? handled by max_cols and caller height, but we keep to max_cols by splitting long lists evenly
    # Now split into up to max_cols columns by roughly equal line count
    all_lines = []
    for col in columns:
        all_lines.extend(col)
    if not all_lines:
        all_lines = [DEFAULT_GROUP, f"  1 {DEFAULT_CATEGORY}"]
    if max_rows is None:
        per = max(1, (len(all_lines) + max_cols - 1) // max_cols)
    else:
        per = max(1, max_rows)
    columns = [all_lines[i:i+per] for i in range(0, len(all_lines), per)]
    columns = columns[:max_cols]

    # patch cat_line_refs by scanning columns
    id_pat = __import__('re').compile(r"^\s+(\d+)\s+")
    refs = []
    for ci, col in enumerate(columns):
        for li, ln in enumerate(col):
            m = id_pat.match(ln)
            if m:
                refs.append((int(m.group(1)), ci, li))
    return columns, refs

def _draw(stdscr, taxonomy: Taxonomy, txns: List[Txn], state: UIState):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    top_h = max(3, h // 2)
    bot_h = h - top_h

    # Layout
    # Top: taxonomy
    stdscr.attron(curses.color_pair(4))
    stdscr.addstr(0, 0, " TAXONOMY ".ljust(w-1)[:w-1])
    stdscr.attroff(curses.color_pair(4))

    col_width = 27
    max_cols = min(5, max(1, w // col_width))
    max_rows = max(1, top_h - 1)  # fill first column top-to-bottom before moving right
    tax_cols, cat_refs = _taxonomy_lines(taxonomy, col_width=col_width, max_cols=max_cols, max_rows=max_rows)
    tax_cols = tax_cols[:max_cols]

    # Determine highlight set from digit_buffer
    highlight_ids = set()
    if state.digit_buffer:
        for cid, _, _ in cat_refs:
            if str(cid).startswith(state.digit_buffer):
                highlight_ids.add(cid)

    # render taxonomy lines
    for ci, col in enumerate(tax_cols):
        x = ci * col_width
        for li in range(1, min(top_h, len(col)+1)):  # start at line 1 (below header)
            txt = col[li-1][:col_width-1]
            attr = curses.color_pair(7)
            # highlight cat IDs prefix
            m = __import__('re').match(r"^\s+(\d+)\s+", txt)
            if m:
                cid = int(m.group(1))
                if cid in highlight_ids:
                    attr = curses.color_pair(5)
            stdscr.addstr(li, x, txt.ljust(col_width-1), attr)

    # Bottom header
    y0 = top_h
    stdscr.attron(curses.color_pair(4))
    stdscr.addstr(y0, 0, " TRANSACTIONS ".ljust(w-1)[:w-1])
    stdscr.attroff(curses.color_pair(4))

    # Right-side help area width
    help_w = max(24, int(w * 0.20))
    list_w = max(20, w - help_w - 1)

    # Inspector line (full description)
    inspector = txns[state.row].description if txns else ""
    inspector = " " + inspector
    stdscr.addstr(y0+1, 0, inspector[:w-1].ljust(w-1), curses.A_DIM)

    # Transactions table header
    header = "Num  Statement    Transaction  Description".ljust(46)
    header += "  CatID  Category".ljust(22)
    header += "  Group"
    stdscr.addstr(y0+2, 0, header[:list_w].ljust(list_w), curses.color_pair(4))

    # compute visible rows
    rows_y = y0 + 3
    visible = max(1, bot_h - 5)  # room for headers + footer
    # keep scroll in sync with focus
    if state.row < state.scroll:
        state.scroll = state.row
    if state.row >= state.scroll + visible:
        state.scroll = state.row - visible + 1

    cat_items = taxonomy.compute_cat_ids()
    cat_to_id = {norm_key(cat): cid for cid, cat, grp in cat_items}
    cat_to_group = taxonomy.category_to_group()

    for i in range(visible):
        idx = state.scroll + i
        if idx >= len(txns):
            break
        t = txns[idx]
        y = rows_y + i
        color = _color_for_txn(t)

        cat_id = cat_to_id.get(norm_key(t.category), 1 if norm_key(t.category)==norm_key(DEFAULT_CATEGORY) else 0)
        desc = t.description.replace("\n", " ")
        desc_trunc = (desc[:30] + "…") if len(desc) > 31 else desc

        line = f"{t.idx:>3}  {t.statement_date:<11}  {t.transaction_date:<11}  {desc_trunc:<32}  {cat_id:>5}  {t.category:<12}  {t.group:<12}"
        line = line[:list_w-1]
        # focus cell highlighting
        if idx == state.row:
            # draw base line
            stdscr.addstr(y, 0, line.ljust(list_w-1), color)
            # overlay focus cell
            # determine column spans
            cat_start = line.find(str(cat_id).rjust(5))
            if cat_start < 0:
                cat_start = 0
            # We'll highlight either Category or Group field
            if state.col == COLUMN_CAT:
                # category field approx after cat_id + two spaces
                cat_field_start = cat_start + 7
                cat_field_len = 12
                stdscr.addstr(y, cat_field_start, line[cat_field_start:cat_field_start+cat_field_len].ljust(cat_field_len), curses.color_pair(6))
                # show autocomplete ghost if in edit_mode
                if state.edit_mode:
                    ghost = _ghost_completion_category(taxonomy, state.edit_buffer)
                    if ghost:
                        stdscr.addstr(y, cat_field_start, ghost[:cat_field_len].ljust(cat_field_len), curses.A_DIM | curses.color_pair(6))
            else:
                grp_field_start = cat_start + 7 + 12 + 2
                grp_field_len = 12
                stdscr.addstr(y, grp_field_start, line[grp_field_start:grp_field_start+grp_field_len].ljust(grp_field_len), curses.color_pair(6))
                if state.edit_mode:
                    ghost = _ghost_completion_group(taxonomy, state.edit_buffer)
                    if ghost:
                        stdscr.addstr(y, grp_field_start, ghost[:grp_field_len].ljust(grp_field_len), curses.A_DIM | curses.color_pair(6))
        else:
            stdscr.addstr(y, 0, line.ljust(list_w-1), color)

    # Help panel
    hx = list_w + 1
    stdscr.addstr(y0+2, hx, "Keys", curses.color_pair(4))
    help_lines = [
        "0-9    cat id",
        "Enter  approve/assign",
        "a-z    type name",
        "Del    clear cat/grp",
        "Bksp   undo keystroke",
        "q      quit",
    ]
    for i, ln in enumerate(help_lines):
        if y0+3+i < h:
            stdscr.addstr(y0+3+i, hx, ln[:help_w-1].ljust(help_w-1), curses.A_DIM)

    # Footer message / SAVE button
    footer_y = h - 1
    if _all_confirmed(txns):
        btn = "   [  SAVE  ]   (press S)   "
        x = max(0, (w - len(btn)) // 2)
        stdscr.addstr(footer_y, 0, " " * (w-1))
        stdscr.addstr(footer_y, x, btn[:w-1], curses.A_BOLD | curses.color_pair(5))
    else:
        msg = ""
        if state.message and time.time() < state.message_ts:
            msg = state.message
        elif state.digit_buffer:
            msg = f"CatID: {state.digit_buffer}"
        elif state.edit_mode:
            msg = f"Typing: {state.edit_buffer}"
        stdscr.addstr(footer_y, 0, msg[:w-1].ljust(w-1), curses.A_DIM)

    stdscr.refresh()

def _ghost_completion_category(taxonomy: Taxonomy, typed: str) -> str:
    typed = typed or ""
    typedk = norm_key(typed)
    if not typedk:
        return typed
    # best prefix match
    best = None
    for _, cat, _ in taxonomy.compute_cat_ids():
        if norm_key(cat).startswith(typedk):
            best = cat
            break
    if best:
        return titleish(best)
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
