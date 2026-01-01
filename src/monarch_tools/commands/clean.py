from __future__ import annotations

from pathlib import Path

from monarch_tools.defaults import read_default_text


def cmd_clean(argv) -> int:
    """Reset data/categories.txt, data/groups.txt, data/rules.json to packaged defaults."""
    root = Path.cwd()

    targets = {
        root / "data" / "categories.txt": "categories.txt",
        root / "data" / "groups.txt": "groups.txt",
        root / "data" / "rules.json": "rules.json",
    }

    for dst, template_name in targets.items():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(read_default_text(template_name), encoding="utf-8")
        print(f"Reset: {dst.as_posix()}")

    return 0
