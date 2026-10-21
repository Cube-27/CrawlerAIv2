"""The pipeline's LLM hook bound to a client (extraction spec, llm spec, D-0483): role C for `extract_page`, on a
detail page's gaps, and on a listing's blocks whose rows lack row fields and its missing page fields (llm spec, "Role C
input, claims and candidates").

`resolve` and `llm` don't import each other (C8 layering), so the hook is bound here, in the first layer above both;
the worker binds it so.

The client commits each call's usage on a connection of its own (D-0346). A caller of `extract_page` with this hook
must not hold an uncommitted write to the job's row meanwhile: the client's usage update would wait on it.
"""

import asyncio
from dataclasses import dataclass

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.dom import other_item_paths
from crawlerai.collect.labels import field_labels
from crawlerai.db.models import JobId
from crawlerai.llm.client import LLMClient, LLMFailure, PromptKind
from crawlerai.llm.roles import c_extract
from crawlerai.resolve.pipeline import GapReply, GapRequest, ListingGapReply, ListingGapRequest, RoleC
from crawlerai.resolve.types import LLMCallRecord


def role_c(client: LLMClient, *, job_id: JobId | None) -> RoleC:
    """Role C on `client`, charged to `job_id` (None for a replay, which no job pays for)."""
    return _RoleC(client, job_id)


@dataclass(frozen=True, slots=True)
class _RoleC:
    client: LLMClient
    job_id: JobId | None

    async def detail(self, request: GapRequest) -> GapReply:
        """One call for every missing field, reading the product's own text: other items' content
        (`collect.dom.other_item_paths`) is left out."""
        fields = {name: request.schema.fields[name] for name in request.missing}
        elsewhere = await asyncio.to_thread(other_item_paths, request.page, request.ctx, request.outside)
        filled = await c_extract.extract_detail(
            self.client,
            request.page.cleaned_text,
            fields,
            request.ctx,
            owner=request.target.id,
            job_id=self.job_id,
            labels=field_labels(request.schema),
            elsewhere=elsewhere,
        )
        calls = _calls(c_extract.PROMPT_KIND, filled)
        return GapReply(
            filled.candidates,
            calls,
            failure=_reason(filled),
            diagnostics=filled.diagnostics,
            unverified=filled.unverified,
        )

    async def listing(self, request: ListingGapRequest) -> ListingGapReply:
        """The blocks' calls (when blocks are asked), then the page fields' (when page fields are): the page fields are
        read in the whole cleaned text, as a detail page's, since a block shows one item only. A failed call ends the
        page's calls, and its reason is the asked page fields'."""
        fields = request.schema.fields
        labels = field_labels(request.schema)
        candidates: list[Candidate] = []
        diagnostics: list[str] = []
        calls: list[LLMCallRecord] = []
        failure = None
        unverified: tuple[str, ...] = ()
        if request.blocks:
            asked = sorted({name for block in request.blocks for name in block.fields})
            rows = await c_extract.extract_listing(
                self.client,
                request.blocks,
                {name: fields[name] for name in asked},
                request.ctx,
                job_id=self.job_id,
                labels=labels,
            )
            candidates.extend(rows.candidates)
            diagnostics.extend(rows.diagnostics)
            calls.extend(_calls(c_extract.LISTING_PROMPT_KIND, rows))
            failure = _reason(rows)
        if request.page_missing and failure is None:
            page = await c_extract.extract_detail(
                self.client,
                request.page.cleaned_text,
                {name: fields[name] for name in request.page_missing},
                request.ctx,
                owner=PAGE,
                job_id=self.job_id,
                labels=labels,
                kind=c_extract.LISTING_PROMPT_KIND,
            )
            candidates.extend(page.candidates)
            diagnostics.extend(page.diagnostics)
            calls.extend(_calls(c_extract.LISTING_PROMPT_KIND, page))
            failure = _reason(page)
            unverified = page.unverified
        return ListingGapReply(
            tuple(candidates), tuple(calls), failure=failure, diagnostics=tuple(diagnostics), unverified=unverified
        )


def _reason(filled: c_extract.Filled) -> str | None:
    """The reason of the first of the calls that gave no valid reply, if one did."""
    return next((reply.field_reason for reply in filled.replies if isinstance(reply, LLMFailure)), None)


def _calls(kind: PromptKind, filled: c_extract.Filled) -> tuple[LLMCallRecord, ...]:
    """Every answered call, a failed one's too, of every call the hook made: each was charged to the job (F30)."""
    return tuple(
        LLMCallRecord(prompt_kind=kind, **call.model_dump()) for reply in filled.replies for call in reply.answered
    )
