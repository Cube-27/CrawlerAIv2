"""`crawlerai eval import-labels` (D-1460): the pages of a label file captured into the dev split, each with its labels
stored as a `draft`.

A label file is JSON, `{"pages": [<page>, ...]}`; other top-level keys are ignored. A page has:
- `url`: the page, http or https, listed once in the file;
- `schema`: the name of an active schema; `page_kind`, when given, must be the schema's;
- `category`: an eval category (`db.models.EvalCategory`);
- `fields`: `{name: value}`, a detail page's fields or a listing's page fields;
- `rows`: `[{name: value}, ...]`, a listing's rows in page order;
- `notes`: free text, kept on the labels.
Other keys of a page are ignored. A value is what the field type's normalizer reads (schemas spec): a string, or the
structured forms it accepts (money `{amount, currency}`, an enum member's schema.org IRI, a schema.org `Place`), or a
location in its normalized form (`{text, ...}`), read by its `text` as the page writes it. It is stored as the
normalizer's value, normalized in the captured page's context, as the pipeline normalizes what it collects; `null`
leaves the field unlabeled. A value the normalizer declines, a list of which it drops an item, and a row-mapped field
(whose rows a labeler labels, variants spec) are left unlabeled and reported by path and reason.

A field the file does not give is unlabeled, never `absent`: a draft claims nothing about it, and metrics don't score
it. Drafts name no labeler and never count as ground truth (§16.2): only a dev report that asks for drafts scores
them (D-1461). Nothing printed or raised names a URL, host or value: pages are reported by their position in the file.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from crawlerai.acquire.types import BlockClass, FetchResult
from crawlerai.core.retry import backoff_delay
from crawlerai.core.validation import field_error
from crawlerai.db.models import EvalCategory, PageKind
from crawlerai.eval.cli import Captured, EvalCliError, PageRequest, SchemaRef, Skipped, http_host, store_page
from crawlerai.eval.labels import FieldLabel, LabelRow, Labels, parse_labels
from crawlerai.eval.prefill import parsed_with_context
from crawlerai.eval.store import EvalStore
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# Fetch a page as a page of the schema: its `FetchResult`, or why it was not fetched (robots.txt, the target guard).
PageFetch = Callable[[str, SchemaDef], Awaitable[FetchResult | str]]
# A page not reached at import is fetched again, up to this many fetches in all (master plan 2026-10-18 §3.1): a page
# that answered at screening may refuse one fetch and answer the next.
IMPORT_TRIES: Final = 3
# Which capture of a page's fetches is kept: the first reached, else the one that came closest to it.
_CLOSEST: Final[dict[BlockClass, int]] = {"ok": 0, "shell": 1, "blocked": 2, "not_found": 3, "error": 4}


async def best_fetch(
    fetch: Callable[[], Awaitable[FetchResult | str]],
    *,
    tries: int = IMPORT_TRIES,
    wait: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> FetchResult | str:
    """The page fetched with `fetch` until it is reached, at most `tries` times, waiting the back-off of each try
    (`core.retry.backoff_delay`) before the next; the capture closest to reached is kept (`_CLOSEST`, the earliest of
    equals). Why it was not fetched, when its first fetch sent nothing (robots.txt, the target guard)."""
    best: FetchResult | None = None
    for attempt in range(1, tries + 1):
        if attempt > 1:
            await wait(backoff_delay(attempt - 1).total_seconds())
        page = await fetch()
        if isinstance(page, str):
            return page if best is None else best
        if best is None or _CLOSEST[page.block_class] < _CLOSEST[best.block_class]:
            best = page
        if best.block_class == "ok":
            break
    return page if best is None else best


class _Page(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    url: str
    schema_name: str = Field(alias="schema", min_length=1)
    category: EvalCategory
    page_kind: PageKind | None = None
    fields: dict[str, JsonValue] = {}
    rows: tuple[dict[str, JsonValue], ...] = ()
    notes: str = ""


class _File(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    pages: tuple[_Page, ...]


@dataclass(frozen=True)
class LabeledPage:
    request: PageRequest
    fields: Mapping[str, JsonValue]
    rows: tuple[Mapping[str, JsonValue], ...]
    notes: str


@dataclass(frozen=True)
class Declined:
    """A label value left unlabeled: its path in the labels and the normalizer's reason, never the value."""

    path: str
    reason: str


