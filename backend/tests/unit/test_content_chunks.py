"""`chunks` (`content.chunks`): a page's markdown split by heading, sentence or word window, each chunk with the
headings above it."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from crawlerai.content.chunks import ChunkOptions, chunks

DOC = (
    "Intro paragraph before any heading. It has two sentences.\n\n"
    "# Bees\n\nBees live in colonies. A colony has one queen. Workers forage.\n\n"
    "## Smoke\n\nSmoke calms the colony. Use it before opening the hive.\n\n"
    "## Honey\n\nHoney is taken in late summer.\n\n"
    "# Wax\n\nWax is made by workers."
)


def _words(text: str) -> int:
    return len(text.split())


def test_heading_strategy_makes_one_chunk_per_section_with_its_heading_path() -> None:
    made = chunks(DOC, ChunkOptions(strategy="heading", size=100))
    assert [(c.heading_path, c.text.splitlines()[0]) for c in made] == [
        ([], "Intro paragraph before any heading. It has two sentences."),
        (["Bees"], "# Bees"),
        (["Bees", "Smoke"], "## Smoke"),
        (["Bees", "Honey"], "## Honey"),
        (["Wax"], "# Wax"),
    ]
    assert [c.index for c in made] == [0, 1, 2, 3, 4]
    assert made[1].words == _words(made[1].text)


def test_a_section_over_the_size_is_split_by_sentences_under_its_own_path() -> None:
    made = chunks(DOC, ChunkOptions(strategy="heading", size=8))
    bees = [c for c in made if c.heading_path == ["Bees"]]
    assert len(bees) > 1
    assert all(c.words <= 8 for c in bees)
    assert "".join(c.text for c in bees).replace(" ", "").startswith("#BeesBeeslive")


def test_sentence_strategy_packs_whole_sentences_up_to_the_size_and_repeats_the_overlap() -> None:
    text = "One two three. Four five six. Seven eight nine. Ten eleven twelve."
    made = chunks(text, ChunkOptions(strategy="sentence", size=6, overlap=3))
    assert [c.text for c in made] == [
        "One two three. Four five six.",
        "Four five six. Seven eight nine.",
        "Seven eight nine. Ten eleven twelve.",
    ]


def test_sentence_strategy_does_not_split_after_an_abbreviation_followed_by_lower_case() -> None:
    made = chunks("Use tools, e.g. a smoker, for calm bees. Then wait.", ChunkOptions(strategy="sentence", size=8))
    assert [c.text for c in made] == ["Use tools, e.g. a smoker, for calm bees.", "Then wait."]


def test_sentence_strategy_splits_ideographic_sentences_without_spaces() -> None:
    made = chunks("蜜蜂住在蜂群里。每个蜂群有一只蜂王。", ChunkOptions(strategy="sentence", size=1))
    assert [c.text for c in made] == ["蜜蜂住在蜂群里。", "每个蜂群有一只蜂王。"]


def test_token_strategy_windows_the_words_with_overlap_and_keeps_the_text_as_written() -> None:
    made = chunks("a b c d e f g\n\nh i j", ChunkOptions(strategy="token", size=4, overlap=1))
    assert [c.text for c in made] == ["a b c d", "d e f g", "g\n\nh i j"]


def test_token_windows_do_not_cross_a_heading() -> None:
    made = chunks("# A\n\none two three\n\n# B\n\nfour five six", ChunkOptions(strategy="token", size=100))
    assert [c.heading_path for c in made] == [["A"], ["B"]]


def test_a_code_block_is_one_sentence_and_never_cut() -> None:
    doc = "Before the code.\n\n```\nfirst line\n\nsecond line. third.\n```\n\nAfter the code."
    made = chunks(doc, ChunkOptions(strategy="sentence", size=4))
    assert any("```\nfirst line\n\nsecond line. third.\n```" in c.text for c in made)


def test_a_heading_path_names_a_link_by_its_text() -> None:
    made = chunks("# [Bees](https://example.test/b)\n\nText here.", ChunkOptions())
    assert made[0].heading_path == ["Bees"]


def test_overlap_must_be_smaller_than_size() -> None:
    with pytest.raises(ValidationError, match="overlap must be smaller than size"):
        ChunkOptions(size=5, overlap=5)


def test_no_markdown_makes_no_chunks() -> None:
    assert chunks("", ChunkOptions()) == []


@given(
    st.lists(st.text(alphabet="abc de.\n", min_size=1, max_size=40), min_size=1, max_size=8),
    st.integers(min_value=2, max_value=12),
    st.sampled_from(["heading", "sentence", "token"]),
)
def test_every_word_of_the_markdown_is_in_some_chunk(blocks: list[str], size: int, strategy: str) -> None:
    markdown = "\n\n".join(blocks)
    made = chunks(markdown, ChunkOptions(strategy=strategy, size=size))  # type: ignore[arg-type]
    assert set(markdown.split()) <= {word for chunk in made for word in chunk.text.split()}


@given(
    st.integers(min_value=0, max_value=12),
    st.integers(min_value=1, max_value=30),
    st.integers(min_value=0, max_value=12),
    st.integers(min_value=2, max_value=12),
    st.sampled_from(["heading", "sentence", "token"]),
)
def test_every_strategy_keeps_a_code_block_whole_in_each_chunk_that_holds_it(
    before: int, code_words: int, after: int, size: int, strategy: str
) -> None:
    code = "```\n" + " ".join(f"c{i}" for i in range(code_words)) + "\n```"
    parts = [" ".join(["w"] * before), code, " ".join(["v"] * after)]
    markdown = "\n\n".join(part for part in parts if part)
    made = chunks(markdown, ChunkOptions(strategy=strategy, size=size, overlap=size // 2))  # type: ignore[arg-type]
    holding = [c.text for c in made if "c0" in c.text or f"c{code_words - 1}" in c.text]
    assert holding
    assert all(code in text for text in holding)
