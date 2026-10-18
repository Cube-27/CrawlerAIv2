"""Typed value spotting (listings spec, "Rows from blocks"): a string the field type's normalizer parses by a syntax it
checks is a value of the type. Shared by the item layer's align step (a block's elements) and the structural DOM
collector (the main landmark's)."""

from dataclasses import dataclass
from typing import Final

from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.normalize.identifier import has_check_digit
from crawlerai.schemas.types import FieldSpec, FieldType

# The types whose normalizer checks a syntax, so a text it accepts is a value of the type (ISO 4217 and CLDR amounts,
# ISO 8601 and CLDR dates); identifiers qualify under a scheme with a check digit (`is_typed`).
SPOTTED: Final = frozenset({FieldType.MONEY, FieldType.DATE, FieldType.DATETIME})


@dataclass(frozen=True, slots=True)
class Spot:
    """One value read in a block: its raw text, its normalized value, the XPath of its element and its place."""

    raw: str
    normalized: Ok
    xpath: str
    place: str


def is_typed(spec: FieldSpec) -> bool:
    """Whether the field's type has a checkable syntax, so its values can be spotted in free text."""
    return spec.type in SPOTTED or (spec.type is FieldType.IDENTIFIER and has_check_digit(spec))


def spots(raw: str, spec: FieldSpec, ctx: Context, xpath: str, place: str) -> tuple[Spot, ...]:
    normalized = normalize(raw, spec, ctx)
    return (Spot(raw, normalized, xpath, place),) if isinstance(normalized, Ok) else ()
