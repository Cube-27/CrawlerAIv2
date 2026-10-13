"""Eval page labels (SPEC-03 §4.3): the `eval_page.labels` document, its validation and type equality.

`parse_labels` is the boundary: it checks the document's structure, the two-pass rule (ARCHITECTURE §16.2) and
the fields against the page's schema, and reports every error with its path and reason, so nothing partial is
saved (§4.11). Whether each `value` is a valid normalized value is the type normalizer's call (SPEC-04), made by
the labeling API (SPEC-03 PR 8).

`FieldShape` is the part of a schema field that labels need: its type, nesting and scope. SPEC-04 PR 1 brings the
full `FieldSpec`; callers then pass that instead, and `FieldShape` goes.
"""

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Self, assert_never

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic_core import ErrorDetails

from crawlerai.db.models import PageKind
from crawlerai.normalize import date, enum, identifier, location, money, text, url
from crawlerai.normalize import range as range_

LabelStatus = Literal["draft", "labeled", "checked"]
Scope = Literal["row", "page"]
# The §5.1 types that have values of their own (SPEC-04 §4.1); `list` and `object` recurse into them.
ScalarType = Literal[
    "text", "long_text", "money", "enum", "url", "image_url", "identifier", "date", "datetime", "location", "range"
]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScalarShape(_Model):
    type: ScalarType
    scope: Scope = "row"


class ListShape(_Model):
    type: Literal["list"]
    item: "FieldShape"
    scope: Scope = "row"


class ObjectShape(_Model):
    type: Literal["object"]
    fields: dict[str, "FieldShape"]
    scope: Scope = "row"


FieldShape = Annotated[ScalarShape | ListShape | ObjectShape, Field(discriminator="type")]
_FIELD_SHAPES: TypeAdapter[dict[str, FieldShape]] = TypeAdapter(dict[str, FieldShape])


def field_shapes(fields: Mapping[str, JsonValue]) -> dict[str, FieldShape]:
    """The shapes of a schema document's `fields` (SPEC-04 §4.2, `schema_def.fields`): each field's type, scope and
    nesting, without the parts labels don't read (`required`, `description`, `schema_org`, ...)."""
    return _FIELD_SHAPES.validate_python({name: _shape_part(spec) for name, spec in fields.items()})


def _shape_part(spec: JsonValue) -> JsonValue:
    if not isinstance(spec, dict):
        return spec  # not a field document: validation rejects it
    part: dict[str, JsonValue] = {key: spec[key] for key in ("type", "scope") if key in spec}
    if "item" in spec:
        part["item"] = _shape_part(spec["item"])
    if isinstance(nested := spec.get("fields"), dict):
        part["fields"] = {name: _shape_part(sub) for name, sub in nested.items()}
    return part


def values_equal(a: JsonValue, b: JsonValue, shape: FieldShape) -> bool:
    """Type equality (SPEC-04 §4.5): each scalar type's normalizer decides; a list is a multiset of its items, an
    object is equal field by field."""
    match shape:
        case ListShape(item=item):
            return isinstance(a, list) and isinstance(b, list) and _multiset_equal(a, b, item)
        case ObjectShape(fields=fields):
            return (
                isinstance(a, dict)
                and isinstance(b, dict)
                and a.keys() == b.keys() <= fields.keys()
                and all(values_equal(a[name], b[name], fields[name]) for name in a)
            )
        case ScalarShape(type=type_):
            return _scalar_equal(type_)(a, b)
        case _:
            assert_never(shape)


def _scalar_equal(type_: ScalarType) -> Callable[[JsonValue, JsonValue], bool]:
    match type_:
        case "text" | "long_text":
            return text.equal
        case "money":
            return money.equal
        case "enum":
            return enum.equal
        case "url" | "image_url":
            return url.equal
        case "identifier":
            return identifier.equal
        case "date" | "datetime":
            return date.equal
        case "location":
            return location.equal
        case "range":
            return range_.equal
        case _:
            assert_never(type_)


def _multiset_equal(a: Sequence[JsonValue], b: Sequence[JsonValue], item: FieldShape) -> bool:
    # Greedy matching is exact because type equality is an equivalence relation.
    if len(a) != len(b):
        return False
    unmatched = list(b)
    for x in a:
        match = next((i for i, y in enumerate(unmatched) if values_equal(x, y, item)), None)
        if match is None:
            return False
        del unmatched[match]
    return True


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
            self.labeler is None or self.checker is None or self.checker.casefold() == self.labeler.casefold()
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


def parse_labels(raw: JsonValue, page_kind: PageKind, shapes: Mapping[str, FieldShape]) -> Labels:
    """Validate a labels document for a page of `page_kind` whose schema has the fields `shapes`.

    Raises `InvalidLabels` with every error found. Drafts may leave fields unlabeled; labeled and checked pages
    label every field, because metrics need the label to score the engine's output (§4.6).
    """
    try:
        labels = Labels.model_validate(raw)
    except ValidationError as e:
        raise InvalidLabels([from_pydantic(err) for err in e.errors()]) from None
    complete = labels.status != "draft"
    if page_kind == "detail":
        # On a detail page every field belongs to the one entity (SPEC-04 §4.2), whatever its scope.
        errors = list(_check_fields("fields", labels.fields, shapes, shapes, complete))
        if labels.rows:
            errors.append(LabelError("rows", "only listing pages have rows"))
    else:
        page = {name: shape for name, shape in shapes.items() if shape.scope == "page"}
        row = {name: shape for name, shape in shapes.items() if shape.scope == "row"}
        errors = list(_check_fields("fields", labels.fields, page, shapes, complete))
        for i, label_row in enumerate(labels.rows):
            errors.extend(_check_fields(f"rows[{i}].fields", label_row.fields, row, shapes, complete))
    if errors:
        raise InvalidLabels(errors)
    return labels


def _check_fields(
    path: str,
    labels: Mapping[str, FieldLabel],
    expected: Mapping[str, FieldShape],
    shapes: Mapping[str, FieldShape],
    complete: bool,
) -> Iterator[LabelError]:
    for name, label in labels.items():
        shape = expected.get(name)
        if shape is None:
            if name not in shapes:
                yield LabelError(f"{path}.{name}", "not a field of the schema")
            elif shapes[name].scope == "row":
                yield LabelError(f"{path}.{name}", "a row field belongs in rows")
            else:
                yield LabelError(f"{path}.{name}", "a page field belongs in fields")
            continue
        for i, distractor in enumerate(label.distractors):
            if distractor is None:
                yield LabelError(f"{path}.{name}.distractors[{i}]", "a distractor has a value")
            elif label.value is not None and values_equal(distractor, label.value, shape):
                yield LabelError(f"{path}.{name}.distractors[{i}]", "a distractor equals the value")
    if complete:
        for name in expected.keys() - labels.keys():
            yield LabelError(f"{path}.{name}", "not labeled; mark it absent if the page does not show it")


def from_pydantic(err: ErrorDetails) -> LabelError:
    path = "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in err["loc"]).removeprefix(".")
    # Our own validators raise ValueError; pydantic prefixes its message with "Value error, ".
    reason = str(err["ctx"]["error"]) if err["type"] == "value_error" else err["msg"]
    return LabelError(path, reason)
