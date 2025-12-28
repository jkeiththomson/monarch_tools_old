from __future__ import annotations

import argparse
from pathlib import Path

from monarch_tools.extractors import extract_chase_activity


def cmd_extract(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="monarch-tools extract")
    p.add_argument("--pdf", required=True, help="Path to statement PDF")
    p.add_argument("--out", required=True, help="Output directory")
    args = p.parse_args(argv)

    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_csv = out_dir / f"{pdf_path.stem}.monarch.csv"

    result = extract_chase_activity(pdf_path=pdf_path, out_csv=out_csv)
    print(f"wrote:\n  monarch: {result}")
    return 0
