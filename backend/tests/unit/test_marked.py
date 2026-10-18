"""The cleaned text role C reads on a detail page (llm spec, "Role C input, claims and candidates"): ids for the links
and images the fields asked can claim, only for links to another resource, and offsets that map back past them."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.content.page import ParsedPage
from crawlerai.content.text import CleanedText, Mark, MarkKind
from crawlerai.llm.marked import marked

BASE = "https://jobs.example.test/postings/7"
BOTH: frozenset[MarkKind] = frozenset({"link", "image"})


def _cleaned(body: str) -> CleanedText:
    return ParsedPage(f"<html><body>{body}</body></html>").cleaned_text


def test_links_read_their_id_after_their_text_and_images_with_their_description() -> None:
    cleaned = _cleaned(
        '<p>Senior baker <a href="/postings/7/apply">Apply</a></p>'
        '<a href="/home" aria-label="Home page"></a><img src="/logo.png" alt="Bakery logo"><img src="/x.png">'
    )

    read = marked(cleaned, cleaned.text, BOTH, BASE, BASE, 10_000)

    # An element that renders no text sits where the text stood when it was reached: before the next line's break.
    assert read.text == "Senior baker Apply[L1][L2: Home page][I1: Bakery logo][I2]"
    assert read.cleaned == cleaned.text
    assert {ref: mark.target for ref, mark in read.elements.items()} == {
        "L1": "/postings/7/apply",
        "L2": "/home",
        "I1": "/logo.png",
        "I2": "/x.png",
    }


@given(st.lists(st.tuples(st.text("ab ", min_size=1, max_size=5), st.booleans()), min_size=1, max_size=6))
def test_every_offset_outside_an_id_maps_back_to_the_same_character(pieces: list[tuple[str, bool]]) -> None:
    text = "".join(piece for piece, _ in pieces)
    marks: list[Mark] = []
    position = 0
    for n, (piece, linked) in enumerate(pieces):
        if linked:
            marks.append(Mark("link", position, position + len(piece), f"/a[{n + 1}]", f"/p/{n}", ""))
        position += len(piece)
    read = marked(CleanedText(text, (), tuple(marks)), text, BOTH, BASE, BASE, 10_000)

    spans = _spans(read.inserted, read.lengths)
    ids = {i: at for at, length, shift in spans for i in range(at + shift, at + shift + length)}
    shown = [i for i in range(len(read.text)) if i not in ids]
    assert [read.text[i] for i in shown] == list(text)
    assert [read.cleaned_offset(i) for i in shown] == list(range(len(text)))
    assert all(read.cleaned_offset(i) == at for i, at in ids.items())


def _spans(inserted: tuple[int, ...], lengths: tuple[int, ...]) -> list[tuple[int, int, int]]:
    """Each id's position in the cleaned text, its length, and the length of the ids before it."""
    spans, shift = [], 0
    for at, length in zip(inserted, lengths, strict=True):
        spans.append((at, length, shift))
        shift += length
    return spans
