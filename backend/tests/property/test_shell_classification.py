"""Shell classification (SPEC-02 §4.3): a page with enough visible text or enough links is never a shell."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.classify import classify

# Letters and digits only, so generated text is never markup or whitespace.
_ALPHABET = st.characters(categories=["L", "N"])
_HIDDEN = st.lists(
    st.tuples(st.sampled_from(["script", "style", "noscript", "template"]), st.text(_ALPHABET)), max_size=3
)


def _document(visible: str, paragraph: int, links: int, hidden: list[tuple[str, str]]) -> bytes:
    paragraphs = "".join(f"<p>{visible[i : i + paragraph]}</p>\n" for i in range(0, len(visible), paragraph))
    anchors = "".join(f'<a href="/{i}"></a>' for i in range(links))
    hidden_blocks = "".join(f"<{tag}>{text}</{tag}>" for tag, text in hidden)
    return f"<!doctype html><html><body>{hidden_blocks}{paragraphs}{anchors}</body></html>".encode()


@given(st.text(_ALPHABET, min_size=200, max_size=600), st.integers(1, 80), st.integers(0, 10), _HIDDEN)
def test_enough_visible_text_is_never_shell(
    visible: str, paragraph: int, links: int, hidden: list[tuple[str, str]]
) -> None:
    assert classify(200, (), _document(visible, paragraph, links, hidden)) == "ok"


@given(st.text(_ALPHABET, max_size=600), st.integers(1, 80), st.integers(5, 50), _HIDDEN)
def test_enough_links_is_never_shell(visible: str, paragraph: int, links: int, hidden: list[tuple[str, str]]) -> None:
    assert classify(200, (), _document(visible, paragraph, links, hidden)) == "ok"


@given(st.text(_ALPHABET, max_size=199), st.integers(1, 80), st.integers(0, 4), _HIDDEN)
def test_little_text_and_few_links_is_shell(
    visible: str, paragraph: int, links: int, hidden: list[tuple[str, str]]
) -> None:
    assert classify(200, (), _document(visible, paragraph, links, hidden)) == "shell"
