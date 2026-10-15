"""The markdown format's list layout (CommonMark 0.31 §5.2, §5.3): a nested list as trafilatura writes it, with layout
indentation on its continuation paragraphs, keeps each paragraph in the item whose content column it reaches, at
exactly that column. The lists are generated: items nest at most one level deeper than the one before, and each may
be followed by a paragraph of any open item."""

from dataclasses import dataclass
from unittest.mock import patch

import trafilatura
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.content.markdown import markdown
from crawlerai.content.page import ParsedPage

PAGE = ParsedPage('<!doctype html><html lang="en"><body><main><p>A page.</p></main></body></html>')
FINAL_URL = "https://shop.example.test/a/"

_markers = st.sampled_from(["-", "+", "*", "1.", "2)", "10."])
_words = st.lists(st.sampled_from(["steel", "oak", "chair", "folds", "flat"]), min_size=1, max_size=3).map(" ".join)


@dataclass(frozen=True)
class Layout:
    """A list as trafilatura writes it (`written`) and as the markdown format answers with it (`expected`)."""

    written: list[str]
    expected: list[str]


def content_column(indent: int, marker: str, gap: int) -> int:
    # CommonMark §5.2: the content starts after the marker and its spaces; after five or more, the first is the
    # separator and the rest start an indented code block, so the content column is the marker's end plus one.
    return indent + len(marker) + (gap if gap <= 4 else 1)


@st.composite
def layouts(draw: st.DrawFn) -> Layout:
    written: list[str] = []
    expected: list[str] = []
    columns: list[int] = []  # the content columns of the open items, outermost first
    for _ in range(draw(st.integers(1, 6))):
        depth = draw(st.integers(0, len(columns)))
        del columns[depth:]
        indent = columns[-1] if columns else 0
        marker, gap, text = draw(_markers), draw(st.integers(1, 6)), draw(_words)
        line = " " * indent + marker + " " * gap + text
        written.append(line)
        expected.append(line)
        columns.append(content_column(indent, marker, gap))
        if draw(st.booleans()):  # a paragraph of an open item, after a blank line
            level = draw(st.integers(0, len(columns) - 1))
            # Layout indentation past the item's column, short of the next deeper item's.
            room = columns[level + 1] - columns[level] - 1 if level + 1 < len(columns) else 8
            extra, text = draw(st.integers(0, room)), draw(_words)
            written += ["", " " * (columns[level] + extra) + text]
            expected += ["", " " * columns[level] + text]
            del columns[level + 1 :]
    return Layout(written, expected)


@given(layouts())
def test_a_continuation_paragraph_stays_in_the_item_whose_column_it_reaches(layout: Layout) -> None:
    with patch.object(trafilatura, "extract", return_value="\n".join(layout.written)):
        made = markdown(PAGE, FINAL_URL)

    assert made.split("\n") == layout.expected


@given(_words, _words, st.integers(5, 9))
def test_a_marker_followed_by_five_spaces_or_more_starts_its_content_one_past_the_marker(
    item: str, paragraph: str, gap: int
) -> None:
    written = f"-{' ' * gap}{item}\n\n{' ' * 6}{paragraph}"
    with patch.object(trafilatura, "extract", return_value=written):
        made = markdown(PAGE, FINAL_URL)

    # The paragraph reaches the item's column, 2, and its layout indentation past it is dropped.
    assert made == f"-{' ' * gap}{item}\n\n  {paragraph}"
