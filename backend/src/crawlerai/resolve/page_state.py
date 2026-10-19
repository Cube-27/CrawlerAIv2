"""Why a detail page's field is unpublished, from evidence the fetch and the resolution already hold (resolution spec,
"Fields a render would show" and "Out of stock without a price"): no per-site rule, only schema.org semantics and the
attempts the capture records.
"""

from collections.abc import Mapping
from typing import Final

from crawlerai.resolve.types import FieldOutcome, FieldSet
from crawlerai.schemas.paths import named_property, parse_paths
from crawlerai.schemas.types import FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureManifest

# The reason of a field missing for want of any candidate (`resolve.preference`).
NO_CANDIDATES: Final = "no_candidates"
# The reason of a `missing` field a render could show (`interaction_required`).
SCRIPT_RENDERED: Final = "script_rendered"
# The reason of a `missing` price on a page that states its item is not for sale.
OUT_OF_STOCK: Final = "out_of_stock"
# schema.org ItemAvailability: the members that state no unit can be bought.
_NOT_FOR_SALE: Final = frozenset({"OutOfStock", "SoldOut", "Discontinued"})
_AVAILABILITY: Final = "schema:ItemAvailability"
_PRICE: Final = "price"  # schema.org Offer.price


def was_rendered(manifest: CaptureManifest) -> bool:
    """Whether a browser render of the page ran: the kept capture is one, or the fetch tried the browser and kept the
    HTTP page (`fetch_policy.attempts`, each with its `method`)."""
    if manifest.method == "browser":
        return True
    attempts = manifest.fetch_policy.get("attempts")
    return isinstance(attempts, list) and any(isinstance(a, dict) and a.get("method") == "browser" for a in attempts)


def out_of_stock(schema: SchemaDef, fields: FieldSet) -> FieldSet:
    """The fields with each price the page leaves without a candidate saying `out_of_stock`, when its published
    availability states that nothing can be bought (schema.org `OutOfStock`, `SoldOut`, `Discontinued`): the page is
    served and states its item, but an unavailable item has no price to show. The price stays `missing`."""
    if not _unavailable(schema, fields):
        return fields
    return {
        name: outcome.model_copy(update={"reason": OUT_OF_STOCK}) if _is_price(schema, name, outcome) else outcome
        for name, outcome in fields.items()
    }


def _unavailable(schema: SchemaDef, fields: Mapping[str, FieldOutcome]) -> bool:
    return any(
        spec.type is FieldType.ENUM
        and spec.vocab == _AVAILABILITY
        and (outcome := fields.get(name)) is not None
        and outcome.status == "published"
        and outcome.value in _NOT_FOR_SALE
        for name, spec in schema.fields.items()
    )


def _is_price(schema: SchemaDef, name: str, outcome: FieldOutcome) -> bool:
    spec = schema.fields[name]
    return (
        spec.type is FieldType.MONEY
        and spec.schema_org is not None
        and outcome.status == "missing"
        and outcome.reason == NO_CANDIDATES
        and all(named_property(path) == _PRICE for path in parse_paths(spec.schema_org))
    )


def render_could_show(fields: FieldSet, *, rendered: bool, holds_state: bool) -> FieldSet:
    """The fields with each one a render could plausibly supply `interaction_required`: still `missing` for want of
    a candidate (`NO_CANDIDATES`: not rejected, not absent by config, not explained by the page's outcome), on a page
    whose script renders its data (`holds_state`) that no render has been run for. A rendered page leaves them
    `missing`."""
    if rendered or not holds_state:
        return fields
    return {
        name: outcome.model_copy(update={"status": "interaction_required", "reason": SCRIPT_RENDERED})
        if outcome.status == "missing" and outcome.reason == NO_CANDIDATES
        else outcome
        for name, outcome in fields.items()
    }
