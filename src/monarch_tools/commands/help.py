from __future__ import annotations

from typing import List


def cmd_help(argv: List[str]) -> int:
    # Import inside the function to avoid circular-import issues at module import time.
    from monarch_tools.__main__ import registry

    print("monarch-tools\n")
    print("Usage:")
    print("  python -m monarch_tools <command> [args...]\n")
    print("Commands:")

    cmds = registry()
    for name in sorted(cmds.keys()):
        fn = cmds[name]
        desc = ""
        if getattr(fn, "__doc__", None):
            desc = (fn.__doc__ or "").strip().splitlines()[0].strip()
        if not desc:
            fallback = {
                "hello": "Sanity check the CLI wiring",
                "version": "Print package version",
                "help": "Show this help",
                "extract": "Extract statement CSVs from a PDF",
                "categorize": "Categorize transactions using rules + taxonomy",
                "assign": "Interactive rule-building from unmatched merchants",
                "assign_tui": "Full-screen TUI for assigning merchants",
                "clean": "Reset taxonomy to Uncategorized/Other and clear rules.json",
            }
            desc = fallback.get(name, "")

        print(f"  {name:<10} {desc}")

    print("")
    return 0
