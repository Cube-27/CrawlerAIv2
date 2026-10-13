"""The pipeline's LLM hook bound to a client (SPEC-05 §4.13, SPEC-06 §4.4, D-0483): role C for `extract_page`.

`resolve` and `llm` don't import each other (C8 layering), so the hook is bound here, in the first layer above both;
the worker and the replay harness (`eval.engine`) bind it the same way.

The client commits each call's usage on a connection of its own (D-0346). A caller of `extract_page` with this hook
must not hold an uncommitted write to the job's row meanwhile: the client's usage update would wait on it.
"""

from crawlerai.db.models import JobId
from crawlerai.llm.client import LLMClient, LLMResponse
from crawlerai.llm.roles import c_extract
from crawlerai.resolve.pipeline import GapReply, GapRequest, RoleC
from crawlerai.resolve.types import LLMCallRecord


def role_c(client: LLMClient, *, job_id: JobId | None) -> RoleC:
    """Role C on `client`, charged to `job_id` (None for a replay, which no job pays for)."""

    async def fill(request: GapRequest) -> GapReply:
        filled = await c_extract.extract_detail(
            client,
            request.page.cleaned_text.text,
            request.schema,
            request.ctx,
            owner=request.target.id,
            fields=request.missing,
            job_id=job_id,
        )
        calls = () if filled.response is None else (_call(filled.response),)
        return GapReply(filled.candidates, calls, failure=filled.failure, diagnostics=filled.diagnostics)

    return fill


def _call(response: LLMResponse) -> LLMCallRecord:
    return LLMCallRecord(
        prompt_kind=c_extract.PROMPT_KIND,
        provider=response.provider,
        model=response.model,
        request_hash=response.request_hash,
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
    )
