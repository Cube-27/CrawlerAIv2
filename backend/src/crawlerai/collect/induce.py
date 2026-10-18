"""Induction's one rule, shared by learning across sample pages (`config_ir.induction`), by the item layer across a
listing's rows (`collect.items.bind`) and by the captured-call row reader across a call's rows (`collect.xhr`): a way
of reading a value (a selector, a JSON key) is induced only when enough instances propose it, each because it
reproduces a value the engine already holds there (value-anchored wrapper induction: a reading proved by values,
never by a name); of several, the one most instances propose, then the first proposed."""

from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Sequence


def induced[K: Hashable](
    proposals: Sequence[Iterable[K]], quorum: int, verified: Callable[[K], bool] = lambda _: True
) -> K | None:
    """Of the readings at least `quorum` instances propose (each instance once) that `verified` accepts, the one most
    propose, the first proposed on a tie; None when there is none."""
    counts: Counter[K] = Counter()
    for proposed in proposals:
        counts.update(list(dict.fromkeys(proposed)))
    # `Counter` keeps first-insertion order, and `sorted` is stable: on a tie, the first proposed comes first.
    ranked = sorted((key for key, count in counts.items() if count >= quorum), key=lambda key: -counts[key])
    return next((key for key in ranked if verified(key)), None)
