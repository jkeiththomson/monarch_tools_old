from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .text_utils import norm_key

# rules.json compatibility:
#  - List format:
#       [ {"description": "...", "category": "...", "group": "..."}, ... ]
#  - Dict format (your current default):
#       { "merchants": { "<DESCRIPTION>": {"category": "...", "group": "..."}, ... } }
#
# This module supports both, and preserves the on-disk format on save.

RulesObj = Union[List[Dict[str, Any]], Dict[str, Any]]

def load_rules(path: Path) -> RulesObj:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_rules(path: Path, rules: RulesObj) -> None:
    path.write_text(json.dumps(rules, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def _find_in_merchants_map(merchants: Dict[str, Any], description: str) -> Optional[Dict[str, Any]]:
    direct = merchants.get(description)
    if isinstance(direct, dict):
        return {"description": description, **direct}

    dk = norm_key(description)
    for k, v in merchants.items():
        if norm_key(str(k)) == dk and isinstance(v, dict):
            return {"description": str(k), **v}
    return None

def find_rule_for_description(rules: RulesObj, description: str) -> Optional[Dict[str, Any]]:
    dk = norm_key(description)

    if isinstance(rules, list):
        for r in rules:
            if isinstance(r, dict) and norm_key(str(r.get("description", ""))) == dk:
                return r
        return None

    if isinstance(rules, dict):
        merchants = rules.get("merchants")
        if isinstance(merchants, dict):
            return _find_in_merchants_map(merchants, description)
        return None

    return None

def upsert_rule_literal_description(rules: RulesObj, description: str, category: str, group: str) -> None:
    """Map literal description -> chosen category/group."""

    if isinstance(rules, list):
        existing = find_rule_for_description(rules, description)
        if existing is None:
            rules.append({"description": description, "category": category, "group": group})
        else:
            existing["category"] = category
            existing["group"] = group
        return

    if isinstance(rules, dict):
        merchants = rules.get("merchants")
        if not isinstance(merchants, dict):
            merchants = {}
            rules["merchants"] = merchants
        merchants[description] = {"category": category, "group": group}
        return
