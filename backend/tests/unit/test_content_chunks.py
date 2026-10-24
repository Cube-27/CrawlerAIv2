"""`chunks` (`content.chunks`): a page's markdown split by heading, sentence or word window, each chunk with the
headings above it."""

from hypothesis import given
from hypothesis import strategies as st

from snowcrawl.content.chunks import ChunkOptions, chunks

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
