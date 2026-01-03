from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
from .taxonomy import DEFAULT_CATEGORY, DEFAULT_GROUP
from .text_utils import titleish

@dataclass
class Txn:
    idx: int
    statement_date: str
    transaction_date: str
    description: str
    category: str
    group: str
    # UI state
    confirmed: bool = False

def _pick_col(cols: List[str], candidates: List[str]) -> str:
    lower = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return ""

def load_transactions(csv_path: Path) -> Tuple[List[Txn], List[str], Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("Input CSV has no header row.")
        cols = list(reader.fieldnames)
        col_stmt = _pick_col(cols, ["statement_date", "Statement Date", "Statement"])
        col_txn = _pick_col(cols, ["transaction_date", "Transaction Date", "Transaction"])
        col_desc = _pick_col(cols, ["description", "Description", "Merchant", "Payee"])
        col_cat  = _pick_col(cols, ["category", "Category"])
        col_grp  = _pick_col(cols, ["group", "Group"])
        for r in reader:
            rows.append(r)
    txns: List[Txn] = []
    for i, r in enumerate(rows, start=1):
        stmt = r.get(col_stmt, "") if col_stmt else ""
        tdt  = r.get(col_txn, "") if col_txn else ""
        desc = r.get(col_desc, "") if col_desc else ""
        cat  = r.get(col_cat, "") if col_cat else ""
        grp  = r.get(col_grp, "") if col_grp else ""
        cat = titleish(cat) if cat else DEFAULT_CATEGORY
        grp = titleish(grp) if grp else DEFAULT_GROUP
        txns.append(Txn(i, stmt, tdt, desc, cat, grp, confirmed=False))
    meta = {"col_stmt": col_stmt, "col_txn": col_txn, "col_desc": col_desc, "col_cat": col_cat, "col_grp": col_grp}
    return txns, cols, meta

def write_transactions(csv_path: Path, original_cols: List[str], meta: Dict[str, str], txns: List[Txn]) -> None:
    cols = list(original_cols)
    col_cat = meta.get("col_cat") or "Category"
    col_grp = meta.get("col_grp") or "Group"
    if col_cat not in cols:
        cols.append(col_cat)
    if col_grp not in cols:
        cols.append(col_grp)

    # We re-read original file to preserve other columns
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for i, (row, txn) in enumerate(zip(rows, txns)):
        row[col_cat] = txn.category
        row[col_grp] = txn.group

    tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)
