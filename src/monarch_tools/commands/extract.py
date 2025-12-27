from __future__ import annotations

import argparse
from pathlib import Path

from monarch_tools.extractors.chase.activity import extract_activity


def cmd_extract(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="monarch-tools extract")
    p.add_argument("--pdf", required=True, help="Path to statement PDF")
    p.add_argument("--out", required=True, help="Output directory")
    args = p.parse_args(argv)

    pdf_path = Path(args.pdf).expanduser()
    out_dir = Path(args.out).expanduser()

    if not pdf_path.exists():
        raise SystemExit(f"ERROR: PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise SystemExit(f"ERROR: Not a PDF: {pdf_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    outputs = extract_activity(pdf_path=pdf_path, out_dir=out_dir)

    print("wrote:")
    for k, v in outputs.items():
        print(f"  {k}: {v}")
    return 0