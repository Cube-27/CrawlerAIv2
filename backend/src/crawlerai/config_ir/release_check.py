"""The release check (SPEC-08 §4.12, ARCHITECTURE §12.3, INV-20): before a config is exported, the independent release
executor runs it on the held-out pages, and each field is compared with what the engine published there.

A field passes when it reproduces the engine's value on every held-out page with one while there are fewer than 10
such pages, and on at least 95% of them from 10 on; otherwise the export marks it `manual`. A field the engine
published on no held-out page cannot be shown to match and is `manual` too, as is a suspended field (the release
executor does not run it) and one the schema lacks. Values are compared as validation compares them (§4.7): the
release executor's value normalized as the engine normalizes it, then `equal`. Row fields are compared row by row in
document order, and only when the release executor finds as many rows as the engine published (D-0566).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final

from pydantic import BaseModel, ConfigDict, JsonValue

from crawlerai.config_ir.model import NEXT_PAGE_FIELD, ExtractionConfigIR
from crawlerai.config_ir.release_executor import Released, ReleasePage, release_run
from crawlerai.config_ir.release_rules import release_rules
from crawlerai.config_ir.validation import EVERY_PAGE_BELOW, HeldOutPage, release_value
from crawlerai.db.models import CaptureId
from crawlerai.normalize.dispatch import equal
from crawlerai.schemas.types import FieldSpec, SchemaDef

# ARCHITECTURE §12.3: from 10 pages with an engine value on, a field passes on at least 95% of them.
RELEASE_SHARE: Final = Fraction(19, 20)


class _Report(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReleaseField(_Report):
    """One field on the held-out pages: `published`, pages where the engine published it; `reproduced`, those where the
    release executor gave that value; `manual`, the field failed the check."""

    published: int
    reproduced: int
    manual: bool


class ReleaseListing(_Report):
    fields: dict[str, ReleaseField]
    next: ReleaseField | None


class ReleaseReport(_Report):
    """The release check of one config: the held-out captures it ran on, and each field's result."""

    held_out: list[CaptureId]
    fields: dict[str, ReleaseField]
    listing: ReleaseListing | None


def releasable(published: int, reproduced: int) -> bool:
    """§12.3: every page with an engine value while there are fewer than `EVERY_PAGE_BELOW`, at least `RELEASE_SHARE`
    from then on; never with none."""
    if published < EVERY_PAGE_BELOW:
        return published > 0 and reproduced == published
    return Fraction(reproduced, published) >= RELEASE_SHARE


def release_check(ir: ExtractionConfigIR, schema: SchemaDef, held_out: Sequence[HeldOutPage]) -> ReleaseReport:
    runs = [_Run.of(ir, schema, page) for page in held_out]
    fields = {name: _field(runs, name, schema, _page_seen) for name in ir.fields}
    listing = None
    if ir.listing is not None:
        rows = {name: _field(runs, name, schema, _row_seen) for name in ir.listing.fields}
        next_ = _field(runs, NEXT_PAGE_FIELD, schema, _page_seen) if ir.listing.next is not None else None
        listing = ReleaseListing(fields=rows, next=next_)
    return ReleaseReport(held_out=[page.capture_id for page in held_out], fields=fields, listing=listing)


@dataclass(frozen=True, slots=True)
class _Run:
    page: HeldOutPage
    released: Released

    @classmethod
    def of(cls, ir: ExtractionConfigIR, schema: SchemaDef, page: HeldOutPage) -> "_Run":
        release_page = ReleasePage(page.page.html, page.page.network, page.ctx.base_url)
        return cls(page, release_run(ir, release_page, release_rules(schema, page.ctx)))


# Whether the engine published the field on the page, and whether the release executor reproduced it there.
type _Seen = Callable[[_Run, str, FieldSpec], tuple[bool, bool]]


def _field(runs: Sequence[_Run], name: str, schema: SchemaDef, seen: _Seen) -> ReleaseField:
    spec = schema.fields.get(name)
    results = [] if spec is None else [seen(run, name, spec) for run in runs]
    published = sum(on for on, _ in results)
    reproduced = sum(on and same for on, same in results)
    return ReleaseField(published=published, reproduced=reproduced, manual=not releasable(published, reproduced))


def _page_seen(run: _Run, name: str, spec: FieldSpec) -> tuple[bool, bool]:
    published = run.page.facts.published.get(name)
    if published is None:
        return False, False
    return True, _same(release_value(run.released.fields, name, spec, run.page.ctx), published, spec)


def _row_seen(run: _Run, name: str, spec: FieldSpec) -> tuple[bool, bool]:
    engine, released = run.page.rows, run.released.rows
    published = [(n, value) for n, facts in enumerate(engine) if (value := facts.published.get(name)) is not None]
    if not published:
        return False, False
    aligned = len(engine) == len(released)
    ctx = run.page.ctx
    return True, aligned and all(_same(release_value(released[n], name, spec, ctx), v, spec) for n, v in published)


def _same(released: JsonValue | None, published: JsonValue, spec: FieldSpec) -> bool:
    return released is not None and equal(released, published, spec)
