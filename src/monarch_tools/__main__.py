from __future__ import annotations
from .commands.clean import cmd_clean
import argparse
import sys
from typing import Callable, Dict, List, Optional

CommandFn = Callable[[List[str]], int]


def _lazy(mod: str, fn_name: str) -> CommandFn:
    """Return a command function that imports its implementation lazily.

    This prevents unrelated commands (e.g., `extract` and its PDF deps) from
    breaking the whole CLI when you're only running `categorize`.
    """
    def _runner(argv: List[str]) -> int:
        module = __import__(mod, fromlist=[fn_name])
        fn = getattr(module, fn_name)
        return fn(argv)
    return _runner


def registry() -> Dict[str, CommandFn]:
    return {
        "hello": _lazy("monarch_tools.commands.hello", "cmd_hello"),
        "help": _lazy("monarch_tools.commands.help", "cmd_help"),
        "version": _lazy("monarch_tools.commands.version", "cmd_version"),
        "extract": _lazy("monarch_tools.commands.extract", "cmd_extract"),
        "categorize": _lazy("monarch_tools.commands.categorize", "cmd_categorize"),
        # Keep these if present in your repo; harmless if you don't call them.
        "assign": _lazy("monarch_tools.commands.assign", "cmd_assign"),
        "assign_tui": _lazy("monarch_tools.commands.assign_tui", "cmd_assign_tui"),
        "clean": _lazy("monarch_tools.commands.clean", "cmd_clean"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="python -m monarch_tools", add_help=False)
    parser.add_argument("command", nargs="?", help="Command to run")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)

    cmds = registry()

    if not ns.command:
        return cmds["help"]([])

    if ns.command in ("-h", "--help"):
        return cmds["help"]([])
    if ns.command in ("-V", "--version"):
        return cmds["version"]([])

    fn = cmds.get(ns.command)
    if not fn:
        print(f"Unknown command: {ns.command}", file=sys.stderr)
        return cmds["help"]([])

    args = list(ns.args)
    if args[:1] == ["--"]:
        args = args[1:]

    return fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
