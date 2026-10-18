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


def test_only_the_kinds_asked_are_marked() -> None:
    cleaned = _cleaned('<a href="/a">A</a><img src="/i.png" alt="I">')

    assert marked(cleaned, cleaned.text, frozenset({"image"}), BASE, BASE, 10_000).text == "A[I1: I]"
    assert marked(cleaned, cleaned.text, frozenset(), BASE, BASE, 10_000).text == "A"


def test_a_same_document_or_non_http_target_is_not_marked() -> None:
    # RFC 3986 §4.4: a reference to the page itself, with or without a fragment, names no other resource; and a
    # target that is not an http(s) URL gives no url value.
    cleaned = _cleaned(
        '<a href="#apply">Apply</a> <a href="">Top</a> <a href="https://jobs.example.test/postings/7#form">Form</a> '
        '<a href="javascript:void(0)">Open</a> <img src="data:image/png;base64,AAAA" alt="Pixel"> '
        '<a href="?page=2">Next</a>'
    )

    read = marked(cleaned, cleaned.text, BOTH, BASE, BASE, 10_000)

    assert read.text == "Apply Top Form Open Next[L1]"
    assert read.elements["L1"].target == "?page=2"


def test_the_page_is_its_own_url_when_a_base_href_moves_where_targets_resolve() -> None:
    cleaned = _cleaned(f'<a href="{BASE}">Self</a> <a href="./">Base</a> <a href="#f">F</a>')

    read = marked(cleaned, cleaned.text, BOTH, "https://cdn.example.test/", BASE, 10_000)

    assert read.text == "Self Base[L1] F[L2]"
    assert {ref: mark.target for ref, mark in read.elements.items()} == {"L1": "./", "L2": "#f"}


def test_ids_past_the_budget_are_not_shown() -> None:
    cleaned = _cleaned('<a href="/a">A</a> <a href="/b">B</a> <img src="/i.png" alt="Logo">')

    read = marked(cleaned, cleaned.text, BOTH, BASE, BASE, len("[L1][L2]"))

    assert read.text == "A[L1] B[L2]"
    assert set(read.elements) == {"L1", "L2"}


def test_marks_past_the_cut_are_not_shown() -> None:
    cleaned = _cleaned('<a href="/a">First</a> <a href="/b">Second</a>')

    assert marked(cleaned, cleaned.text[:8], BOTH, BASE, BASE, 10_000).text == "First[L1] Se"


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
