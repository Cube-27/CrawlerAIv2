"""The engine's listing rows aligned with a config's rows: an order-preserving
subsequence, the one with the most agreeing values."""

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.config_ir.row_alignment import align


def _equal(_name: str, config: JsonValue, engine: JsonValue) -> bool:
    return config == engine


def _rows(*titles: str) -> list[dict[str, JsonValue]]:
    return [{"title": title} for title in titles]


def test_engine_rows_missing_items_align_with_the_config_rows_they_are() -> None:
    assert align(_rows("B", "D"), _rows("A", "B", "C", "D"), _equal) == [1, 3]


@given(
    st.lists(st.integers(), unique=True, max_size=30).flatmap(
        lambda values: st.tuples(st.just(values), st.lists(st.booleans(), min_size=len(values), max_size=len(values)))
    )
)
def test_a_subsequence_of_distinct_rows_aligns_with_where_each_row_is(case: tuple[list[int], list[bool]]) -> None:
    values, kept = case
    config = [{"n": value} for value in values]
    picked = [index for index, keep in enumerate(kept) if keep]
    engine = [config[index] for index in picked]
    assert align(engine, config, _equal) == picked
