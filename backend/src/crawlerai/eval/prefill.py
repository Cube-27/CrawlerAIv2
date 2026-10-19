"""The labeling pre-fill (evaluation spec, "Labels and two-pass labeling"; llm spec, "Role C input, claims and
candidates"): role C over every field of a page's schema, as a `draft` label.

The calls are role C's with prompt kind `c_prefill`, charged to no job: a detail page's one call; on a listing, the
listing call over the blocks of the item layer's first aligned group (`collect.items.align`), one row per block in the
group's order, and the detail call over the cleaned text for the page fields. A value becomes a field label only when
it is grounded in the cleaned text and its normalizer accepts it: the label holds the normalized value and its `text:`
locator. Everything else (null, ungrounded, declined) is left unlabeled for the labeler; a pre-fill never marks a field
`absent`, which is a labeler's claim about the page (G2). A block row that labels no field is no row. The draft names
`prefill_source=llm:<model>` and no labeler, and never counts as ground truth: only a checked page does. Row-mapped
fields are left out: role C is never asked for them (variants spec, "Path alternatives and row-mapped fields"), so the
labeler labels their rows.
"""

import asyncio
from collections import defaultdict
from collections.abc import Mapping

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.currencies import with_stated_currencies
from crawlerai.collect.items.align import align
from crawlerai.collect.items.bind import RowBlock
from crawlerai.collect.items.lines import BlockText, block_texts
from crawlerai.collect.schema_org_map import is_item_url
from crawlerai.content.context import page_context
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import PageKind
from crawlerai.eval.labels import FieldLabel, LabelRow, Labels
from crawlerai.llm.client import LLMClient, LLMFailure, LLMResponse
from crawlerai.llm.roles import c_extract
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, SchemaContent
from crawlerai.storage.capture_bundle import CaptureBundle


async def prefill(
    llm: LLMClient, bundle: CaptureBundle, page_kind: PageKind, fields: Mapping[str, FieldSpec]
) -> Labels:
    """The draft labels role C reads from the captured page. Raises the client's `LLMFailure` when a call gives no
    valid reply: a pre-fill without values is not a draft worth storing."""
    fields = {name: spec for name, spec in fields.items() if not spec.row_mapped}
    page, ctx = await parsed_with_context(bundle)
    kind = c_extract.PREFILL_PROMPT_KIND
    row_fields = {name: spec for name, spec in fields.items() if spec.scope == "row"}
    if page_kind == "detail" or not row_fields:
        # A detail page's fields are its one entity's; a listing schema without row fields has only the page's,
        # so role C is asked for no rows.
        cleaned = page.cleaned_text
        filled = [await c_extract.extract_detail(llm, cleaned, fields, ctx, owner=PAGE, job_id=None, kind=kind)]
        rows: tuple[str, ...] = ()
    else:
        blocks = await asyncio.to_thread(_blocks, page, ctx, fields)
        filled = await _listing(llm, page, ctx, fields, blocks)
        rows = tuple(block.row for block in blocks)
    model = _model(filled)
    by_owner = _labels_by_owner(tuple(c for one in filled for c in one.candidates))
    return Labels(
        label_version=1,
        status="draft",
        prefill_source=None if model is None else f"llm:{model}",
        fields=by_owner.get(PAGE, {}),
        rows=tuple(LabelRow(fields=by_owner[row]) for row in rows if by_owner.get(row)),
    )


def _model(filled: list[c_extract.Filled]) -> str | None:
    """The model that answered the calls, None when none was made; raises the first call's failure."""
    replies = [reply for one in filled for reply in one.replies]
    if failure := next((reply for reply in replies if isinstance(reply, LLMFailure)), None):
        raise failure
    return next((reply.model for reply in replies if isinstance(reply, LLMResponse)), None)


async def _listing(
    llm: LLMClient, page: ParsedPage, ctx: Context, fields: Mapping[str, FieldSpec], blocks: tuple[BlockText, ...]
) -> list[c_extract.Filled]:
    """A listing's calls: the blocks' (when the page shows any) and the page fields' (when the schema has any)."""
    kind = c_extract.PREFILL_PROMPT_KIND
    filled: list[c_extract.Filled] = []
    if blocks:
        listed = {name: fields[name] for block in blocks for name in block.fields}
        filled.append(await c_extract.extract_listing(llm, blocks, listed, ctx, job_id=None, kind=kind))
    if page_fields := {name: spec for name, spec in fields.items() if spec.scope == "page"}:
        cleaned = page.cleaned_text
        filled.append(
            await c_extract.extract_detail(llm, cleaned, page_fields, ctx, owner=PAGE, job_id=None, kind=kind)
        )
    return filled


def _blocks(page: ParsedPage, ctx: Context, fields: Mapping[str, FieldSpec]) -> tuple[BlockText, ...]:
    """The blocks of the page's first aligned group, each to fill every row field but the item URL (its link, which its
    text does not show)."""
    groups = align(page, SchemaContent(page_kind="listing", fields=dict(fields)), ctx)
    if not groups:
        return ()
    asked = [name for name, spec in fields.items() if spec.scope == "row" and not is_item_url(spec)]
    rows = [RowBlock(i, block, block.entity.id) for i, block in enumerate(groups[0].blocks)]
    return block_texts(page, rows, {row.row: asked for row in rows})


async def parsed_with_context(bundle: CaptureBundle) -> tuple[ParsedPage, Context]:
    """The captured page parsed, and the normalizers' context it states (locales, currencies), as the pipeline reads
    them: what a label value is normalized in."""
    page = await asyncio.to_thread(ParsedPage.of, bundle)  # parsing is CPU work
    return page, with_stated_currencies(
        page_context(
            page, bundle.manifest.final_url, bundle.manifest.fetched_at, headers=bundle.manifest.headers.response
        ),
        page,
    )


def _labels_by_owner(candidates: tuple[Candidate, ...]) -> dict[str, dict[str, FieldLabel]]:
    """Each accepted candidate as its owner's field label."""
    labels: dict[str, dict[str, FieldLabel]] = defaultdict(dict)
    for candidate in candidates:
        if isinstance(candidate.normalized, Ok):
            label = FieldLabel(value=candidate.normalized.value, absent=False, locator=candidate.locator)
            labels[candidate.entity_id][candidate.field] = label
    return labels
