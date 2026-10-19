"""The shown variant's availability (variants spec, owner 2026-10-19).

Availability is a variant's, not the product's: where a detail page's Offers disagree on it, the target states one
only when it shows a variant's values, as a page does for its default or selected variant. The target shows a variant
when its own sku or gtin (GS1 GTIN, a seller's SKU: each identifies one variant) is that of exactly one published row,
and the target's published price, sku and gtin are the row's where it states them. That row's availability then
publishes for the target; otherwise the target's stays unpublished, never a default.
"""

from collections.abc import Mapping, MutableMapping
from typing import TypeGuard

from pydantic import JsonValue

from crawlerai.collect.schema_org_map import named_property, parse_paths
from crawlerai.normalize.base import Ok
from crawlerai.normalize.dispatch import equal
from crawlerai.resolve.derive import Derived
from crawlerai.resolve.preference import Chosen, Preference, Unpublished
from crawlerai.resolve.types import FieldOutcome, FieldSet, RowOutcome
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

_AVAILABILITY = "availability"  # schema.org Offer.availability
_SHOWN_IDS = frozenset({"sku", "gtin"})  # GS1 GTIN and a seller's SKU identify one variant
_DISAGREE = "offers_disagree"

Decisions = MutableMapping[str, Preference | Derived]


def shown_variant_availability(schema: SchemaDef, decisions: Decisions, rows: FieldSet) -> None:
    """Give each availability field whose Offers disagree the availability of the variant the target shows, in
    place; a field with no such variant keeps its `offers_disagree`."""
    for name, spec in schema.fields.items():
        decision = decisions.get(name)
        if _disagrees(decision) and _is_availability(spec):
            decisions[name] = _shown_value(schema, decisions, rows, name) or decision


def _shown_value(schema: SchemaDef, decisions: Decisions, rows: FieldSet, name: str) -> Chosen | None:
    """The availability `name` of the variant the target shows, as the target's choice."""
    for row_field in rows.values():
        sub = _shown(schema, decisions, row_field, name)
        if sub is not None and sub.chosen is not None:
            others = tuple(c for c in sub.kept if c is not sub.chosen)
            return Chosen(sub.chosen, others, sub.rejected, sub.kept)
    return None


def _shown(schema: SchemaDef, decisions: Decisions, rows: FieldOutcome, name: str) -> FieldOutcome | None:
    """The sub-field `name` of the row the target shows, when that row publishes it."""
    row = _shown_row(schema, decisions, rows)
    sub = None if row is None else row.fields.get(name)
    return sub if sub is not None and sub.status == "published" else None


def _disagrees(decision: Preference | Derived | None) -> TypeGuard[Unpublished]:
    return isinstance(decision, Unpublished) and decision.reason == _DISAGREE


def _is_availability(spec: FieldSpec) -> bool:
    return spec.schema_org is not None and all(
        named_property(path) == _AVAILABILITY for path in parse_paths(spec.schema_org)
    )


def _shown_row(
    schema: SchemaDef, decisions: Mapping[str, Preference | Derived], rows: FieldOutcome
) -> RowOutcome | None:
    """The one published row whose sku or gtin is the target's and whose price, sku and gtin the target's published
    ones are."""
    shown = {
        name: value
        for name, value in _published_values(decisions).items()
        if _identifies(schema.fields[name]) or schema.fields[name].type is FieldType.MONEY
    }
    ids = {name for name in shown if _identifies(schema.fields[name])}
    matching = [
        row
        for row in rows.items or ()
        if any(_same(schema.fields[name], shown[name], row, name) for name in ids)
        and all(_same(schema.fields[name], value, row, name, absent=True) for name, value in shown.items())
    ]
    return matching[0] if len(matching) == 1 else None


def _identifies(spec: FieldSpec) -> bool:
    return spec.type is FieldType.IDENTIFIER and spec.scheme in _SHOWN_IDS


def _published_values(decisions: Mapping[str, Preference | Derived]) -> dict[str, JsonValue]:
    return {
        name: decision.candidate.normalized.value
        for name, decision in decisions.items()
        if isinstance(decision, Chosen) and isinstance(decision.candidate.normalized, Ok)
    }


def _same(spec: FieldSpec, value: JsonValue, row: RowOutcome, name: str, *, absent: bool = False) -> bool:
    """Whether the row publishes `value` for its sub-field `name`; `absent`: a sub-field the row does not publish
    counts as the same."""
    sub = row.fields.get(name)
    if sub is None or sub.status != "published":
        return absent
    return equal(value, sub.value, spec)
