"""The shown variant's availability (variants spec, D-1780).

Availability is a variant's, not the product's: where a detail page's Offers disagree on it, the target states one
only when it shows a variant's values, as a page does for its default or selected variant. The target shows a variant
when its own published sku or gtin (GS1 GTIN, a seller's SKU: each identifies one variant) is that of exactly one
published row, and the target's published price, sku and gtin are the row's where both state them. That row's
availability then publishes for the target; otherwise the target's stays unpublished, never a default. The target's
values are read after assessment, so a value below the confidence threshold never selects a row. A row's sub-field
stands for a target field when it is the one of its type and scheme that maps the same schema.org properties.
"""

from collections.abc import Mapping

from pydantic import JsonValue

from crawlerai.collect.schema_org_map import named_property, parse_paths
from crawlerai.normalize.dispatch import equal
from crawlerai.resolve.derive import Derived
from crawlerai.resolve.preference import Chosen, Preference, Unpublished
from crawlerai.resolve.types import FieldOutcome, FieldSet, RowOutcome
from crawlerai.schemas.types import FieldSpec, FieldType, IdentifierScheme, SchemaDef

_AVAILABILITY = "availability"  # schema.org Offer.availability
_SHOWN_IDS = frozenset({"sku", "gtin"})  # GS1 GTIN and a seller's SKU identify one variant
_DISAGREE = "offers_disagree"

# A target field the row is compared on: its spec, its published value, and the row's sub-field that stands for it.
_Shown = tuple[FieldSpec, JsonValue, str]


def shown_variant_availability(
    schema: SchemaDef, decisions: Mapping[str, Preference | Derived], fields: FieldSet, rows: FieldSet
) -> dict[str, Chosen]:
    """For each availability field whose Offers disagree, the availability of the variant the target shows, as the
    target's choice; `fields` are the target's assessed outcomes. A field with no such variant is left out."""
    shown: dict[str, Chosen] = {}
    for name, spec in schema.fields.items():
        if _disagrees(decisions.get(name)) and _is_availability(spec):
            chosen = _shown_value(schema, fields, rows, spec)
            if chosen is not None:
                shown[name] = chosen
    return shown


def _shown_value(schema: SchemaDef, fields: FieldSet, rows: FieldSet, spec: FieldSpec) -> Chosen | None:
    for row_name, row_field in rows.items():
        item = schema.fields[row_name].item
        subs = {} if item is None or item.fields is None else item.fields
        sub = _shown(schema, fields, row_field, subs, spec)
        if sub is not None and sub.chosen is not None:
            others = tuple(c for c in sub.kept if c is not sub.chosen)
            return Chosen(sub.chosen, others, sub.rejected, sub.kept)
    return None


def _shown(
    schema: SchemaDef, fields: FieldSet, rows: FieldOutcome, subs: Mapping[str, FieldSpec], spec: FieldSpec
) -> FieldOutcome | None:
    """The sub-field standing for `spec` of the row the target shows, when that row publishes it."""
    row = _shown_row(schema, fields, rows, subs)
    name = _counterpart(spec, subs)
    sub = None if row is None or name is None else row.fields.get(name)
    return sub if sub is not None and sub.status == "published" else None


def _disagrees(decision: Preference | Derived | None) -> bool:
    return isinstance(decision, Unpublished) and decision.reason == _DISAGREE


def _is_availability(spec: FieldSpec) -> bool:
    return spec.schema_org is not None and all(
        named_property(path) == _AVAILABILITY for path in parse_paths(spec.schema_org)
    )


def _shown_row(
    schema: SchemaDef, fields: FieldSet, rows: FieldOutcome, subs: Mapping[str, FieldSpec]
) -> RowOutcome | None:
    """The one published row whose sku or gtin is the target's and whose price, sku and gtin the target's published
    ones are."""
    shown = _compared(schema, fields, subs)
    ids = [compared for compared in shown if _identifies(compared[0])]
    matching = [
        row
        for row in rows.items or ()
        if any(_same(compared, row) for compared in ids)
        and all(_same(compared, row, absent=True) for compared in shown)
    ]
    return matching[0] if len(matching) == 1 else None


def _compared(schema: SchemaDef, fields: FieldSet, subs: Mapping[str, FieldSpec]) -> list[_Shown]:
    """The target's published identifiers and prices that the rows have a sub-field for."""
    compared: list[_Shown] = []
    for name, outcome in fields.items():
        spec = schema.fields.get(name)
        if spec is None or outcome.status != "published" or not (_identifies(spec) or spec.type is FieldType.MONEY):
            continue
        sub = _counterpart(spec, subs)
        if sub is not None:
            compared.append((spec, outcome.value, sub))
    return compared


def _counterpart(spec: FieldSpec, subs: Mapping[str, FieldSpec]) -> str | None:
    """The one sub-field of the same type and scheme that maps the same schema.org properties as `spec`."""
    found = [name for name, sub in subs.items() if _role(sub) == _role(spec)]
    return found[0] if len(found) == 1 else None


def _role(spec: FieldSpec) -> tuple[FieldType, IdentifierScheme | None, frozenset[str]] | None:
    if spec.schema_org is None:
        return None
    return spec.type, spec.scheme, frozenset(named_property(path) for path in parse_paths(spec.schema_org))


def _identifies(spec: FieldSpec) -> bool:
    return spec.type is FieldType.IDENTIFIER and spec.scheme in _SHOWN_IDS


def _same(compared: _Shown, row: RowOutcome, *, absent: bool = False) -> bool:
    """Whether the row publishes the target's value; `absent`: a sub-field the row does not publish counts as the
    same."""
    spec, value, name = compared
    sub = row.fields.get(name)
    if sub is None or sub.status != "published":
        return absent
    return equal(value, sub.value, spec)
