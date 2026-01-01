from __future__ import annotations

from importlib import resources


def read_default_text(filename: str) -> str:
    """Read a default template shipped inside monarch_tools/defaults/."""
    return resources.files(__package__).joinpath(filename).read_text(encoding="utf-8")
