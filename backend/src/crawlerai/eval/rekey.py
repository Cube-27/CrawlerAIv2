"""`crawlerai eval re-key` (evaluation spec, "Label re-keying"): a golden page's draft labels recomputed from the label
file against its stored capture, with each label row the capture does not show marked `stale`.

A dynamic list changes between the moment it is labeled and the moment it is captured: rows come and go, the order
moves. A label row of which the capture shows neither text nor URL path is a row of the list as labeled, not as
captured; scoring it as a miss would charge the engine for a row it could not see. Re-keying marks such rows, and the
report counts them apart (`Report.label_stale`). Only drafts are re-keyed: a labeled or checked page took the two
passes and is left as it is. Nothing printed names a URL, host or value.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from crawlerai.eval.label_file import Declined, LabeledPage, draft_labels
from crawlerai.eval.labels import LabelRow, Labels
from crawlerai.eval.prefill import parsed_with_context
from crawlerai.eval.presence import Capture
from crawlerai.eval.store import DevEvalStore
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import decode_body


@dataclass(frozen=True)
class Rekeyed:
    n: int  # the page's position in the label file
    rows: int
    stale: int
    labeled: int
    declined: tuple[Declined, ...]


@dataclass(frozen=True)
class NotRekeyed:
    n: int
    reason: str  # `not_in_split`, or `not_draft`


def stale_rows(labels: Labels, schema: SchemaDef, capture: Capture) -> Labels:
    """`labels` with each row marked `stale` when the capture shows none of its labeled values and does not show at
    least one of them; a row whose values' presence is unknown stays as it is."""
    return labels.model_copy(update={"rows": tuple(_marked(row, schema, capture) for row in labels.rows)})


def _marked(row: LabelRow, schema: SchemaDef, capture: Capture) -> LabelRow:
    shown = {capture.shows(label.value, schema.fields[name]) for name, label in row.fields.items() if not label.absent}
    return row.model_copy(update={"stale": True not in shown and False in shown})


async def rekey_pages(
    store: DevEvalStore, schemas: Mapping[str, SchemaDef], pages: Sequence[LabeledPage]
) -> list[Rekeyed | NotRekeyed]:
    """Re-key each file page already in the golden set (by the URL its capture requested), in file order."""
    stored = await store.pages_by_url()
    outcomes: list[Rekeyed | NotRekeyed] = []
    for page in pages:
        row = stored.get(page.request.url)
        if row is None:
            outcomes.append(NotRekeyed(page.request.n, "not_in_split"))
            continue
        if row.labels.get("status") != "draft":
            outcomes.append(NotRekeyed(page.request.n, "not_draft"))
            continue
        schema = schemas[page.request.schema_name]
        bundle = await store.get_bundle(row.capture_id)
        _, ctx = await parsed_with_context(bundle)
        labels, declined = draft_labels(page, schema, ctx)
        labels = stale_rows(labels, schema, Capture(decode_body(bundle)))
        await store.put_labels(row.id, labels.model_dump(mode="json"), None, "labeler", expected=row.labels)
        stale = sum(r.stale for r in labels.rows)
        labeled = len(labels.fields) + sum(len(r.fields) for r in labels.rows)
        outcomes.append(Rekeyed(page.request.n, len(labels.rows), stale, labeled, declined))
    return outcomes


def report(outcomes: Sequence[Rekeyed | NotRekeyed]) -> str:
    """One JSON line per file page, in file order: its rows, stale rows, labels stored and declined, or why not."""
    lines = []
    for outcome in sorted(outcomes, key=lambda o: o.n):
        match outcome:
            case Rekeyed():
                line: dict[str, object] = {
                    "n": outcome.n,
                    "rows": outcome.rows,
                    "stale": outcome.stale,
                    "labeled": outcome.labeled,
                    "declined": [{"path": d.path, "reason": d.reason} for d in outcome.declined],
                }
            case NotRekeyed():
                line = {"n": outcome.n, "skipped": outcome.reason}
        lines.append(json.dumps(line) + "\n")
    return "".join(lines)
