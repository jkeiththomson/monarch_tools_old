from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple


@dataclass(frozen=True)
class Command:
    help: str
    fn: Callable[[List[str]], int]


def _import_commands() -> Dict[str, Command]:
    # Import lazily so failures are localized to the command being used.
    from .commands.hello import cmd_hello
    from .commands.help import cmd_help
    from .commands.version import cmd_version
    from .commands.extract import cmd_extract
    from .commands.categorize import cmd_categorize

    commands: Dict[str, Command] = {
        "hello": Command("Sanity check the CLI wiring", cmd_hello),
        "help": Command("Show this help", cmd_help),
        "version": Command("Print package version", cmd_version),
        "extract": Command("Extract statement CSVs from a PDF", cmd_extract),
        "categorize": Command("Categorize transactions using rules + taxonomy (interactive TUI).", cmd_categorize),
    }

    # clean is optional depending on what patch set is applied
    try:
        from .commands.clean import cmd_clean  # type: ignore
        commands["clean"] = Command("Reset baseline taxonomy + rules in data/*", cmd_clean)
    except Exception:
        pass

    return commands


def _print_usage(commands: Dict[str, Command]) -> None:
    print("monarch-tools")
    print()
    print("Usage:")
    print("  python -m monarch_tools <command> [args...]")
    print()
    print("Commands:")
    width = max(len(k) for k in commands.keys()) if commands else 10
    for name in sorted(commands.keys()):
        print(f"  {name.ljust(width)} {commands[name].help}")


def main(argv: List[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    commands = _import_commands()

    if not argv or argv[0] in ("-h", "--help", "help"):
        # If user typed `help`, delegate to cmd_help so it can show per-command help.
        if argv and argv[0] == "help":
            return commands["help"].fn(argv[1:])
        _print_usage(commands)
        return 0

    cmd = argv[0]
    cmd_argv = argv[1:]

    if cmd not in commands:
        print(f"Unknown command: {cmd}")
        _print_usage(commands)
        return 2

    return commands[cmd].fn(cmd_argv)


if __name__ == "__main__":
    raise SystemExit(main())
