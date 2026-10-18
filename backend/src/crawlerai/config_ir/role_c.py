"""The pipeline's LLM hook bound to a client (SPEC-05 §4.13, SPEC-06 §4.4, D-0483): role C for `extract_page`, on a
detail page's gaps, and on a listing's blocks whose rows lack row fields and its missing page fields (llm spec, "Role C
input, claims and candidates").

`resolve` and `llm` don't import each other (C8 layering), so the hook is bound here, in the first layer above both;
the worker and the replay harness (`eval.engine`) bind it the same way.

The client commits each call's usage on a connection of its own (D-0346). A caller of `extract_page` with this hook
must not hold an uncommitted write to the job's row meanwhile: the client's usage update would wait on it.
"""

from dataclasses import dataclass

from crawlerai.collect.base import PAGE, Candidate
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
        fields = {name: request.schema.fields[name] for name in request.missing}
        filled = await c_extract.extract_detail(
            self.client,
            request.page.cleaned_text.text,
            fields,
            request.ctx,
            owner=request.target.id,
            job_id=self.job_id,
        )
        calls = _calls(c_extract.PROMPT_KIND, filled)
        return GapReply(filled.candidates, calls, failure=_reason(filled), diagnostics=filled.diagnostics)

    async def listing(self, request: ListingGapRequest) -> ListingGapReply:
        """The blocks' call (when blocks are asked), then the page fields' (when page fields are): the page fields are
        read in the whole cleaned text, as a detail page's, since a block shows one item only."""
        fields = request.schema.fields
        candidates: list[Candidate] = []
        diagnostics: list[str] = []
        calls: list[LLMCallRecord] = []
        if request.blocks:
            asked = sorted({name for block in request.blocks for name in block.fields})
            rows = await c_extract.extract_listing(
                self.client, request.blocks, {name: fields[name] for name in asked}, request.ctx, job_id=self.job_id
            )
            candidates.extend(rows.candidates)
            diagnostics.extend(rows.diagnostics)
            calls.extend(_calls(c_extract.LISTING_PROMPT_KIND, rows))
        failure = None
        if request.page_missing:
            page = await c_extract.extract_detail(
                self.client,
                request.page.cleaned_text.text,
                {name: fields[name] for name in request.page_missing},
                request.ctx,
                owner=PAGE,
                job_id=self.job_id,
                kind=c_extract.LISTING_PROMPT_KIND,
            )
            candidates.extend(page.candidates)
            diagnostics.extend(page.diagnostics)
            calls.extend(_calls(c_extract.LISTING_PROMPT_KIND, page))
            failure = _reason(page)
        return ListingGapReply(tuple(candidates), tuple(calls), failure=failure, diagnostics=tuple(diagnostics))


def _reason(filled: c_extract.Filled) -> str | None:
    return filled.reply.field_reason if isinstance(filled.reply, LLMFailure) else None


def _calls(kind: PromptKind, filled: c_extract.Filled) -> tuple[LLMCallRecord, ...]:
    """Every answered call, a failed one's too, of every call the hook made: each was charged to the job (F30)."""
    replies = filled.replies if isinstance(filled, c_extract.FilledListing) else (filled.reply,)
    return tuple(LLMCallRecord(prompt_kind=kind, **call.model_dump()) for reply in replies for call in reply.answered)
