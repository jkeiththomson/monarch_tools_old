from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from .text_utils import norm_key

@dataclass
class Rule:
    description: str
    category: str
    group: str

def load_rules(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_rules(path: Path, rules: List[Dict[str, Any]]) -> None:
    path.write_text(json.dumps(rules, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def find_rule_for_description(rules: List[Dict[str, Any]], description: str) -> Optional[Dict[str, Any]]:
    dk = norm_key(description)
    for r in rules:
        if norm_key(str(r.get("description",""))) == dk:
            return r
    return None

def upsert_rule_literal_description(rules: List[Dict[str, Any]], description: str, category: str, group: str) -> None:
    """Per spec: for now, copy literal description into rules.json and map to chosen category."""
    existing = find_rule_for_description(rules, description)
    if existing is None:
        rules.append({"description": description, "category": category, "group": group})
    else:
        existing["category"] = category
        existing["group"] = group
