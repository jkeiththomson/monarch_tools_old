"""Top-level CLI entry point for monarch_tools."""

import argparse

from .hello import cmd_hello
from .name import cmd_name
from .help import cmd_help
from .activity import cmd_activity
from .categorize import cmd_categorize
from .monarchcsv import cmd_monarch
from .sanity import cmd_sanity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monarch-tools",
        description="Monarch Money toolbox CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # --- hello ---
    p_hello = sub.add_parser("hello", help="Say hello")
    p_hello.set_defaults(func=cmd_hello)

    # --- name ---
    p_name = sub.add_parser("name", help="Print your name")
    p_name.add_argument("who", help="Name to print")
    p_name.set_defaults(func=cmd_name)

    # --- help ---
    p_help = sub.add_parser("help", help="Show this help message")
    p_help.set_defaults(func=cmd_help)

    # --- activity ---
    p_activity = sub.add_parser(
        "activity",
        help="Extract account activity from a statement PDF",
        description=(
            "Parse a credit card statement PDF (currently Chase only) and "
            "emit an <stem>.activity.csv file plus a summary CSV."
        ),
    )
    p_activity.add_argument(
        "type",
        help="Statement type (e.g. 'chase')",
    )
    p_activity.add_argument(
        "pdf",
        help="Path to the input statement PDF.",
    )
    p_activity.add_argument(
        "--out-dir",
        default="out",
        help="Directory for output CSV files (default: %(default)s).",
    )
    p_activity.set_defaults(func=cmd_activity)

    # --- categorize ---
    p_categorize = sub.add_parser(
        "categorize",
        help="Interactively assign categories to activity rows",
        description=(
            "Walk an <stem>.activity.csv file and interactively build/update "
            "rules.json, categories.txt, and groups.txt."
        ),
    )
    p_categorize.add_argument(
        "categories_txt",
        help="Path to categories.txt",
    )
    p_categorize.add_argument(
        "groups_txt",
        help="Path to groups.txt",
    )
    p_categorize.add_argument(
        "rules_json",
        help="Path to rules.json",
    )
    p_categorize.add_argument(
        "activity_csv",
        help="Path to <stem>.activity.csv produced by the 'activity' command.",
    )
    p_categorize.add_argument(
        "--dry-run",
        action="store_true",
        help="Run categorization without writing any output files.",
    )
    p_categorize.set_defaults(func=cmd_categorize)

    # --- monarch ---
    p_monarch = sub.add_parser(
        "monarch",
        help="Export Monarch-compatible CSV for a single account",
        description=(
            "Generate a <stem>.monarch.csv file suitable for Monarch Money's "
            "single-account CSV import, using an activity CSV plus rules.json."
        ),
    )
    p_monarch.add_argument(
        "account",
        help="Monarch account name for these transactions (must match an existing account in Monarch).",
    )
    p_monarch.add_argument(
        "rules_json",
        help="Path to rules.json used for canonical merchants and categories.",
    )
    p_monarch.add_argument(
        "activity_csv",
        help="Path to <stem>.activity.csv produced by the 'activity' command.",
    )
    p_monarch.add_argument(
        "--out",
        metavar="PATH",
        help=(
            "Optional explicit output path for the Monarch CSV. "
            "Defaults to <stem>.monarch.csv alongside the activity CSV."
        ),
    )
    p_monarch.set_defaults(func=cmd_monarch)

    # --- sanity ---
    p_sanity = sub.add_parser(
        "sanity",
        help="Compare totals between activity CSV and Monarch CSV",
        description=(
            "Print a side-by-side comparison of payments/purchases counts and "
            "totals from an activity CSV and its corresponding .monarch.csv."
        ),
    )
    p_sanity.add_argument(
        "activity_csv",
        help="Path to <stem>.activity.csv file.",
    )
    p_sanity.add_argument(
        "monarch_csv",
        nargs="?",
        help="Optional path to .monarch.csv. If omitted, derived from activity filename.",
    )
    p_sanity.set_defaults(func=cmd_sanity)

    return parser


def main() -> int:
    parser = build_parser()
    ns = parser.parse_args()
    return ns.func(ns)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
