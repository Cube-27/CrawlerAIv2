"""The engine's listing rows aligned with a config's rows (SPEC-08 §4.7, D-1500): an order-preserving subsequence, the
one with the most agreeing values."""

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.config_ir.row_alignment import align


def _equal(_name: str, config: JsonValue, engine: JsonValue) -> bool:
    return config == engine


def _rows(*titles: str) -> list[dict[str, JsonValue]]:
    return [{"title": title} for title in titles]


def test_rows_in_the_same_order_align_one_to_one() -> None:
    assert align(_rows("A", "B", "C"), _rows("A", "B", "C"), _equal) == [0, 1, 2]


def test_engine_rows_missing_items_align_with_the_config_rows_they_are() -> None:
    assert align(_rows("B", "D"), _rows("A", "B", "C", "D"), _equal) == [1, 3]


def test_out_of_order_rows_leave_one_unaligned() -> None:
    aligned = align(_rows("B", "A", "C"), _rows("A", "B", "C"), _equal)
    assert aligned.count(None) == 1
    assert aligned[2] == 2


def test_a_row_agreeing_with_no_config_row_is_unaligned() -> None:
    assert align(_rows("A", "X", "C"), _rows("A", "B", "C"), _equal) == [0, None, 2]


def test_the_alignment_with_more_agreeing_fields_wins() -> None:
    # Both config rows share the title; the price says which one the engine row is.
    engine: list[dict[str, JsonValue]] = [{"title": "Mug", "price": 2}]
    config: list[dict[str, JsonValue]] = [{"title": "Mug", "price": 1}, {"title": "Mug", "price": 2}]
    assert align(engine, config, _equal) == [1]


def test_no_rows() -> None:
    assert align([], _rows("A"), _equal) == []
    assert align(_rows("A"), [], _equal) == [None]


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


@given(st.lists(st.integers(0, 3), max_size=12), st.lists(st.integers(0, 3), max_size=12))
def test_aligned_indices_increase_and_each_pair_agrees(engine_values: list[int], config_values: list[int]) -> None:
    engine = [{"n": value} for value in engine_values]
    config = [{"n": value} for value in config_values]
    aligned = align(engine, config, _equal)
    pairs = [(i, j) for i, j in enumerate(aligned) if j is not None]
    assert [j for _, j in pairs] == sorted({j for _, j in pairs})
    assert all(engine[i] == config[j] for i, j in pairs)