@dataclass(frozen=True)
class Imported:
    captured: Captured
    labeled: int  # field labels stored, rows' included
    declined: tuple[Declined, ...]


ImportOutcome = Imported | Skipped


def read_label_file(text: str) -> tuple[_Page, ...]:
    """The pages of a label file. Every structural error is reported by its path, without the value."""
    try:
        return _File.model_validate(json.loads(text)).pages
    except json.JSONDecodeError as e:
        raise EvalCliError(f"the label file is not JSON (line {e.lineno})") from None
    except ValidationError as e:
        errors = "\n".join(f"{path}: {reason}" for path, reason in map(field_error, e.errors()))
        raise EvalCliError(f"the label file is invalid:\n{errors}") from None


def schema_names(pages: Sequence[_Page]) -> set[str]:
    return {page.schema_name for page in pages}


def labeled_pages(pages: Sequence[_Page], schemas: Mapping[str, SchemaDef]) -> list[LabeledPage]:
    """Each page as a request to capture with its label values, checked against its schema. Any error rejects the
    whole file, by path, so nothing is fetched for a file that would be stored in part."""
    errors: list[str] = []
    seen: set[str] = set()
    labeled: list[LabeledPage] = []
    for n, page in enumerate(pages, start=1):
        path = f"pages[{n - 1}]"
        schema = schemas[page.schema_name]
        page_errors = list(_page_errors(page, schema, seen))
        seen.add(page.url)
        errors += [f"{path}.{error}" for error in page_errors]
        if not page_errors:
            request = PageRequest(n, page.url, page.schema_name, page.category)
            labeled.append(LabeledPage(request, page.fields, page.rows, page.notes))
    if errors:
        raise EvalCliError("the label file is invalid:\n" + "\n".join(errors))
    return labeled


def _page_errors(page: _Page, schema: SchemaDef, seen: set[str]) -> Iterator[str]:
    if http_host(page.url) is None:
        yield "url: not an http or https URL with a host"
    elif page.url in seen:
        yield "url: the URL is listed twice"
    if page.page_kind is not None and page.page_kind != schema.page_kind:
        yield f"page_kind: schema {schema.name} is for {schema.page_kind} pages"
    if schema.page_kind == "detail":
        if page.rows:
            yield "rows: only listing pages have rows"
        yield from _unknown("fields", page.fields, schema.fields)
        return
    yield from _unknown("fields", page.fields, _scoped(schema, "page"))
    for i, row in enumerate(page.rows):
        yield from _unknown(f"rows[{i}]", row, _scoped(schema, "row"))


def _scoped(schema: SchemaDef, scope: str) -> dict[str, FieldSpec]:
    return {name: spec for name, spec in schema.fields.items() if spec.scope == scope}


def _unknown(path: str, values: Mapping[str, JsonValue], specs: Mapping[str, FieldSpec]) -> Iterator[str]:
    for name in sorted(values.keys() - specs.keys()):
        yield f"{path}.{name}: not a field of the schema here"


def draft_labels(page: LabeledPage, schema: SchemaDef, ctx: Context) -> tuple[Labels, tuple[Declined, ...]]:
    """The page's label values as a draft: each normalized in `ctx`, and those that don't normalize declined."""
    declined: list[Declined] = []
    fields = _field_labels("fields", page.fields, schema, ctx, declined)
    rows = []
    for i, row in enumerate(page.rows):
        # A row that labels no field is no row (as a pre-fill's): it could match no engine row.
        if row_fields := _field_labels(f"rows[{i}]", row, schema, ctx, declined):
            rows.append(LabelRow(fields=row_fields))
    labels = Labels(
        label_version=1, status="draft", prefill_source="none", fields=fields, rows=tuple(rows), notes=page.notes
    )
    # The boundary every label document passes (`parse_labels`), so a draft stored here reads back as one.
    parse_labels(labels.model_dump(mode="json"), schema.page_kind, schema.fields)
    return labels, tuple(declined)


