"""The labeling pre-fill (SPEC-03 §4.10, SPEC-06 §4.4): role C over every field of a page's schema, as a `draft` label.

The call is role C's detail or listing call with prompt kind `c_prefill`, charged to no job. A value becomes a field
label only when it is grounded in the cleaned text and its normalizer accepts it: the label holds the normalized value
and its `text:` locator. Everything else (null, ungrounded, declined) is left unlabeled for the labeler; a pre-fill
never marks a field `absent`, which is a labeler's claim about the page (G2). A listing row that labels no field is no
row. The draft names `prefill_source=llm:<model>` and no labeler, and never counts as ground truth: only a checked
page does (§16.2). Row-mapped fields are left out: role C is never asked for them (SPEC-13 §4.9), so the labeler labels
their rows.
"""

import asyncio
from collections import defaultdict
from collections.abc import Mapping

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.currencies import with_stated_currencies
from crawlerai.content.context import page_context
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import PageKind
from crawlerai.eval.labels import FieldLabel, LabelRow, Labels
from crawlerai.llm.client import LLMClient, LLMFailure
from crawlerai.llm.roles import c_extract
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec
from crawlerai.storage.capture_bundle import CaptureBundle


async def prefill(
    llm: LLMClient, bundle: CaptureBundle, page_kind: PageKind, fields: Mapping[str, FieldSpec]
) -> Labels:
    """The draft labels role C reads from the captured page. Raises the client's `LLMFailure` when the call gives
    no valid reply: a pre-fill without values is not a draft worth storing."""
    fields = {name: spec for name, spec in fields.items() if not spec.row_mapped}
    page, ctx = await parsed_with_context(bundle)
    text = page.cleaned_text.text
    rows: tuple[str, ...] = ()
    row_fields = {name: spec for name, spec in fields.items() if spec.scope == "row"}
    if page_kind == "detail" or not row_fields:
        # A detail page's fields are its one entity's; a listing schema without row fields has only the page's,
        # so role C is asked for no rows.
        filled = await c_extract.extract_detail(
            llm, text, fields, ctx, owner=PAGE, job_id=None, kind=c_extract.PREFILL_PROMPT_KIND
        )
    else:
        page_fields = {name: spec for name, spec in fields.items() if spec.scope == "page"}
        filled = await c_extract.extract_listing(
            llm, text, row_fields, page_fields, ctx, job_id=None, kind=c_extract.PREFILL_PROMPT_KIND
        )
        rows = tuple(row.id for row in filled.rows)
    if isinstance(filled.reply, LLMFailure):
        raise filled.reply
    by_owner = _labels_by_owner(filled.candidates)
    return Labels(
        label_version=1,
        status="draft",
        prefill_source=f"llm:{filled.reply.model}",
        fields=by_owner.get(PAGE, {}),
        rows=tuple(LabelRow(fields=by_owner[row]) for row in rows if by_owner.get(row)),
    )


async def parsed_with_context(bundle: CaptureBundle) -> tuple[ParsedPage, Context]:
    """The captured page parsed, and the normalizers' context it states (locales, currencies), as the pipeline reads
    them: what a label value is normalized in."""
    page = await asyncio.to_thread(ParsedPage.of, bundle)  # parsing is CPU work
    return page, with_stated_currencies(page_context(page, bundle.manifest.final_url, bundle.manifest.fetched_at), page)


def _labels_by_owner(candidates: tuple[Candidate, ...]) -> dict[str, dict[str, FieldLabel]]:
    """Each accepted candidate as its owner's field label."""
    labels: dict[str, dict[str, FieldLabel]] = defaultdict(dict)
    for candidate in candidates:
        if isinstance(candidate.normalized, Ok):
            label = FieldLabel(value=candidate.normalized.value, absent=False, locator=candidate.locator)
            labels[candidate.entity_id][candidate.field] = label
    return labels
