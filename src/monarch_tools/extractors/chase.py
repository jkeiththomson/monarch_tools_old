from __future__ import annotations

import csv
from pathlib import Path

from .chase_legacy import extract_activity


def extract_chase_activity(pdf_path: Path, out_csv: Path) -> Path:
    pdf_path = pdf_path.expanduser().resolve()
    out_csv = out_csv.expanduser().resolve()
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    activity_csv_path = Path(extract_activity(str(pdf_path), str(out_csv.parent))).resolve()

    statement_date = _infer_statement_date_from_filename(pdf_path.name)

    _write_monarch_csv_from_activity(
        activity_csv=activity_csv_path,
        out_csv=out_csv,
        statement_date=statement_date,
    )

    return out_csv


def _infer_statement_date_from_filename(filename: str) -> str:
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    if len(stem) >= 8 and stem[:8].isdigit():
        y, m, d = stem[0:4], stem[4:6], stem[6:8]
        return f"{y}-{m}-{d}"
    return ""


def _write_monarch_csv_from_activity(activity_csv: Path, out_csv: Path, statement_date: str) -> None:
    with activity_csv.open("r", newline="", encoding="utf-8") as f_in, out_csv.open(
        "w", newline="", encoding="utf-8"
    ) as f_out:
        reader = csv.reader(f_in)

        w = csv.writer(f_out)
        w.writerow(["statement_date", "date", "description", "amount", "group", "category"])

        header_seen = False
        for row in reader:
            if not row:
                if header_seen:
                    break
                continue

            if not header_seen:
                if [c.strip().lower() for c in row] == ["date", "description", "amount"]:
                    header_seen = True
                continue

            if len(row) < 3:
                continue

            date_s, desc, amt = row[0].strip(), row[1].strip(), row[2].strip()
            w.writerow([statement_date, date_s, desc, amt, "", ""])
