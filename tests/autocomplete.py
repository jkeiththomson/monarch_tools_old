#!/usr/bin/env python3
"""
Category Autocomplete (reference implementation)

Implements the spec:
- Normalize labels and queries consistently
- Hybrid matching: token-prefix, substring, subsequence, fuzzy (Damerau-Levenshtein)
- Deterministic scoring + tie-breakers
- Optional prefix index for speed
- Simple interactive CLI demo

Usage:
  python autocomplete.py --categories categories.txt
  python autocomplete.py --categories categories.txt --query "gas elec"
  python autocomplete.py --categories categories.txt --interactive
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


# ----------------------------
# Normalization
# ----------------------------

_PUNCT_TO_SPACE_RE = re.compile(r"[\/\-\.,'()\[\]{}:;!?\"`~|\\]+")

def _strip_diacritics(s: str) -> str:
    # NFKD splits accents into combining marks; remove them.
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

def normalize(s: str) -> str:
    """
    Normalization rules:
      1) Unicode NFKD + remove diacritics
      2) lowercase
      3) & -> and
      4) punctuation -> spaces
      5) collapse whitespace
      6) trim
    """
    s = _strip_diacritics(s)
    s = s.lower()
    s = s.replace("&", " and ")
    s = _PUNCT_TO_SPACE_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ----------------------------
# Helpers
# ----------------------------

def slugify(label: str) -> str:
    # stable-ish slug
    s = normalize(label)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "item"

def is_subsequence(query_compact: str, target_norm: str) -> bool:
    """
    Checks if query_compact letters appear in order within target_norm letters.
    Spaces in target are ignored implicitly by scanning full string.
    """
    if not query_compact:
        return True
    it = iter(target_norm.replace(" ", ""))
    for ch in query_compact:
        for t in it:
            if t == ch:
                break
        else:
            return False
    return True

def damerau_levenshtein(a: str, b: str, max_dist: Optional[int] = None) -> int:
    """
    Optimal String Alignment distance (Damerau-Levenshtein variant).
    Good enough for short strings like category labels.
    If max_dist is provided, can early-exit once distance exceeds it.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la

    # Quick bound
    if max_dist is not None and abs(la - lb) > max_dist:
        return max_dist + 1

    # DP matrix
    dp = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        dp[i][0] = i
    for j in range(lb + 1):
        dp[0][j] = j

    for i in range(1, la + 1):
        row_min = None
        ai = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ai == b[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,      # deletion
                dp[i][j - 1] + 1,      # insertion
                dp[i - 1][j - 1] + cost  # substitution
            )
            # transposition
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                dp[i][j] = min(dp[i][j], dp[i - 2][j - 2] + 1)

            row_min = dp[i][j] if row_min is None else min(row_min, dp[i][j])

        if max_dist is not None and row_min is not None and row_min > max_dist:
            return max_dist + 1

    return dp[la][lb]


# ----------------------------
# Data model
# ----------------------------

@dataclass(frozen=True)
class CategoryItem:
    id: str
    label: str
    norm: str
    tokens: Tuple[str, ...]
    aliases: Tuple[str, ...] = ()

    @staticmethod
    def from_label(label: str, aliases: Optional[Sequence[str]] = None) -> "CategoryItem":
        n = normalize(label)
        toks = tuple(n.split()) if n else tuple()
        al = tuple(aliases or ())
        return CategoryItem(
            id=slugify(label),
            label=label,
            norm=n,
            tokens=toks,
            aliases=al
        )


# ----------------------------
# Autocomplete Engine
# ----------------------------

@dataclass
class MatchResult:
    item: CategoryItem
    score: float
    prefix_coverage: int

