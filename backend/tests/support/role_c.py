"""Role C as a stand-in (`resolve.pipeline.RoleC`): no model is called. It records every request it gets."""

import re

from pydantic import JsonValue

from snowcrawl.collect.base import Candidate
from snowcrawl.normalize.base import Ok
from snowcrawl.resolve.pipeline import GapReply, GapRequest, ListingGapReply, ListingGapRequest
from snowcrawl.resolve.types import LLMCallRecord

__all__ = ["CALL", "LISTING_CALL", "PRICE", "FakeRoleC"]

# The call each answer records.
CALL = LLMCallRecord(
    prompt_kind="c_extract_detail",
    provider="provider-a",
    model="model-a",
    request_hash="0" * 64,
    tokens_in=9,
    tokens_out=3,
)
LISTING_CALL = CALL.model_copy(update={"prompt_kind": "c_extract_listing"})
PRICE: JsonValue = {"amount": "19.90", "currency": "EUR"}
# An amount and its ISO 4217 code, as a page's text writes a price.
_AMOUNT = re.compile(r"\d+\.\d{2} EUR")


class FakeRoleC:
    """On a detail page, answers each missing field with `PRICE` as a grounded `llm` candidate of the target; with
    `from_text`, answers the price field only, with the first amount the page text shows, at its offsets. Or answers
    with `failure`. On a listing, gives `listing_reply`, or with `fill_blocks` fills each asked field of each block with
    the block's first line, grounded there. `error` is raised instead of any answer."""

    def __init__(
        self,
        *,
        failure: str | None = None,
        listing_reply: ListingGapReply | None = None,
        fill_blocks: bool = False,
        from_text: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.requests: list[GapRequest] = []
        self.listing_requests: list[ListingGapRequest] = []
        self._failure = failure
        self._listing_reply = listing_reply or ListingGapReply(candidates=(), llm_calls=())
        self._fill_blocks = fill_blocks
        self._from_text = from_text
        self._error = error

    async def listing(self, request: ListingGapRequest) -> ListingGapReply:
        self.listing_requests.append(request)
        if self._error is not None:
            raise self._error
        if self._fill_blocks:
            filled = tuple(
                _llm(name, block.row, block.text.split("\n")[0], block.start, block.text.split("\n")[0])
                for block in request.blocks
                for name in block.fields
            )
            return ListingGapReply(candidates=filled, llm_calls=(LISTING_CALL,))
        return self._listing_reply

    async def detail(self, request: GapRequest) -> GapReply:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._failure is not None:
            return GapReply((), (), failure=self._failure, diagnostics=(f"role C: {self._failure}",))
        if self._from_text:
            return self._read(request)
        candidates = tuple(_llm(name, request.target.id, "19.90 EUR", 0, PRICE) for name in request.missing)
        return GapReply(candidates=candidates, llm_calls=(CALL,))

    def _read(self, request: GapRequest) -> GapReply:
        found = _AMOUNT.search(request.page.cleaned_text.text)
        if found is None or "price" not in request.missing:
            return GapReply((), (CALL,))
        raw = found.group()
        value: JsonValue = {"amount": raw.removesuffix(" EUR"), "currency": "EUR"}
        return GapReply((_llm("price", request.target.id, raw, found.start(), value),), (CALL,))


def _llm(field: str, owner: str, raw: str, start: int, value: JsonValue) -> Candidate:
    return Candidate(
        field=field,
        entity_id=owner,
        source_kind="llm",
        raw=raw,
        normalized=Ok(value),
        locator=f"text:{start}-{start + len(raw)}",
        independent=True,
    )
