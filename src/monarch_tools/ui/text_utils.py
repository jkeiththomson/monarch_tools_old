from __future__ import annotations

import re

def titleish(s: str) -> str:
    """Capitalize first letter of each word, but keep standalone 'a' lowercase unless it's the first word.
    Implements the spec's display normalization rule.
    """
    s = (s or "").strip()
    if not s:
        return s
    words = re.split(r"(\s+)", s)
    out = []
    first_word = True
    for w in words:
        if w.isspace() or w == "":
            out.append(w)
            continue
        low = w.lower()
        if low == "a" and not first_word:
            out.append("a")
        else:
            out.append(low[:1].upper() + low[1:])
        if w.strip():
            first_word = False
    return "".join(out)

def norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())
