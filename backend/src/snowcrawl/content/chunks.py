"""The `chunks` content format: a page's markdown split into pieces of a bounded size for retrieval, each with the
headings it sits under. No model reads it: sizes are counted in words, the runs of non-whitespace characters (a
stand-in for a model's tokens, whose count depends on the model's vocabulary).

Three strategies, all keeping a code block whole in one chunk and never joining text across a heading:
- `heading`: one chunk per section (a heading and the blocks up to the next heading); a section longer than `size`
  words is split by sentences, as `sentence` does;
- `sentence`: sentences (UAX #29 sentence boundaries, approximated: a full stop, `!` or `?` followed by whitespace and
  not by a lower-case letter, or an ideographic full stop) packed into chunks of at most `size` words;
- `token`: a window of `size` words moved by `size - overlap` words over each section's text between its code blocks;
  each code block is a chunk of its own.

`overlap` is the words at the end of a chunk that the next chunk of the same section starts with: for `sentence`, as
many whole trailing sentences as fit in it. The chunk's `heading_path` is the titles of its headings, outermost first.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from snowcrawl.content.md_blocks import Block, parse, paths
from snowcrawl.normalize.strings import sentences

Strategy = Literal["heading", "sentence", "token"]
Source = Literal["markdown", "markdown_fit"]
_WORD = re.compile(r"\S+")


class ChunkOptions(BaseModel):
    """`chunks`' options: the `strategy`, the `size` of a chunk and the `overlap` between chunks, in words, and the
    markdown the chunks are cut from (`markdown_fit` is pruned, so the chunks hold the page's content only)."""

    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    strategy: Strategy = "heading"
    size: PositiveInt = 400
    overlap: int = Field(default=0, ge=0)
    source: Source = "markdown"

    @model_validator(mode="after")
    def _overlap_is_less_than_size(self) -> Self:
        if self.overlap >= self.size:
            raise ValueError("overlap must be smaller than size")
        return self


class Chunk(BaseModel):
    """One chunk of a page's markdown: its position, text, size in words and the headings above it."""

    index: int
    text: str
    words: int
    heading_path: list[str]


@dataclass(frozen=True)
class _Section:
    path: tuple[str, ...]
    blocks: list[Block]


def chunks(markdown: str, options: ChunkOptions | None = None) -> list[Chunk]:
    """The chunks of `markdown`, in order, numbered from 0."""
    options = options or ChunkOptions()
    found: list[tuple[tuple[str, ...], str]] = []
    for section in _sections(markdown):
        pieces = _pieces(section, options)
        found.extend((section.path, piece) for piece in pieces if piece.strip())
    return [
        Chunk(index=index, text=text, words=len(_WORD.findall(text)), heading_path=list(path))
        for index, (path, text) in enumerate(found)
    ]


def _sections(markdown: str) -> list[_Section]:
    """The markdown's sections: each heading with the blocks after it up to the next heading, and any blocks before
    the first heading as a section of their own, under no path."""
    blocks = parse(markdown)
    sections: list[_Section] = []
    for block, path in zip(blocks, paths(blocks), strict=True):
        if block.kind == "heading" or not sections:
            sections.append(_Section(path, [block]))
        else:
            sections[-1].blocks.append(block)
    return sections


def _pieces(section: _Section, options: ChunkOptions) -> list[str]:
    text = "\n\n".join(block.text for block in section.blocks)
    if options.strategy == "heading" and len(_WORD.findall(text)) <= options.size:
        return [text]
    if options.strategy == "token":
        return [piece for run in _runs(section.blocks) for piece in _token_pieces(run, options)]
    return list(_packed(_sentences(section.blocks), options))


def _runs(blocks: list[Block]) -> list[list[Block]]:
    """The blocks split at each code block: a code block is a run of its own, the blocks between are another."""
    runs: list[list[Block]] = []
    for block in blocks:
        if block.kind == "code" or not runs or runs[-1][-1].kind == "code":
            runs.append([block])
        else:
            runs[-1].append(block)
    return runs


def _token_pieces(run: list[Block], options: ChunkOptions) -> Iterator[str]:
    """A code block whole, as one piece whatever its size; other blocks' text in word windows."""
    if run[0].kind == "code":
        yield run[0].text
    else:
        yield from _windows("\n\n".join(block.text for block in run), options)


def _windows(text: str, options: ChunkOptions) -> Iterator[str]:
    """Windows of `size` words, each starting `size - overlap` words after the last, cut from `text` as written."""
    spans = [match.span() for match in _WORD.finditer(text)]
    step = options.size - options.overlap
    for start in range(0, len(spans), step):
        last = min(start + options.size, len(spans)) - 1
        yield text[spans[start][0] : spans[last][1]]
        if last == len(spans) - 1:
            return


def _sentences(blocks: list[Block]) -> list[str]:
    """The sentences of the blocks, in order (`normalize.strings.sentences`); a code block or a heading is one."""
    return [
        sentence
        for block in blocks
        for sentence in ([block.text] if block.kind in ("code", "heading") else sentences(block.text))
        if sentence
    ]


def _packed(sentences: list[str], options: ChunkOptions) -> Iterator[str]:
    """Sentences packed into chunks of at most `size` words (a longer sentence is a chunk of its own), each chunk
    starting with the trailing sentences of the last that fit in `overlap` words."""
    current: list[str] = []
    size = 0
    for sentence in sentences:
        words = len(_WORD.findall(sentence))
        if current and size + words > options.size:
            yield " ".join(current)
            current = _tail(current, options.overlap)
            size = sum(len(_WORD.findall(s)) for s in current)
            if size + words > options.size:  # the overlap would leave no room for the sentence
                current, size = [], 0
        current.append(sentence)
        size += words
    if current:
        yield " ".join(current)


def _tail(sentences: list[str], overlap: int) -> list[str]:
    kept: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        total += len(_WORD.findall(sentence))
        if total > overlap:
            break
        kept.append(sentence)
    return kept[::-1]
