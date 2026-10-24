"""Repeated templates: element paths that are sibling items of one template, and how many make a repetition.

Two element XPaths whose steps differ only in the position of one step (XPath 1.0 §2.4 `[n]` predicates) address
elements at the same place in sibling blocks, rendered by one template as one list's items (a review's `Reviews: 1`,
a list's microdata items). `MIN_ITEMS` (`acquire.items`) of them make a list, as they make a group of item blocks.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Final

from snowcrawl.acquire.items import MIN_ITEMS

# Sibling containers repeat from two on.
MIN_REPEATS: Final = 2
# XPath 1.0 §2.4: a step's position predicate (`[n]`).
_POSITION: Final = re.compile(r"\[\d+\]")


def template_siblings(paths: Iterable[str], minimum: int = MIN_ITEMS) -> frozenset[str]:
    """The `paths` that are one of `minimum` or more element XPaths differing only in the position of one step."""
    slots: defaultdict[tuple[int, tuple[str, ...]], set[str]] = defaultdict(set)
    for path in set(paths):
        steps = tuple(path.split("/"))
        for depth, step in enumerate(steps):
            slots[depth, (*steps[:depth], _POSITION.sub("", step), *steps[depth + 1 :])].add(path)
    return frozenset(path for found in slots.values() if len(found) >= minimum for path in found)
