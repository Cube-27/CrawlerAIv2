"""Shell classification (SPEC-02 §4.3): a page with enough visible text or enough links is never a shell; one with
enough text is `blocked` only when it is a small document that links, loads and runs nothing."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.classify import TERMINAL_MAX_BYTES, classify

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
    document = _document(visible, paragraph, links, hidden)
    terminal = len(document) <= TERMINAL_MAX_BYTES and links == 0 and not any(tag == "script" for tag, _ in hidden)
    assert classify(200, (), document) == ("blocked" if terminal else "ok")


@given(st.text(_ALPHABET, max_size=600), st.integers(1, 80), st.integers(5, 50), _HIDDEN)
def test_enough_links_is_never_shell(visible: str, paragraph: int, links: int, hidden: list[tuple[str, str]]) -> None:
    assert classify(200, (), _document(visible, paragraph, links, hidden)) == "ok"


@given(st.text(_ALPHABET, max_size=199), st.integers(1, 80), st.integers(0, 4), _HIDDEN)
def test_little_text_and_few_links_is_shell(
    visible: str, paragraph: int, links: int, hidden: list[tuple[str, str]]
) -> None:
    assert classify(200, (), _document(visible, paragraph, links, hidden)) == "shell"


# At least one chrome link, so that the page is never a terminal document (`test_classify.py`).
_CHROME_LINKS = st.integers(1, 12).map(lambda n: "".join(f'<li><a href="/c/{i}">c</a></li>' for i in range(n)))


@given(st.integers(0, 40), _CHROME_LINKS, st.sampled_from(["li", "div", "article"]), st.booleans())
def test_a_listing_is_a_shell_exactly_when_it_shows_fewer_than_three_linked_items(
    items: int, chrome: str, tag: str, main: bool
) -> None:
    tiles = "".join(f'<{tag} class="t"><a href="/p/{i}">Item {i}</a></{tag}>' for i in range(items))
    content = f"<p>{'words ' * 50}</p><section>{tiles}</section>"
    body = f"<nav><ul>{chrome}</ul></nav>{f'<main>{content}</main>' if main else content}"
    document = f"<!doctype html><html><head><title>t</title></head><body>{body}</body></html>".encode()

    assert classify(200, (), document, page_kind="listing") == ("ok" if items >= 3 else "shell")
