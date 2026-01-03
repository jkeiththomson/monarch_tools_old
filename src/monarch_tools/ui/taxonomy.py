from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
from .text_utils import norm_key, titleish

DEFAULT_GROUP = "Aaa"
DEFAULT_CATEGORY = "Uncategorized"

@dataclass
class Taxonomy:
    groups: List[str]                 # display names
    group_to_cats: Dict[str, List[str]]  # group display -> list of category display

    def ensure_defaults(self) -> None:
        gk = {norm_key(g): g for g in self.groups}
        if norm_key(DEFAULT_GROUP) not in gk:
            self.groups.insert(0, DEFAULT_GROUP)
            self.group_to_cats[DEFAULT_GROUP] = [DEFAULT_CATEGORY]
        else:
            gname = gk[norm_key(DEFAULT_GROUP)]
            self.groups[self.groups.index(gname)] = DEFAULT_GROUP
            self.group_to_cats[DEFAULT_GROUP] = self.group_to_cats.pop(gname)
        # ensure default category exists and is the only category in Aaa
        self.group_to_cats[DEFAULT_GROUP] = [DEFAULT_CATEGORY]

    def normalize_display(self) -> None:
        # normalize capitalization for professional display
        new_groups: List[str] = []
        new_map: Dict[str, List[str]] = {}
        for g in self.groups:
            g2 = titleish(g)
            if norm_key(g2) == norm_key(DEFAULT_GROUP):
                g2 = DEFAULT_GROUP
            new_groups.append(g2)
        # map old->new group keys
        old_to_new = {norm_key(old): new for old, new in zip(self.groups, new_groups)}
        for old_g, cats in self.group_to_cats.items():
            ng = old_to_new.get(norm_key(old_g), titleish(old_g))
            if norm_key(ng) == norm_key(DEFAULT_GROUP):
                ng = DEFAULT_GROUP
            new_map.setdefault(ng, [])
            for c in cats:
                c2 = titleish(c)
                if norm_key(c2) == norm_key(DEFAULT_CATEGORY):
                    c2 = DEFAULT_CATEGORY
                new_map[ng].append(c2)
        self.groups = new_groups
        self.group_to_cats = new_map
        self.ensure_defaults()

    def validate_unique_categories(self) -> None:
        seen = {}
        for g, cats in self.group_to_cats.items():
            for c in cats:
                k = norm_key(c)
                if k in seen and k != norm_key(DEFAULT_CATEGORY):
                    raise ValueError(f"Category name must be unique across groups: '{c}' duplicates '{seen[k]}'")
                seen[k] = c

    def sort_alpha(self) -> None:
        # Aaa first, then alpha
        rest = [g for g in self.groups if norm_key(g) != norm_key(DEFAULT_GROUP)]
        rest.sort(key=lambda s: norm_key(s))
        self.groups = [DEFAULT_GROUP] + rest
        for g in list(self.group_to_cats.keys()):
            if norm_key(g) != norm_key(DEFAULT_GROUP):
                cats = self.group_to_cats[g]
                # remove any accidental Uncategorized duplicates
                cats = [c for c in cats if norm_key(c) != norm_key(DEFAULT_CATEGORY)]
                cats.sort(key=lambda s: norm_key(s))
                self.group_to_cats[g] = cats
        self.ensure_defaults()

    def add_category(self, category: str, group: str) -> None:
        category = titleish(category)
        group = DEFAULT_GROUP if norm_key(group) == norm_key(DEFAULT_GROUP) else titleish(group)
        if not category:
            return
        if norm_key(category) == norm_key(DEFAULT_CATEGORY):
            return
        # ensure group exists
        if group not in self.group_to_cats:
            self.add_group(group)
        # enforce uniqueness across all groups
        for g, cats in self.group_to_cats.items():
            for c in cats:
                if norm_key(c) == norm_key(category):
                    return  # already exists somewhere
        self.group_to_cats[group].append(category)
        self.sort_alpha()
        self.validate_unique_categories()

    def add_group(self, group: str) -> None:
        group = titleish(group)
        if not group:
            return
        if norm_key(group) == norm_key(DEFAULT_GROUP):
            return
        if norm_key(group) in {norm_key(g) for g in self.groups}:
            # already exists (case-insensitive); do nothing
            return
        self.groups.append(group)
        self.group_to_cats[group] = []
        self.sort_alpha()

    def remove_category_if_unused(self, category: str, used_categories: List[str]) -> None:
        k = norm_key(category)
        if k in {norm_key(DEFAULT_CATEGORY)}:
            return
        if k in {norm_key(u) for u in used_categories if u}:
            return
        # remove from its group
        for g in list(self.group_to_cats.keys()):
            self.group_to_cats[g] = [c for c in self.group_to_cats[g] if norm_key(c) != k]
        self.sort_alpha()

    def remove_group_if_unused(self, group: str, used_groups: List[str]) -> None:
        kg = norm_key(group)
        if kg == norm_key(DEFAULT_GROUP):
            return
        if kg in {norm_key(u) for u in used_groups if u}:
            return
        # remove group
        self.groups = [g for g in self.groups if norm_key(g) != kg]
        # also remove its cats
        for g in list(self.group_to_cats.keys()):
            if norm_key(g) == kg:
                self.group_to_cats.pop(g, None)
        self.sort_alpha()

    def category_to_group(self) -> dict:
        m = {}
        for g, cats in self.group_to_cats.items():
            for c in cats:
                if norm_key(c) == norm_key(DEFAULT_CATEGORY):
                    continue
                m[norm_key(c)] = g
        return m

    def compute_cat_ids(self) -> List[Tuple[int, str, str]]:
        """Return list of (cat_id, category, group) recomputed each time.
        IDs are UI-only helpers per spec; stored files use names only.
        CatID=1 reserved for Uncategorized in Aaa.
        """
        items: List[Tuple[int, str, str]] = []
        items.append((1, DEFAULT_CATEGORY, DEFAULT_GROUP))
        cid = 2
        # group order is self.groups
        for g in self.groups:
            if norm_key(g) == norm_key(DEFAULT_GROUP):
                continue
            cats = self.group_to_cats.get(g, [])
            for c in cats:
                if norm_key(c) == norm_key(DEFAULT_CATEGORY):
                    continue
                items.append((cid, c, g))
                cid += 1
        return items
