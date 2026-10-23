"""The engine's listing rows aligned with a config's rows, for held-out validation.

The engine's rows of a listing without structured rows come from role C, which may leave items out; a config's row
selector selects every item. Both are in document order, so the engine's rows are matched to the config's as an
order-preserving subsequence: the alignment with the most field values that agree (a longest common subsequence over
rows, weighted by the fields each pair agrees on). An engine row that agrees with no config row stays unaligned, and
its values are then not reproduced; a config row no engine row aligns with is one the engine did not publish.
"""

from collections.abc import Callable, Mapping, Sequence

from pydantic import JsonValue

type Row = Mapping[str, JsonValue]
# Whether a config value agrees with the value the engine published for the field: (field, config, engine).
type Agrees = Callable[[str, JsonValue, JsonValue], bool]


def align(engine: Sequence[Row], config: Sequence[Row], agrees: Agrees) -> list[int | None]:
    """For each engine row, in order, the index of the config row it aligns with, or None. The indices increase."""
    scores = [[_score(row, other, agrees) for other in config] for row in engine]
    return _backtrack(scores, _table(scores))


def _score(engine: Row, config: Row, agrees: Agrees) -> int:
    """How many of the engine row's published fields the config row agrees on."""
    return sum(1 for name, value in engine.items() if name in config and agrees(name, config[name], value))


def _table(scores: Sequence[Sequence[int]]) -> list[list[int]]:
    """`best[i][j]`: the most agreeing values of an alignment of the first i engine rows with the first j config
    rows."""
    n, m = len(scores), len(scores[0]) if scores else 0
    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            paired = best[i - 1][j - 1] + scores[i - 1][j - 1] if scores[i - 1][j - 1] else 0
            best[i][j] = max(best[i - 1][j], best[i][j - 1], paired)
    return best


def _backtrack(scores: Sequence[Sequence[int]], best: Sequence[Sequence[int]]) -> list[int | None]:
    aligned: list[int | None] = [None] * len(scores)
    i, j = len(scores), len(best[0]) - 1
    while i > 0 and j > 0:
        score = scores[i - 1][j - 1]
        if score and best[i][j] == best[i - 1][j - 1] + score:
            aligned[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return aligned
