"""Markdown as blocks (CommonMark 0.31 §3, leaf blocks), for the formats that keep or split a page's markdown by block:
`markdown_fit` (`fit`) and `chunks` (`chunks`).

A block is an ATX heading (§4.2), a fenced code block (§4.5), a list item (§5.2, with its nested lines), or the
paragraph-like lines between blank lines (§4.8, a GFM table too). Rendering joins the blocks again: consecutive list
items stay a tight list, any other blocks are separated by a blank line.
"""

import re
from dataclasses import dataclass
from typing import Literal

# CommonMark §4.5: a fenced code block opens and closes with a run of three or more backticks or tildes.
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# CommonMark §5.2: a list item starts with a bullet (`-`, `+`, `*`) or an ordered marker (digits, then `.` or `)`),
# then whitespace; its indentation is what nests it, and its content starts after that whitespace.
LIST_ITEM = re.compile(r"^([ \t]*(?:[-+*]|\d{1,9}[.)]))([ \t]+)")
# CommonMark §4.2: an ATX heading is one to six `#`, then a space or the line's end, then its content.
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
# CommonMark §6.3, §6.4: an image or link, `[text](destination)`; its text stands for it in a heading's path. The text
# and destination are bounded, so a line of unclosed `[` cannot make the scan quadratic.
_LINK = re.compile(r"!?\[((?:[^\[\]\\]|\\.){0,1000})\]\([^()]{0,2000}\)")

Kind = Literal["heading", "code", "list", "text"]


@dataclass(frozen=True)
class Block:
    """One block's markdown. `level` is a heading's (1 to 6), 0 for any other. `tight` marks a list item that follows
    another list item with no blank line between."""

    kind: Kind
    text: str
    level: int = 0
    tight: bool = False

    @property
    def title(self) -> str:
        """A heading's text without its `#`s and its links' targets."""
        match = _HEADING.match(self.text)
        return _LINK.sub(r"\1", match.group(2) or "").strip() if match else ""


class _Reader:
    """Reads lines into blocks: the lines of the block being read, its kind, the fence of a code block open, and whether
    a blank line came since the last block ended."""

    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self._lines: list[str] = []
        self._kind: Kind = "text"
        self._fence: str | None = None
        self._blank = False

    def read(self, line: str) -> None:
        opened = FENCE.match(line)
        if self._fence is not None:
            self._read_code(line, opened)
        elif opened:
            self._start("code", line)
            self._fence = opened.group(1)
        elif not line.strip():
            self._flush()
            self._blank = True
        elif heading := _HEADING.match(line):
            self._flush()
            self.blocks.append(Block("heading", line.strip(), level=len(heading.group(1))))
            self._blank = False
        elif LIST_ITEM.match(line) and not self._nested(line):
            self._start("list", line)
        elif self._lines:
            self._lines.append(line)
        else:
            self._start("text", line)

    def finish(self) -> list[Block]:
        self._flush()
        return self.blocks

    def _read_code(self, line: str, closing: re.Match[str] | None) -> None:
        self._lines.append(line)
        if closing and self._closes(closing, line):
            self._fence = None
            self._flush()
            self._blank = False

    def _closes(self, closing: re.Match[str], line: str) -> bool:
        """CommonMark §4.5: a closing fence is a run of the opening fence's character, at least as long, followed only
        by spaces or tabs."""
        run = closing.group(1)
        return (
            self._fence is not None
            and run[0] == self._fence[0]
            and len(run) >= len(self._fence)
            and not line[closing.end() :].strip(" \t")
        )

    def _start(self, kind: Kind, line: str) -> None:
        self._flush()
        self._kind, self._lines, self._blank = kind, [line], False

    def _nested(self, line: str) -> bool:
        """Whether a list-item line is a nested item of the item open: indented deeper than its marker (CommonMark
        §5.2)."""
        return self._kind == "list" and bool(self._lines) and _indent(line) > _indent(self._lines[0])

    def _flush(self) -> None:
        if not self._lines:
            return
        after_item = bool(self.blocks) and self.blocks[-1].kind == "list" and not self._blank
        self.blocks.append(Block(self._kind, "\n".join(self._lines), tight=self._kind == "list" and after_item))
        self._lines = []


def parse(markdown: str) -> list[Block]:
    """The blocks of `markdown`, in order."""
    reader = _Reader()
    for line in markdown.splitlines():
        reader.read(line)
    return reader.finish()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def render(blocks: list[Block]) -> str:
    """The blocks as markdown: a tight list item follows its predecessor on the next line, any other block after a
    blank line."""
    out: list[str] = []
    previous: Block | None = None
    for block in blocks:
        if previous is not None:
            out.append("\n" if block.tight and previous.kind == "list" else "\n\n")
        out.append(block.text)
        previous = block
    return "".join(out)


def paths(blocks: list[Block]) -> list[tuple[str, ...]]:
    """For each block, the titles of the headings it sits under, outermost first; a heading's own path includes
    itself."""
    stack: list[tuple[int, str]] = []
    found: list[tuple[str, ...]] = []
    for block in blocks:
        if block.kind == "heading":
            while stack and stack[-1][0] >= block.level:
                stack.pop()
            stack.append((block.level, block.title))
        found.append(tuple(title for _, title in stack))
    return found
