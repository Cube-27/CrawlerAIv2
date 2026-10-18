"""Induction's one rule (`collect.induce`): a reading enough instances propose and that holds, the most proposed first,
then the first proposed."""

from crawlerai.collect.induce import induced


def test_a_reading_needs_its_quorum_of_instances_each_counted_once() -> None:
    assert induced([["a", "a"], ["a"], ["b"]], 3) is None
    assert induced([["a", "a"], ["a"], ["a", "b"]], 3) == "a"


def test_the_most_proposed_reading_wins_then_the_first_proposed() -> None:
    assert induced([["b", "a"], ["a"], ["a", "b"], ["c"]], 2) == "a"
    assert induced([["b", "a"], ["a", "b"]], 2) == "b"


def test_a_reading_that_does_not_hold_is_passed_over() -> None:
    assert induced([["b", "a"], ["a", "b"]], 2, lambda key: key != "b") == "a"
    assert induced([["b"], ["b"]], 2, lambda key: key != "b") is None