def _field_labels(
    path: str, values: Mapping[str, JsonValue], schema: SchemaDef, ctx: Context, declined: list[Declined]
) -> dict[str, FieldLabel]:
    labels: dict[str, FieldLabel] = {}
    for name, raw in sorted(values.items()):
        if raw is None:
            continue
        spec = schema.fields[name]
        if spec.row_mapped:
            declined.append(Declined(f"{path}.{name}", "row_mapped"))
            continue
        value = _label_value(raw, spec, ctx)
        if isinstance(value, str):
            declined.append(Declined(f"{path}.{name}", value))
        else:
            labels[name] = FieldLabel(value=value.value, absent=False)
    return labels


def _label_value(raw: JsonValue, spec: FieldSpec, ctx: Context) -> Ok | str:
    """The normalized value of a label, or the reason it is not one. A list whose items did not all normalize is not
    the labeled list, so it is declined too."""
    result = normalize(_as_written(raw, spec), spec, ctx)
    if not isinstance(result, Ok):
        return result.reason
    if result.basis in ("url", "unknown"):
        # Ground truth states its currency; a label whose currency only its URL names, or nothing settles, is not one
        # (normalization spec).
        return "unknown_currency"
    if spec.type is FieldType.LIST and result.reasons:
        return "items_dropped"
    return result


# The keys of a normalized location (`normalize.location`): a label in that form names its place by `text`.
_LOCATION_KEYS = frozenset({"text", "locality", "region", "country", "remote_flag"})


def _as_written(raw: JsonValue, spec: FieldSpec) -> JsonValue:
    """A location label given in its normalized form as its `text`, the place as the page writes it, which the location
    normalizer reads as the pipeline reads a page's text; a list of them item by item; any other label as given."""
    if spec.type is FieldType.LIST and spec.item is not None and isinstance(raw, list):
        return [_as_written(item, spec.item) for item in raw]
    written = isinstance(raw, dict) and isinstance(raw.get("text"), str) and raw.keys() <= _LOCATION_KEYS
    return raw["text"] if spec.type is FieldType.LOCATION and written and isinstance(raw, dict) else raw


async def import_pages(
    store: EvalStore,
    schemas: Mapping[str, SchemaDef],
    pages: Sequence[LabeledPage],
    fetch: PageFetch,
    existing: Set[str] = frozenset(),
) -> list[ImportOutcome]:
    """Fetch each page in order with `fetch` (polite and serial: the caller's), store it as an eval page of `store`'s
    split whatever its outcome, and store its draft labels. A page whose URL is in `existing` (the split's pages) is
    skipped, so an interrupted import can be run again."""
    outcomes: list[ImportOutcome] = []
    for page in pages:
        if page.request.url in existing:
            outcomes.append(Skipped(page.request.n, "already_in_split"))
            continue
        schema = schemas[page.request.schema_name]
        result = await fetch(page.request.url, schema)
        if isinstance(result, str):
            outcomes.append(Skipped(page.request.n, result))
            continue
        ref = SchemaRef(schema.id, schema.name, schema.page_kind)
        captured = await store_page(store, ref, page.request, result)
        _, ctx = await parsed_with_context(result.bundle)
        labels, declined = draft_labels(page, schema, ctx)
        await store.put_labels(captured.page_id, labels.model_dump(mode="json"), None, "labeler", expected={})
        outcomes.append(Imported(captured, _count(labels), declined))
    return outcomes


def _count(labels: Labels) -> int:
    return len(labels.fields) + sum(len(row.fields) for row in labels.rows)


def report(outcomes: Sequence[ImportOutcome]) -> str:
    """One JSON line per page, in file order: its capture and page ids, fetch outcome, labels stored and declined."""
    lines = []
    for outcome in sorted(outcomes, key=lambda o: o.captured.n if isinstance(o, Imported) else o.n):
        match outcome:
            case Imported(captured=captured):
                line: dict[str, object] = {
                    "n": captured.n,
                    "capture_id": str(captured.capture_id),
                    "page_id": str(captured.page_id),
                    "status_code": captured.status_code,
                    "block_class": captured.block_class,
                    "error": captured.error,
                    "labeled": outcome.labeled,
                    "declined": [{"path": d.path, "reason": d.reason} for d in outcome.declined],
                }
            case Skipped():
                line = {"n": outcome.n, "skipped": outcome.reason}
        lines.append(json.dumps(line) + "\n")
    return "".join(lines)
