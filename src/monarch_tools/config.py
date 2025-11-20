"""Simple TOML-based config for monarch_tools.

Currently this is used to store per-account metadata such as opening balances.
The default location is `data/config.toml` relative to the project root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

try:  # Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


DEFAULT_CONFIG_PATH = Path("data/config.toml")


def _ensure_tomllib():
    if tomllib is None:  # pragma: no cover - older Python fallback
        raise RuntimeError(
            "tomllib is not available; please run monarch_tools under Python 3.11+ "
            "or install 'tomli' and update this module to import it."
        )


def load_config(path: Path | None = None) -> Dict[str, Any]:
    """Load config from TOML, returning a dict.

    If the file does not exist, an empty dict is returned.
    """
    _ensure_tomllib()
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def save_config(cfg: Dict[str, Any], path: Path | None = None) -> None:
    """Save config to TOML.

    We currently support a very small subset of TOML:

        [accounts."Account Name"]
        opening_balance = 1234.56
    """
    path = path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    accounts = cfg.get("accounts", {})
    if accounts:
        for name, info in accounts.items():
            lines.append(f'[accounts."{name}"]')
            if isinstance(info, dict):
                ob = info.get("opening_balance")
                if ob is not None:
                    lines.append(f"opening_balance = {float(ob):.2f}")
            lines.append("")  # blank line between accounts

    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def ensure_account_opening_balance(
    account_name: str,
    path: Path | None = None,
) -> float | None:
    """Ensure we have an opening balance recorded for the given account.

    - If an opening balance already exists in config, return it.
    - Otherwise, prompt the user once:
        Enter opening balance for account "Name" (blank to skip):

      If the user enters a parsable number, we store it and return it.
      If they press Enter or enter something unparsable, we leave it unset
      and return None.
    """
    path = path or DEFAULT_CONFIG_PATH
    cfg = load_config(path)
    accounts = cfg.setdefault("accounts", {})
    info = accounts.get(account_name)
    if isinstance(info, dict):
        ob = info.get("opening_balance")
        if ob is not None:
            return float(ob)

    # No opening balance yet; ask user.
    try:
        user_input = input(
            f'Enter opening balance for account "{account_name}" (blank to skip): '
        ).strip()
    except EOFError:  # pragma: no cover - non-interactive environments
        user_input = ""

    if not user_input:
        print(f"No opening balance recorded for account {account_name!r}.")
        return None

    # Try to parse a float, tolerating commas.
    try:
        val = float(user_input.replace(",", ""))
    except ValueError:
        print("Could not parse opening balance; leaving it unset.")
        return None

    info = accounts.setdefault(account_name, {})
    info["opening_balance"] = float(val)
    save_config(cfg, path)
    print(
        f"Saved opening balance {val:.2f} for account {account_name!r} in {path}"
    )
    return float(val)
