"""The normalize dispatcher (SPEC-04 §4.3, §4.5): the entry points that send each field type to its one module (C8).

Callers (the resolver, eval, the API) normalize and compare through `normalize` and `equal` and never pick a type
module themselves. `list` and `object` have no values of their own (§4.1), so both recurse here into their items and
sub-fields.
"""

from collections.abc import Iterator, Sequence
from functools import partial

from pydantic import JsonValue

from crawlerai.normalize import date, enum, identifier, location, money, text, url
from crawlerai.normalize import range as range_
from crawlerai.normalize.base import Ambiguous, Context, Equality, Invalid, Normalizer, NormalizeResult, Ok, Raw
from crawlerai.schemas.types import FieldSpec, FieldType

_MONEY = FieldSpec(type=FieldType.MONEY)


def _money(raw: Raw, ctx: Context) -> NormalizeResult:
    # A range resolves its currency by the money rules (SPEC-04 §4.4) through this registry, so range does not
    # import money (C8).
    return normalize(raw, _MONEY, ctx)


# The field-type registry: every §5.1 type with values of its own, with its normalizer and its equality.
_TYPES: dict[FieldType, tuple[Normalizer, Equality]] = {
    FieldType.TEXT: (text.normalize, text.equal),
    FieldType.LONG_TEXT: (text.normalize, text.equal),
    FieldType.ENUM: (enum.normalize, enum.equal),
    FieldType.MONEY: (money.normalize, money.equal),
    FieldType.LOCATION: (location.normalize, location.equal),
    FieldType.URL: (url.normalize, url.equal),
    FieldType.IDENTIFIER: (identifier.normalize, identifier.equal),
    FieldType.IMAGE_URL: (url.normalize, url.equal),
    FieldType.DATE: (date.normalize, date.equal),
    FieldType.DATETIME: (date.normalize, date.equal),
    FieldType.RANGE: (partial(range_.normalize, money=_money), range_.equal),
}


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize `raw` as `spec`'s type. A type with no normalizer declines (§4.7), so a schema that names one
    cannot crash a job."""
    if spec.type is FieldType.LIST:
        return _list(raw, _item(spec), ctx)
    if spec.type is FieldType.OBJECT:
        return _object(raw, _fields(spec), ctx)
    registered = _TYPES.get(spec.type)
    if registered is None:
        return Invalid("unknown_type")
    return registered[0](raw, spec, ctx)


def equal(a: JsonValue, b: JsonValue, spec: FieldSpec) -> bool:
    """Whether two normalized values of `spec`'s type are the same value (SPEC-04 §4.5). Reflexive and symmetric for
    every JSON value; values of another shape are equal only when identical."""
    if a == b:
        return True
    if spec.type is FieldType.LIST:
        return isinstance(a, list) and isinstance(b, list) and _multiset_equal(a, b, _item(spec))
    if spec.type is FieldType.OBJECT:
        fields = _fields(spec)
        return (
            isinstance(a, dict)
            and isinstance(b, dict)
            and a.keys() == b.keys() <= fields.keys()
            and all(equal(a[name], b[name], fields[name]) for name in a)
        )
    registered = _TYPES.get(spec.type)
    return registered is not None and registered[1](a, b, spec)


def _list(raw: Raw, item: FieldSpec, ctx: Context) -> NormalizeResult:
    """SPEC-04 §4.4: `Ok` with the items that normalize, the others dropped and reported; with none, the list
    declines. A single value stands for a list of one (JSON-LD 1.1 §4.3.1: a value and an array of it are the same)."""
    items = raw if isinstance(raw, list) else [raw]
    if not items:
        return Invalid("empty")
    values: list[JsonValue] = []
    reasons: list[str] = []
    ambiguous = False
    for i, entry in enumerate(items):
        result = normalize(entry, item, ctx)
        if isinstance(result, Ok):
            values.append(result.value)
            reasons.extend(_nested(f"[{i}]", result.reasons))
        else:
            ambiguous = ambiguous or isinstance(result, Ambiguous)
            reasons.append(f"[{i}]: {result.reason}")
    if values:
        return Ok(values, tuple(reasons))
    # No item normalized; an ambiguous one might, once the context settles it.
    return Ambiguous("no_item", ()) if ambiguous else Invalid("no_item")


def _object(raw: Raw, fields: dict[str, FieldSpec], ctx: Context) -> NormalizeResult:
    """SPEC-04 §4.4: `Ok` when every required sub-field normalizes; an optional one that declines is dropped and
    reported. Keys the schema does not name are ignored (a structured source carries `@type` and more), and a JSON
    `null` is no value (JSON-LD 1.1 §4.1.4)."""
    if not isinstance(raw, dict):
        return Invalid("not_an_object")
    value: dict[str, JsonValue] = {}
    reasons: list[str] = []
    for name, sub in fields.items():
        entry = raw.get(name)
        result = Invalid("missing") if entry is None else normalize(entry, sub, ctx)
        if isinstance(result, Ok):
            value[name] = result.value
            reasons.extend(_nested(name, result.reasons))
        elif sub.required:
            reason = f"{name}: {result.reason}"
            return Ambiguous(reason, ()) if isinstance(result, Ambiguous) else Invalid(reason)
        elif entry is not None:
            reasons.append(f"{name}: {result.reason}")
    if not value:
        return Invalid("empty")
    return Ok(value, tuple(reasons))


def _nested(path: str, reasons: tuple[str, ...]) -> Iterator[str]:
    # A nested reason's path continues its parent's: `[0]` and `name: x` give `[0].name: x`; `[0]` and `[1]: x` give
    # `[0][1]: x`.
    return (f"{path}{'' if reason.startswith('[') else '.'}{reason}" for reason in reasons)


def _multiset_equal(a: Sequence[JsonValue], b: Sequence[JsonValue], item: FieldSpec) -> bool:
    """Whether the items pair up one to one under item equality: a perfect bipartite matching, found by augmenting
    paths (Kuhn's algorithm). Pairing greedily is not enough, because location equality is not transitive."""
    if len(a) != len(b):
        return False
    candidates = [[j for j, y in enumerate(b) if equal(x, y, item)] for x in a]
    owner: list[int | None] = [None] * len(b)

    def augment(i: int, visited: set[int]) -> bool:
        for j in candidates[i]:
            if j in visited:
                continue
            visited.add(j)
            held = owner[j]
            if held is None or augment(held, visited):
                owner[j] = i
                return True
        return False

    return all(augment(i, set()) for i in range(len(a)))


def _item(spec: FieldSpec) -> FieldSpec:
    if spec.item is None:
        raise TypeError("a list spec has an item")
    return spec.item


def _fields(spec: FieldSpec) -> dict[str, FieldSpec]:
    if spec.fields is None:
        raise TypeError("an object spec has fields")
    return spec.fields
