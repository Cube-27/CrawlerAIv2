"""Eval page labels (SPEC-03 §4.3): the `eval_page.labels` document, its validation and type equality.

`parse_labels` is the boundary: it checks the document's structure, the two-pass rule (ARCHITECTURE §16.2) and
the fields against the page's schema, and reports every error with its path and reason, so nothing partial is
saved (§4.11). Whether each `value` is a valid normalized value is the type normalizer's call (SPEC-04), made by
the labeling API (SPEC-03 PR 8).

Values compare by type equality (SPEC-04 §4.5), `crawlerai.normalize.dispatch.equal`.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic_core import ErrorDetails

from crawlerai.db.models import PageKind
from crawlerai.normalize.dispatch import equal
from crawlerai.schemas.types import FieldSpec

LabelStatus = Literal["draft", "labeled", "checked"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


_FIELD_SPECS: TypeAdapter[dict[str, FieldSpec]] = TypeAdapter(dict[str, FieldSpec])


def field_specs(fields: Mapping[str, JsonValue]) -> dict[str, FieldSpec]:
    """A schema document's `fields` (SPEC-04 §4.2, `schema_def.fields`) as field specs."""
    return _FIELD_SPECS.validate_python(fields)


def _check_locator(locator: str) -> str:
    # The three locator forms of SPEC-03 §4.3; text offsets index the page's cleaned text.
    form = re.fullmatch(r"xpath:.+|jsonld:.+|text:(\d+)-(\d+)", locator, re.DOTALL)
    if form is None:
        raise ValueError("must be 'xpath:…', 'jsonld:…' or 'text:<start>-<end>'")
    if form[1] is not None and int(form[1]) >= int(form[2]):
        raise ValueError("text offsets need start < end")
    return locator


def _check_prefill_source(source: str) -> str:
    if source != "none" and re.fullmatch(r"llm:.+", source) is None:
        raise ValueError("must be 'none' or 'llm:<model>'")
    return source


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def same_person(a: str, b: str) -> bool:
    """Whether two names are one person's (§16.2's two passes): equal after Unicode case folding."""
    return a.casefold() == b.casefold()


class FieldLabel(_Model):
    """One field's label. `absent` means the field is genuinely not on the page (G2); `distractors` are values of the
    same field shown for another entity on the page, which drive the wrong-product metric (§16.3)."""

    value: JsonValue = None
    absent: bool
    locator: Annotated[str, AfterValidator(_check_locator)] | None = None
    distractors: tuple[JsonValue, ...] = ()

    @model_validator(mode="after")
    def _value_matches_absent(self) -> Self:
        if self.absent and self.value is not None:
            raise ValueError("an absent field has no value")
        if self.absent and self.locator is not None:
            raise ValueError("an absent field has no locator")
        if not self.absent and self.value is None:
            raise ValueError("a present field has a value")
        return self


class LabelRow(_Model):
    fields: dict[str, FieldLabel]


class Labels(_Model):
    label_version: Literal[1]
    status: LabelStatus
    labeler: Name | None = None
    checker: Name | None = None
    prefill_source: Annotated[str, AfterValidator(_check_prefill_source)] | None = None
    fields: dict[str, FieldLabel] = {}
    rows: tuple[LabelRow, ...] = ()  # listing pages only, in page order
    notes: str = ""

    @model_validator(mode="after")
    def _two_passes(self) -> Self:
        # ARCHITECTURE §16.2: a labeler, then a checker who is a different person.
        if self.status != "draft" and self.labeler is None:
            raise ValueError("a labeled or checked page names its labeler")
        if self.status == "checked" and (
            self.labeler is None or self.checker is None or same_person(self.checker, self.labeler)
        ):
            raise ValueError("a checked page is checked by someone other than its labeler")
        if self.status != "checked" and self.checker is not None:
            raise ValueError("only a checked page names a checker")
        return self


@dataclass(frozen=True)
class LabelError:
    path: str  # dotted, e.g. "rows[0].fields.price.distractors[1]"; "" for the document
    reason: str


class InvalidLabels(Exception):
    def __init__(self, errors: Sequence[LabelError]) -> None:
        super().__init__("; ".join(f"{e.path or '<labels>'}: {e.reason}" for e in errors))
        self.errors = tuple(errors)


def parse_labels(raw: JsonValue, page_kind: PageKind, specs: Mapping[str, FieldSpec]) -> Labels:
    """Validate a labels document for a page of `page_kind` whose schema has the fields `specs`.

    Raises `InvalidLabels` with every error found. Drafts may leave fields unlabeled; labeled and checked pages
    label every field, because metrics need the label to score the engine's output (§4.6).
    """
    try:
        labels = Labels.model_validate(raw)
    except ValidationError as e:
        raise InvalidLabels([from_pydantic(err) for err in e.errors()]) from None
    complete = labels.status != "draft"
    check = _check_detail if page_kind == "detail" else _check_listing
    errors = list(check(labels, specs, complete))
    if errors:
        raise InvalidLabels(errors)
    return labels


def _check_detail(labels: Labels, specs: Mapping[str, FieldSpec], complete: bool) -> Iterator[LabelError]:
    # On a detail page every field belongs to the one entity (SPEC-04 §4.2), whatever its scope.
    yield from _check_fields("fields", labels.fields, specs, specs, complete)
    if labels.rows:
        yield LabelError("rows", "only listing pages have rows")


def _check_listing(labels: Labels, specs: Mapping[str, FieldSpec], complete: bool) -> Iterator[LabelError]:
    page = {name: spec for name, spec in specs.items() if spec.scope == "page"}
    row = {name: spec for name, spec in specs.items() if spec.scope == "row"}
    yield from _check_fields("fields", labels.fields, page, specs, complete)
    for i, label_row in enumerate(labels.rows):
        yield from _check_fields(f"rows[{i}].fields", label_row.fields, row, specs, complete)


def _check_fields(
    path: str,
    labels: Mapping[str, FieldLabel],
    expected: Mapping[str, FieldSpec],
    specs: Mapping[str, FieldSpec],
    complete: bool,
) -> Iterator[LabelError]:
    for name, label in labels.items():
        spec = expected.get(name)
        if spec is None:
            yield LabelError(f"{path}.{name}", _misplaced(name, specs))
        else:
            yield from _check_distractors(f"{path}.{name}", label, spec)
    if complete:
        for name in expected.keys() - labels.keys():
            yield LabelError(f"{path}.{name}", "not labeled; mark it absent if the page does not show it")


def _misplaced(name: str, specs: Mapping[str, FieldSpec]) -> str:
    """Why a label for `name` is not expected where it is."""
    if name not in specs:
        return "not a field of the schema"
    if specs[name].scope == "row":
        return "a row field belongs in rows"
    return "a page field belongs in fields"


def _check_distractors(path: str, label: FieldLabel, spec: FieldSpec) -> Iterator[LabelError]:
    for i, distractor in enumerate(label.distractors):
        if distractor is None:
            yield LabelError(f"{path}.distractors[{i}]", "a distractor has a value")
        elif label.value is not None and equal(distractor, label.value, spec):
            yield LabelError(f"{path}.distractors[{i}]", "a distractor equals the value")


def from_pydantic(err: ErrorDetails) -> LabelError:
    path = "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in err["loc"]).removeprefix(".")
    # Our own validators raise ValueError; pydantic prefixes its message with "Value error, ".
    reason = str(err["ctx"]["error"]) if err["type"] == "value_error" else err["msg"]
    return LabelError(path, reason)
