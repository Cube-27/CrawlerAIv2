"""The content formats of a page a task reached (rest-api spec), each a function of its capture alone (§15), and the
summary of the fetch that reached it.
"""

from collections.abc import Collection, Iterable
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from crawlerai.acquire.types import AttemptRecord
from crawlerai.collect.run import Adapters
from crawlerai.content.chunks import Chunk, ChunkOptions, chunks
from crawlerai.content.fit import FitOptions, markdown_fit
from crawlerai.content.html import cleaned_html
from crawlerai.content.links import links
from crawlerai.content.markdown import markdown
from crawlerai.content.metadata import PageMetadata, metadata
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.services.scrape_request import Input, PageFormat
from crawlerai.storage.artifacts import PDF, SCREENSHOT, Artifact, artifact_of
from crawlerai.storage.capture_bundle import CaptureManifest


class FetchSummary(BaseModel):
    """The fetch of the page: the method, status and class of the kept attempt, the platform adapter that read an `api`
    capture (INV-39; null for any other), and every attempt made."""

    method: CaptureMethod
    status_code: int | None  # None when no response arrived
    block_class: BlockClass
    adapter: str | None
    attempts: tuple[AttemptRecord, ...]


def fetch_summary(
    method: CaptureMethod,
    status_code: int | None,
    block_class: BlockClass,
    attempts: Iterable[AttemptRecord],
    *,
    adapters: Adapters | None,
    url: str,
    final_url: str,
) -> FetchSummary:
    """The summary of the fetch of `url`, whose kept attempt ended at `final_url`. An `api` capture names the active
    adapter that reads it, as the collectors do (`Registry.reader`); an API recipe's has none, and none is named
    without `adapters`."""
    found = adapters.reader(url, final_url) if method == "api" and adapters is not None else None
    return FetchSummary(
        method=method,
        status_code=status_code,
        block_class=block_class,
        adapter=None if found is None else found[0].name,
        attempts=tuple(attempts),
    )


def _absent(value: object) -> bool:
    return value is None


def _never_null(schema: dict[str, Any]) -> None:
    # A format's member is left out rather than null, so the document gives it no null branch and no default.
    (branch,) = (branch for branch in schema.pop("anyOf") if branch.get("type") != "null")
    schema.update(branch)
    del schema["default"]


def format_member(alias: str | None = None) -> Any:
    """A member of an answer that is there only when it was asked for: a format, or the draft of a prompt."""
    return Field(default=None, alias=alias, exclude_if=_absent, json_schema_extra=_never_null)


class Formats(TypedDict, total=False):
    markdown: str
    markdown_fit: str
    chunks: list[Chunk]
    html: str
    raw_html: str
    links: list[str]
    metadata: PageMetadata
    screenshot: Artifact
    pdf: Artifact


class FormatOptions(Input):
    """The options of the formats that take any: `fit` (`markdown_fit`) and `chunking` (`chunks`)."""

    fit: FitOptions | None = None
    chunking: ChunkOptions | None = None


def _markdown_formats(
    page: ParsedPage, manifest: CaptureManifest, requested: list[PageFormat], options: FormatOptions
) -> Formats:
    """`markdown`, `markdown_fit` and `chunks`, which read the same markdown: each is made once."""
    formats: Formats = {}
    final_url = manifest.final_url
    pieces = options.chunking or ChunkOptions()
    chunked = "chunks" in requested
    plain = fitted = ""
    if "markdown" in requested or (chunked and pieces.source == "markdown"):
        plain = markdown(page, final_url)
    if "markdown_fit" in requested or (chunked and pieces.source == "markdown_fit"):
        fitted = markdown_fit(page, final_url, options.fit)
    if "markdown" in requested:
        formats["markdown"] = plain
    if "markdown_fit" in requested:
        formats["markdown_fit"] = fitted
    if chunked:
        formats["chunks"] = chunks(plain if pieces.source == "markdown" else fitted, pieces)
    return formats


def page_formats(
    page: ParsedPage,
    manifest: CaptureManifest,
    requested: list[PageFormat],
    options: FormatOptions | None = None,
    artifacts: Collection[str] = (),
) -> Formats:
    """The requested content formats of a reached page, from its one parse (INV-26) and its
    capture's manifest: a format is a function of the capture alone (§15), the page kind it was fetched as included.
    `artifacts` names the files stored for the capture; a screenshot or PDF is a member only when it was made."""
    formats = _markdown_formats(page, manifest, requested, options or FormatOptions())
    if "screenshot" in requested and SCREENSHOT in artifacts:
        formats["screenshot"] = artifact_of(manifest.capture_id, SCREENSHOT)
    if "pdf" in requested and PDF in artifacts:
        formats["pdf"] = artifact_of(manifest.capture_id, PDF)
    final_url = manifest.final_url
    if "html" in requested:
        formats["html"] = cleaned_html(page)
    if "raw_html" in requested:
        formats["raw_html"] = page.html
    if "links" in requested:
        formats["links"] = list(links(page, final_url))
    if "metadata" in requested:
        formats["metadata"] = metadata(page, final_url)
    return formats
