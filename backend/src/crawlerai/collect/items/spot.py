"""Typed value spotting (listings spec, "Rows from blocks"): a string the field type's normalizer parses by a syntax it
checks is a value of the type. Shared by the item layer's align step (a block's elements) and the structural DOM
collector (the main landmark's)."""

from dataclasses import dataclass
from typing import Final

from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.normalize.identifier import has_check_digit
from crawlerai.normalize.units import PER_UNIT, per_suffix
from crawlerai.schemas.paths import price_role
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
    # Only a text showing the checked syntax is a value of the type (`Ok.checked`): an amount without a currency sign
    # is any number.
    return (Spot(raw, normalized, xpath, place),) if isinstance(normalized, Ok) and normalized.checked else ()


def reads(spec: FieldSpec, text: str, ctx: Context, *, struck: bool) -> bool:
    """Whether the field reads a text, struck through or not (extraction spec, "Structural DOM values"): a struck text
    is a former price, read only by a list price; a money field reads by its price role (`schemas.paths.price_role`): a
    unit price only an amount written per unit (`normalize.units`: `€25/kg`), a member price none (its labels read it),
    any other no amount written per unit or per period (`$25/mo`)."""
    role = price_role(spec)
    if role == "list_price" or struck:
        return role == "list_price" and struck
    if spec.type is not FieldType.MONEY:
        return True
    if role == "member_price":
        return False
    per = per_suffix(text, ctx)
    if role == "unit_price":
        return per is not None and PER_UNIT in per[1]
    return per is None
