"""`llms.txt` and `llms-full.txt` of a site's pages, in the format of the llmstxt.org proposal: a Markdown file that
opens with an H1 (the site's name), a blockquote (a summary of it), then H2 sections of links, each `- [name](url)`
with an optional `: description`. `llms-full.txt` holds the pages' own Markdown after the same opening.

What the files say comes from the pages and their URLs only (C7): the name is the first page's title, else its host;
the summary is that page's description; a link's name is its page's title, else the last segment of its URL's path,
else the URL; its description is its page's description. The directory every page's path shares (RFC 3986 §3.3) is
the site's root: a page goes in the section of the first segment of its path below it, named by that segment with `-`
and `_` read as spaces, and a page directly in the root goes in `Pages`. Sections follow the order their first page
came in, so the order of the pages decides the file.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

_ROOT_SECTION = "Pages"
_SEPARATORS = re.compile(r"[-_]+")
# CommonMark §6.3: brackets in link text are escaped with a backslash.
_BRACKETS = re.compile(r"([\[\]\\])")


@dataclass(frozen=True)
class LlmsPage:
    """A page of the site: its URL, and what it says about itself (None when it says nothing)."""

    url: str
    title: str | None = None
    description: str | None = None


def llms_txt(pages: Sequence[LlmsPage], site: LlmsPage | None = None) -> str:
    """The `llms.txt` of `pages`, in their order; a file of its H1 alone for none. `site` is the page that names the
    site and summarizes it, the first of `pages` without it."""
    lines = _opening(site or (pages[0] if pages else None))
    for section, members in _sections(pages).items():
        lines += ["", f"## {section}", ""]
        lines += [_entry(page) for page in members]
    return "\n".join(lines) + "\n"


def llms_full_txt(pages: Sequence[LlmsPage], markdown: Sequence[str]) -> str:
    """The `llms-full.txt` of `pages`: the opening of `llms.txt`, then each page as an H2 of its name with its URL and
    its `markdown` (one text per page, in order)."""
    lines = _opening(pages[0] if pages else None)
    for page, text in zip(pages, markdown, strict=True):
        lines += ["", f"## {_name(page)}", "", f"Source: {page.url}"]
        if text:
            lines += ["", text.strip()]
    return "\n".join(lines) + "\n"


def _opening(first: LlmsPage | None) -> list[str]:
    host = urlsplit(first.url).hostname if first else None
    lines = [f"# {_line(first.title if first and first.title else host or 'Site')}"]
    if first and first.description:
        lines += ["", f"> {_line(first.description)}"]
    return lines


def _segments(url: str) -> list[str]:
    return [segment for segment in urlsplit(url).path.split("/") if segment]


def _directory(url: str) -> list[str]:
    """The segments of the directory the URL's path is in: all for a path ending in `/`, else all but the last."""
    segments = _segments(url)
    return segments if urlsplit(url).path.endswith("/") else segments[:-1]


def _shared(paths: Sequence[Sequence[str]]) -> int:
    """How many leading segments every one of `paths` starts with."""
    shared = 0
    while paths and all(len(path) > shared and path[shared] == paths[0][shared] for path in paths):
        shared += 1
    return shared


def _sections(pages: Sequence[LlmsPage]) -> dict[str, list[LlmsPage]]:
    directories = [_directory(page.url) for page in pages]
    shared = _shared(directories)
    sections: dict[str, list[LlmsPage]] = {}
    for page in pages:
        below = _segments(page.url)[shared:]
        title = _SEPARATORS.sub(" ", unquote(below[0])).strip().capitalize() if len(below) > 1 else ""
        sections.setdefault(title or _ROOT_SECTION, []).append(page)
    return sections


def _name(page: LlmsPage) -> str:
    if page.title:
        return _line(page.title)
    segments = _segments(page.url)
    return _line(unquote(segments[-1])) if segments else page.url


def _entry(page: LlmsPage) -> str:
    entry = f"- [{_BRACKETS.sub(r'\\\1', _name(page))}]({page.url.replace(' ', '%20').replace(')', '%29')})"
    return f"{entry}: {_line(page.description)}" if page.description else entry


def _line(text: str) -> str:
    """`text` on one line, its whitespace collapsed."""
    return " ".join(text.split())
