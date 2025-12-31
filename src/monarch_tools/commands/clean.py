from __future__ import annotations

from pathlib import Path
from typing import List


def cmd_clean(argv: List[str]) -> int:
    """Reset taxonomy + rules files under ./data to known-good defaults."""
    import argparse

    from monarch_tools.defaults import read_default_text

    ap = argparse.ArgumentParser(prog="monarch-tools clean")
    ap.add_argument(
        "--data-dir",
        default="data",
        help="Directory containing categories.txt, groups.txt, and rules.json (default: ./data)",
    )
    ns = ap.parse_args(argv)

    data_dir = Path(ns.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    targets = [
        ("categories.txt", data_dir / "categories.txt"),
        ("groups.txt", data_dir / "groups.txt"),
        ("rules.json", data_dir / "rules.json"),
    ]

    for default_name, target in targets:
        target.write_text(read_default_text(default_name), encoding="utf-8")

    print(f"Reset: {data_dir/'categories.txt'}")
    print(f"Reset: {data_dir/'groups.txt'}")
    print(f"Reset: {data_dir/'rules.json'}")
    return 0
