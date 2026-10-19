"""The release check (learning-configs spec, INV-20): before a config is exported, the independent release
executor runs it on the held-out pages, and each field is compared with what the engine published there.

A field passes when it reproduces the engine's value on every held-out page with one while there are fewer than 10
such pages, and on at least 95% of them from 10 on; otherwise the export marks it `manual`. A field the engine
published on no held-out page cannot be shown to match and is `manual` too, as is a suspended field (the release
executor does not run it) and one the schema lacks. Values are compared as validation compares them (§4.7): the
release executor's value normalized as the engine normalizes it, then `equal`. Row fields are compared row by row in
document order, the engine's rows aligned with the release executor's as validation aligns them (D-1500), and only
when the release executor reads at least as many rows as the engine published.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final

from pydantic import BaseModel, ConfigDict, JsonValue

from crawlerai.config_ir.executability import Executability, class_counts, config_classes
from crawlerai.config_ir.model import NEXT_PAGE_FIELD, ExtractionConfigIR
from crawlerai.config_ir.release_executor import Released
from crawlerai.config_ir.row_alignment import align
from crawlerai.config_ir.validation import HeldOutPage, agreeing, release_on, release_value, small_n_rule
from crawlerai.db.models import CaptureId
from crawlerai.normalize.dispatch import equal
from crawlerai.schemas.types import FieldSpec, SchemaDef

# From 10 pages with an engine value on, a field passes on at least 95% of them.
RELEASE_SHARE: Final = Fraction(19, 20)


class _Report(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReleaseField(_Report):
    """One field on the held-out pages: `published`, pages where the engine published it; `reproduced`, those where the
    release executor gave that value; `manual`, the field failed the check; `executability`, what the field's steps
    need to run (`config_ir.executability`)."""

    published: int
    reproduced: int
    manual: bool
    executability: Executability


class ReleaseListing(_Report):
    fields: dict[str, ReleaseField]
    next: ReleaseField | None


class ReleaseReport(_Report):
    """The release check of one config: the held-out captures it ran on, each field's result, and how many of the
    config's fields are in each executability class."""

    held_out: list[CaptureId]
    fields: dict[str, ReleaseField]
    listing: ReleaseListing | None
    executability: dict[Executability, int]


def releasable(published: int, reproduced: int) -> bool:
    """§12.3: every page with an engine value while there are fewer than 10, at least `RELEASE_SHARE` from then on;
    never with none."""
    return small_n_rule(published, reproduced, minimum=1, share=RELEASE_SHARE)


def release_check(ir: ExtractionConfigIR, schema: SchemaDef, held_out: Sequence[HeldOutPage]) -> ReleaseReport:
    runs = [_Run.of(ir, schema, page) for page in held_out]
    classes = config_classes(ir)
    fields = {name: _field(runs, name, schema, _page_seen, classes[name]) for name in ir.fields}
    listing = None
    if ir.listing is not None:
        rows = {name: _field(runs, name, schema, _row_seen, classes[f"listing:{name}"]) for name in ir.listing.fields}
        next_ = None
        if ir.listing.next is not None:
            next_ = _field(runs, NEXT_PAGE_FIELD, schema, _page_seen, classes["listing:next"])
        listing = ReleaseListing(fields=rows, next=next_)
    return ReleaseReport(
        held_out=[page.capture_id for page in held_out], fields=fields, listing=listing, executability=class_counts(ir)
    )


@dataclass(frozen=True, slots=True)
class _Run:
    """The release executor's output on a held-out page, and for each engine row the released row it aligns with."""

    page: HeldOutPage
    released: Released
    aligned: Sequence[int | None]

    @classmethod
    def of(cls, ir: ExtractionConfigIR, schema: SchemaDef, page: HeldOutPage) -> "_Run":
        released = release_on(ir, schema, page)
        names = [name for name in (ir.listing.fields if ir.listing is not None else {}) if name in schema.fields]
        released_rows = [
            {
                name: value
                for name in names
                if (value := release_value(row, name, schema.fields[name], page.ctx)) is not None
            }
            for row in released.rows
        ]
        engine_rows = [facts.published for facts in page.rows]
        return cls(page, released, align(engine_rows, released_rows, agreeing(schema)))


# Whether the engine published the field on the page, and whether the release executor reproduced it there.
type _Seen = Callable[[_Run, str, FieldSpec], tuple[bool, bool]]


def _field(
    runs: Sequence[_Run], name: str, schema: SchemaDef, seen: _Seen, executability: Executability
) -> ReleaseField:
    spec = schema.fields.get(name)
    results = [] if spec is None else [seen(run, name, spec) for run in runs]
    published = sum(on for on, _ in results)
    reproduced = sum(on and same for on, same in results)
    return ReleaseField(
        published=published,
        reproduced=reproduced,
        manual=not releasable(published, reproduced),
        executability=executability,
    )


def _page_seen(run: _Run, name: str, spec: FieldSpec) -> tuple[bool, bool]:
    published = run.page.facts.published.get(name)
    if published is None:
        return False, False
    return True, _same(release_value(run.released.fields, name, spec, run.page.ctx), published, spec)


def _row_seen(run: _Run, name: str, spec: FieldSpec) -> tuple[bool, bool]:
    released = run.released.rows
    published = [
        (n, value)
        for n, facts in zip(run.aligned, run.page.rows, strict=True)
        if (value := facts.published.get(name)) is not None
    ]
    if not published:
        return False, False
    if len(released) < len(run.page.rows):
        return True, False  # the module's rule: at least as many rows as the engine published, as validation counts
    ctx = run.page.ctx
    return True, all(
        n is not None and _same(release_value(released[n], name, spec, ctx), v, spec) for n, v in published
    )


def _same(released: JsonValue | None, published: JsonValue, spec: FieldSpec) -> bool:
    return released is not None and equal(released, published, spec)
