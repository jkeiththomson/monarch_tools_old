from __future__ import annotations

import csv
from pathlib import Path


def _stem(p: Path) -> str:
    # "20180112-statements-9391.pdf" -> "20180112-statements-9391"
    return p.name[:-4] if p.name.lower().endswith(".pdf") else p.stem


def extract_activity(*, pdf_path: Path, out_dir: Path) -> dict[str, Path]:
    """
    Phase 2: contract-first stub.

    Creates 3 CSVs with headers so the pipeline can be wired and tested.
    We'll replace this with real pdfplumber parsing next.
    """
    stem = _stem(pdf_path)

    summary_csv = out_dir / f"{stem}.summary.csv"
    activity_csv = out_dir / f"{stem}.activity.csv"
    monarch_csv = out_dir / f"{stem}.monarch.csv"

    # summary.csv: key/value rows (easy to extend)
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Key", "Value"])
        w.writerow(["SourcePDF", str(pdf_path)])
        w.writerow(["Extractor", "chase"])
        w.writerow(["Status", "stub_phase_2"])

    # activity.csv: stable transaction schema
    with activity_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Amount", "Type"])

    # monarch.csv: minimal import-like schema (we’ll evolve this)
    with monarch_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Merchant", "Amount", "Category", "Account", "Notes"])

    return {
        "summary": summary_csv,
        "activity": activity_csv,
        "monarch": monarch_csv,
    }