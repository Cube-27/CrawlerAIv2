"""The normalize dispatcher (SPEC-04 §4.3, §4.5): the entry points that send each field type to its one module (C8).

Callers (the resolver, eval, the API) normalize and compare through `normalize`, `equal` and `equality_key` and never
pick a type module themselves. `list` and `object` have no values of their own (§4.1), so all three recurse here into
their items and sub-fields.
"""

from collections import Counter
from collections.abc import Hashable, Iterator, Sequence
from functools import partial

from pydantic import JsonValue

from crawlerai.normalize import count, date, enum, identifier, location, money, number, text, url
from crawlerai.normalize import range as range_
from crawlerai.normalize.base import (
    Ambiguous,
    Context,
    Equality,
    EqualityKey,
    Invalid,
    Normalizer,
    NormalizeResult,
    Ok,
    Raw,
    raw_key,
)
from crawlerai.schemas.types import FieldSpec, FieldType

_MONEY = FieldSpec(type=FieldType.MONEY)


def _money(raw: Raw, ctx: Context) -> NormalizeResult:
    # A range resolves its currency by the money rules (SPEC-04 §4.4) through this registry, so range does not
    # import money (C8).
    return normalize(raw, _MONEY, ctx)


# The field-type registry: every §5.1 type with values of its own, with its normalizer and its equality. Equality is a
# key where it is an equivalence relation (two values are equal when their keys are); location's is not transitive (a
# place without a region equals two places in different regions), so two places are compared.
_TYPES: dict[FieldType, tuple[Normalizer, EqualityKey]] = {
    FieldType.TEXT: (text.normalize, text.key),
    FieldType.LONG_TEXT: (text.normalize, text.key),
    FieldType.ENUM: (enum.normalize, enum.key),
    FieldType.MONEY: (money.normalize, money.key),
    FieldType.URL: (url.normalize, url.key),
    FieldType.IDENTIFIER: (identifier.normalize, identifier.key),
    FieldType.IMAGE_URL: (url.normalize, url.key),
    FieldType.DATE: (date.normalize, date.key),
    FieldType.DATETIME: (date.normalize, date.key),
    FieldType.RANGE: (partial(range_.normalize, money=_money), range_.key),
    FieldType.COUNT: (count.normalize, count.key),
    FieldType.NUMBER: (number.normalize, number.key),
}
_COMPARED: dict[FieldType, tuple[Normalizer, Equality]] = {FieldType.LOCATION: (location.normalize, location.equal)}


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize `raw` as `spec`'s type. A type with no normalizer declines (§4.7), so a schema that names one
    cannot crash a job."""
    if spec.type is FieldType.LIST:
        return _list(raw, _item(spec), ctx)
    if spec.type is FieldType.OBJECT:
        return _object(raw, _fields(spec), ctx)
    registered = _TYPES.get(spec.type) or _COMPARED.get(spec.type)
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
    if (compared := _COMPARED.get(spec.type)) is not None:
        return compared[1](a, b, spec)
    key = equality_key(a, spec)
    return key is not None and key == equality_key(b, spec)


def equality_key(value: JsonValue, spec: FieldSpec) -> Hashable | None:
    """A hashable key of `value` under `spec`'s equality (`equal(a, b, spec)` exactly when the keys are equal), or
    `None` when that equality is no equivalence (it involves location, which is not transitive): values then group by
    hashing, not by comparing every pair. A list keys as the multiset of its items' keys, an object by its fields'."""
    if spec.type is FieldType.LIST:
        return _list_key(value, _item(spec)) if isinstance(value, list) else raw_key(value)
    if spec.type is FieldType.OBJECT:
        fields = _fields(spec)
        if not (isinstance(value, dict) and value.keys() <= fields.keys()):
            return raw_key(value)
        keys = {name: equality_key(v, fields[name]) for name, v in value.items()}
        return None if None in keys.values() else ("object", frozenset(keys.items()))
    if spec.type in _COMPARED:
        return None
    registered = _TYPES.get(spec.type)
    return raw_key(value) if registered is None else registered[1](value, spec)


def resource_key(value: JsonValue, spec: FieldSpec) -> Hashable | None:
    """The file an image_url value names, its scheme and query aside (`url.resource_key`: a query that varies how an
    image is served), and a list of images' files as a multiset (a list is a set of values, in no significant order,
    JSON-LD 1.1 §4.3.1); `None` for other types. A page URL's query often names a variant (SPEC-13), so url has
    none."""
    if spec.type is FieldType.LIST and isinstance(value, list):
        keys = [resource_key(item, _item(spec)) for item in value]
        return None if not keys or None in keys else ("resources", frozenset(Counter(keys).items()))
    return url.resource_key(value) if spec.type is FieldType.IMAGE_URL else None


def _list_key(items: list[JsonValue], item: FieldSpec) -> Hashable | None:
    keys = [equality_key(v, item) for v in items]
    return None if None in keys else ("list", frozenset(Counter(keys).items()))


# The types whose normalizer accepts only a grammar or a vocabulary, so arbitrary text declines: money (ISO 4217 and
# CLDR amounts), enum (a versioned vocabulary), date and datetime (ISO 8601, CLDR patterns) and range (amounts or
# quantities). Text and location accept any string; an object's sub-fields say nothing of one leaf.
_CHECKABLE = frozenset({FieldType.MONEY, FieldType.ENUM, FieldType.DATE, FieldType.DATETIME, FieldType.RANGE})


def checkable(raw: Raw, spec: FieldSpec) -> bool:
    """Whether `raw` normalizing as `spec`'s type would be evidence that it is a value of the type, because the type
    has a syntax its normalizer checks (ARCHITECTURE §8.1, SPEC-05 §4.5). An identifier qualifies only under a scheme
    with a check digit, a url only when `raw` is absolute (a relative reference resolves from any word), and a list
    as its item does."""
    if spec.type is FieldType.LIST:
        return checkable(raw, _item(spec))
    if spec.type is FieldType.IDENTIFIER:
        return identifier.has_check_digit(spec)
    if spec.type in (FieldType.URL, FieldType.IMAGE_URL):
        return url.is_absolute(raw)
    return spec.type in _CHECKABLE


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