class CategoryAutocomplete:
    def __init__(
        self,
        items: Sequence[CategoryItem],
        *,
        prefix_cap: int = 6,
        fuzzy_max_dist: int = 2,
        enable_index: bool = True
    ):
        self.items = list(items)
        self.prefix_cap = max(1, prefix_cap)
        self.fuzzy_max_dist = max(0, fuzzy_max_dist)

        # Optional prefix index: prefix -> set(item_index)
        self._prefix_index: Dict[str, Set[int]] = {}
        if enable_index:
            self._build_prefix_index()

    def _build_prefix_index(self) -> None:
        idx: Dict[str, Set[int]] = {}
        for i, it in enumerate(self.items):
            for tok in it.tokens:
                # index prefixes up to cap
                for k in range(1, min(len(tok), self.prefix_cap) + 1):
                    p = tok[:k]
                    idx.setdefault(p, set()).add(i)
        self._prefix_index = idx

    def _candidate_indices(self, q_tokens: List[str]) -> Set[int]:
        if not q_tokens or not self._prefix_index:
            return set(range(len(self.items)))

        cand: Set[int] = set()
        for qt in q_tokens:
            qt = qt[: self.prefix_cap]
            if not qt:
                continue
            hit = self._prefix_index.get(qt)
            if hit:
                cand |= hit

        # If index yields nothing, fall back to full scan (still cheap for small lists)
        return cand or set(range(len(self.items)))

    # --- Scoring components (tunable) ---
    EXACT_MATCH = 1000
    TOKEN_PREFIX = 200
    WHOLE_WORD = 80
    SUBSTRING = 60
    TOKENS_IN_ORDER = 80
    STARTS_WITH_LABEL = 120

    def _score_one_string(
        self,
        q_norm: str,
        q_tokens: List[str],
        q_compact: str,
        target_norm: str,
        target_tokens: Tuple[str, ...]
    ) -> Tuple[float, int, bool, bool]:
        """
        Score query vs a target string (label or alias).
        Returns (score, prefix_coverage, had_any_match, used_fuzzy)
        """
        score = 0.0
        prefix_coverage = 0
        used_fuzzy = False
        had_any_match = False

        if not q_norm:
            return 0.0, 0, False, False

        # Exact
        if q_norm == target_norm:
            return float(self.EXACT_MATCH), len(q_tokens), True, False

        # Starts-with label
        if target_norm.startswith(q_norm):
            score += self.STARTS_WITH_LABEL
            had_any_match = True

        # Substring
        if q_norm in target_norm:
            score += self.SUBSTRING
            had_any_match = True

        # Token-prefix + whole-word
        # For each query token, see if it matches any target token prefix.
        for qt in q_tokens:
            best_for_token = 0
            if not qt:
                continue
            for tt in target_tokens:
                if tt.startswith(qt):
                    best_for_token = max(best_for_token, self.TOKEN_PREFIX)
                    had_any_match = True
                if tt == qt:
                    best_for_token = max(best_for_token, self.WHOLE_WORD)
                    had_any_match = True
            if best_for_token > 0:
                score += best_for_token
                prefix_coverage += 1

        # Tokens in order (not necessarily adjacent)
        if q_tokens:
            pos = 0
            ok = True
            for qt in q_tokens:
                found = False
                for j in range(pos, len(target_tokens)):
                    if target_tokens[j].startswith(qt):
                        found = True
                        pos = j + 1
                        break
                if not found:
                    ok = False
                    break
            if ok:
                score += self.TOKENS_IN_ORDER
                had_any_match = True

        # Subsequence (cheap “gse” style)
        if q_compact and is_subsequence(q_compact, target_norm):
            # Light boost (kept small so it doesn't dominate good token matches)
            score += 20
            had_any_match = True

        # Fuzzy fallback (only if we haven't matched enough)
        # Use a conservative threshold and run on compact-ish strings.
        if not had_any_match and self.fuzzy_max_dist > 0:
            dist = damerau_levenshtein(q_norm, target_norm, max_dist=self.fuzzy_max_dist)
            if dist <= self.fuzzy_max_dist:
                used_fuzzy = True
                had_any_match = True
                score += max(0, 50 - 10 * dist)

        # Length penalty (prefer shorter labels when close)
        score -= 0.5 * (len(target_norm) - len(q_norm))

        return score, prefix_coverage, had_any_match, used_fuzzy

    def search(self, query: str, *, limit: int = 10) -> List[MatchResult]:
        q_norm = normalize(query)
        q_tokens = q_norm.split() if q_norm else []
        q_compact = q_norm.replace(" ", "")

        # Empty query: return top-ish (alphabetical, stable)
        if not q_norm:
            # In a real app: replace with "recently used"
            return [
                MatchResult(item=it, score=0.0, prefix_coverage=0)
                for it in sorted(self.items, key=lambda x: (x.label.lower(), x.id))[:limit]
            ]

        cand_idx = self._candidate_indices(q_tokens)

        results: List[MatchResult] = []
        for i in cand_idx:
            it = self.items[i]

            # Score against label
            best_score, best_cov, matched, _ = self._score_one_string(
                q_norm, q_tokens, q_compact, it.norm, it.tokens
            )

            # Score against aliases (if any) with slightly lower base weight
            for alias in it.aliases:
                alias_norm = normalize(alias)
                alias_tokens = tuple(alias_norm.split())
                s2, cov2, matched2, _ = self._score_one_string(
                    q_norm, q_tokens, q_compact, alias_norm, alias_tokens
                )
                if matched2:
                    s2 -= 10  # slight penalty vs the label
                    if s2 > best_score:
                        best_score, best_cov, matched = s2, cov2, True

            if matched:
                results.append(MatchResult(item=it, score=best_score, prefix_coverage=best_cov))

        # Deterministic ordering (tie-breakers)
        results.sort(
            key=lambda r: (
                -r.score,
                -r.prefix_coverage,
                len(r.item.norm),
                r.item.label.lower(),
                r.item.id,
            )
        )

        return results[:limit]


# ----------------------------
# Loading
# ----------------------------

def load_categories_txt(path: str) -> List[CategoryItem]:
    with open(path, "r", encoding="utf-8") as f:
        labels = [ln.strip() for ln in f.readlines() if ln.strip()]
    return [CategoryItem.from_label(lbl) for lbl in labels]


# ----------------------------
# CLI Demo
# ----------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--categories", required=True, help="Path to categories.txt (one per line)")
    ap.add_argument("--query", help="Run a single query and print results")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--interactive", action="store_true", help="Run an interactive prompt loop")
    ap.add_argument("--no-index", action="store_true", help="Disable prefix index (debug)")
    ap.add_argument("--fuzzy-max-dist", type=int, default=2)
    args = ap.parse_args()

    items = load_categories_txt(args.categories)

    engine = CategoryAutocomplete(
        items,
        enable_index=not args.no_index,
        fuzzy_max_dist=args.fuzzy_max_dist
    )

    def run_query(q: str) -> None:
        res = engine.search(q, limit=args.limit)
        print(f"\nQuery: {q!r}")
        if not res:
            print("  (no matches)")
            return
        for r in res:
            print(f"  - {r.item.label:30}  score={r.score:7.2f}  cov={r.prefix_coverage}")

    if args.query is not None:
        run_query(args.query)
        return 0

    if args.interactive:
        print("Interactive mode. Type to search. Empty line to quit.\n")
        while True:
            try:
                q = input("> ").rstrip("\n")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if q.strip() == "":
                break
            run_query(q)
        return 0

    ap.error("Provide --query or --interactive")

if __name__ == "__main__":
    raise SystemExit(main())