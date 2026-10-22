"""The shared text forms (`normalize.strings`): collapse, cut and word folding."""

import pytest

from crawlerai.normalize.strings import collapse, compose, fold_words, is_cut_of, sentences, uncut


@pytest.mark.parametrize(
    ("short", "long", "word_boundary", "expected"),
    [
        ("The cat", "The cat sat", True, True),
        ("The cat", "The category", True, False),
        ("The cat", "The category", False, True),
        ("The cat…", "The category", True, True),
        ("The cat ...", "The  category", True, True),
        ("The\ncat sat", "The cat sat on the mat", True, True),
        ("The cat sat", "The cat sat", True, True),
        ("…", "The cat", False, False),
        ("The dog", "The cat sat", False, False),
    ],
)
def test_is_cut_of(short: str, long: str, word_boundary: bool, expected: bool) -> None:
    assert is_cut_of(short, long, word_boundary=word_boundary) is expected


@pytest.mark.parametrize(
    ("text", "kwargs", "expected"),
    [
        ("Review count: 12", {}, ["review", "count", "12"]),
        ("Review count: 12", {"digits": False}, ["review", "count"]),
        ("Caf\u00e9 \uff21\uff22", {}, ["café", "ab"]),
        ("Caf\u00e9 \uff21\uff22", {"marks": False}, ["cafe", "ab"]),
        ("snake_case-word", {}, ["snake", "case", "word"]),
    ],
)
def test_fold_words(text: str, kwargs: dict[str, bool], expected: list[str]) -> None:
    assert fold_words(text, **kwargs) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [(" a \t b\n", "a b"), ("a\x00b\u0085c", "ab c"), ("Cafe\u0301", "Caf\u00e9"), ("Cafe\x00\u0301", "Caf\u00e9")],
)
def test_collapse_of_compose(text: str, expected: str) -> None:
    assert collapse(compose(text)) == expected


def test_uncut_drops_one_ending_ellipsis() -> None:
    assert [uncut(s) for s in ("a…", "a...", "a....", "a")] == ["a", "a", "a.", "a"]


def test_a_sentence_ends_after_the_quotation_mark_or_bracket_closing_it() -> None:
    # UAX #29 SB9: a terminator's closing punctuation (Sentence_Break=Close) stays in its sentence.
    assert sentences("It said “boils fast.” It pours (well.) Again") == [
        "It said “boils fast.”",
        "It pours (well.)",
        "Again",
    ]
