from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict, List, Optional

from .commands.hello import cmd_hello
from .commands.help import cmd_help
from .commands.version import cmd_version
from .commands.extract import cmd_extract
from .commands.categorize import cmd_categorize


CommandFn = Callable[[List[str]], int]


def registry() -> Dict[str, CommandFn]:
    return {
        "hello": cmd_hello,
        "help": cmd_help,
        "version": cmd_version,
        "extract": cmd_extract,
        "categorize": cmd_categorize,
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="python -m monarch_tools", add_help=False)
    parser.add_argument("command", nargs="?", help="Command to run")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)

    cmds = registry()

    if not ns.command:
        return cmd_help([])

    if ns.command in ("-h", "--help"):
        return cmd_help([])
    if ns.command in ("-V", "--version"):
        return cmd_version([])

    fn = cmds.get(ns.command)
    if not fn:
        print(f"Unknown command: {ns.command}", file=sys.stderr)
        return cmd_help([])

    args = list(ns.args)
    if args[:1] == ["--"]:
        args = args[1:]

    return fn(args)


if __name__ == "__main__":
    raise SystemExit(main())