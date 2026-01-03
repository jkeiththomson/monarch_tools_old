from __future__ import annotations

import sys

def _print_help() -> None:
    print("usage: python -m monarch_tools <command> [args]\n")
    print("commands:")
    print("  hello")
    print("  extract")
    print("  categorize")
    print("  clean")

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    cmd = argv[0]
    rest = argv[1:]

    if cmd == "hello":
        from .commands.hello import cmd_hello
        return cmd_hello(rest)

    if cmd == "extract":
        # Extract may not exist in some minimal installs; fail clearly.
        try:
            from .commands.extract import cmd_extract
        except Exception as e:
            print("extract command is not available (commands/extract.py missing or import failed).")
            print(f"details: {e}")
            return 2
        return cmd_extract(rest)

    if cmd == "categorize":
        try:
            from .commands.categorize import cmd_categorize
        except Exception as e:
            print("categorize command is not available (commands/categorize.py missing or import failed).")
            print(f"details: {e}")
            return 2
        return cmd_categorize(rest)

    if cmd == "clean":
        from .commands.clean import cmd_clean
        return cmd_clean(rest)

    print(f"unknown command: {cmd}")
    _print_help()
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
