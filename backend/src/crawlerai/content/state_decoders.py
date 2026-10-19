"""Decoders of parsed state documents by their documented shape, never by a variable name (extraction spec, "Source
documents"): each turns a document written in a serializer's reference format into the tree it stands for.

- **devalue flat array** (devalue `stringify`, Nuxt 3's `__NUXT_DATA__` payload): an array whose element 0 is an
  object whose every value is an in-range index into the array after it, or a Nuxt reviver tuple naming such an
  element; every
  index is replaced by the element it names, typed elements by their revived value.
- **normalized-cache dereference** (Apollo Client `InMemoryCache`): an object whose every value is an object and that
  holds `{"__ref": "<key>"}` members; every `__ref` is replaced by the entry it names, `ROOT_QUERY` first.
- **Astro island props** (Astro's `serializeObject`): `[type, value]` tuples revived top-down.

Hostile input is bounded: a decoded tree deeper than `MAX_DEPTH` or larger than `MAX_NODES` leaves the document as
written; references on their own path (cycles) are not followed.
"""

import json
from collections.abc import Callable
from typing import Any

from pydantic import JsonValue

from crawlerai.content.js_literal import MAX_DEPTH, MAX_NODES

# Nuxt `revive-payload` plugin: reducers whose value is the wrapped value itself (a reactive or ref wrapper, an error's
# fields) and those whose value is JSON text (`_` for `undefined`).
_WRAPPERS = frozenset({"Reactive", "ShallowReactive", "Ref", "ShallowRef", "NuxtError"})
_EMPTY_REFS = frozenset({"EmptyRef", "EmptyShallowRef"})
# devalue: negative indices stand for values JSON cannot hold (`undefined`, a hole, NaN, ±Infinity); -0 is -6.
_NEGATIVE_ZERO = -6
# Apollo Client: the reference member of a normalized entity and the root query's cache ID.
_REF = "__ref"
_ROOT = "ROOT_QUERY"


class _TooLarge(Exception):
    pass


def decode(document: JsonValue) -> JsonValue:
    """`document` decoded by the first decoder whose shape it has (module docstring), else as it is."""
    decoder = _decoder(document)
    if decoder is None:
        return document
    try:
        return decoder(document)
    except _TooLarge:
        return document


def _decoder(document: JsonValue) -> Callable[[Any], JsonValue] | None:
    if isinstance(document, list) and _is_flat_array(document):
        return _Unflatten().document
    if isinstance(document, dict) and _is_normalized_cache(document):
        return _Dereference().document
    return None


def _index(value: JsonValue, size: int) -> int | None:
    """`value` when it is an index into an array of `size` elements."""
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < size else None


def _is_flat_array(values: list[JsonValue]) -> bool:
    """devalue numbers values in first-visit order, so the root object's members name elements after it."""
    at, root = 0, values[0] if values else None
    if isinstance(root, list) and len(root) == 2 and _is_wrapper(root[0]):
        wrapped = _index(root[1], len(values))
        if wrapped is not None:
            at, root = wrapped, values[wrapped]
    return isinstance(root, dict) and all((i := _index(v, len(values))) is not None and i > at for v in root.values())


def _is_wrapper(kind: JsonValue) -> bool:
    return isinstance(kind, str) and kind in _WRAPPERS


def _is_normalized_cache(document: dict[str, JsonValue]) -> bool:
    if not document or not all(isinstance(entry, dict) for entry in document.values()):
        return False
    stack: list[JsonValue] = list(document.values())
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if isinstance(node.get(_REF), str) and len(node) == 1:
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


class _Budget:
    def __init__(self) -> None:
        self.nodes = 0

    def spend(self, depth: int) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            raise _TooLarge


class _Unflatten(_Budget):
    """devalue `unflatten`, with Nuxt's revivers; values JSON cannot hold become `null`, a `Map` its `[key, value]`
    pairs, a `Set` its items, a `Date` its ISO string."""

    def document(self, values: list[JsonValue]) -> JsonValue:
        self.values = values
        return self._hydrate(0, 0, frozenset())

    def _hydrate(self, index: JsonValue, depth: int, path: frozenset[int]) -> JsonValue:
        self.spend(depth)
        if not isinstance(index, int) or isinstance(index, bool) or index >= len(self.values) or index in path:
            return None
        if index < 0:
            return -0.0 if index == _NEGATIVE_ZERO else None
        value = self.values[index]
        path = path | {index}
        if isinstance(value, dict):
            return {key: self._hydrate(member, depth + 1, path) for key, member in value.items()}
        if not isinstance(value, list):
            return value
        if value and isinstance(value[0], str):
            return self._revive(value[0], value[1:], depth, path)
        return [self._hydrate(item, depth + 1, path) for item in value]

    def _revive(self, kind: str, args: list[JsonValue], depth: int, path: frozenset[int]) -> JsonValue:
        """A typed element `[kind, ...args]`: devalue's built-in types and Nuxt's revivers; another kind is `null`."""
        if kind in _WRAPPERS and args:
            return self._hydrate(args[0], depth + 1, path)
        if kind in _EMPTY_REFS and args:
            return _json_or_text(self._hydrate(args[0], depth + 1, path))
        if kind in ("Date", "Object", "BigInt", "RegExp") and args:  # the written value (ISO string, number text)
            return args[0]
        if kind == "Set":
            return [self._hydrate(item, depth + 1, path) for item in args]
        if kind == "Map":
            pairs = zip(args[::2], args[1::2], strict=False)
            return [[self._hydrate(k, depth + 1, path), self._hydrate(v, depth + 1, path)] for k, v in pairs]
        if kind == "null":  # an object without prototype: `["null", key, index, ...]`
            return {str(k): self._hydrate(v, depth + 1, path) for k, v in zip(args[::2], args[1::2], strict=False)}
        return None


def _json_or_text(value: JsonValue) -> JsonValue:
    """Nuxt `EmptyRef`: `_` is `undefined`, other text is read as JSON when it is JSON (`destr`)."""
    if value == "_" or not isinstance(value, str):
        return None if value == "_" else value
    try:
        return json.loads(value)  # type: ignore[no-any-return]
    except ValueError:
        return value


class _Dereference(_Budget):
    """Every `{"__ref": key}` replaced by the entry `key` names, except on its own path."""

    def document(self, cache: dict[str, JsonValue]) -> JsonValue:
        self.cache = cache
        order = sorted(cache, key=lambda key: key != _ROOT)
        return {key: self._resolve(cache[key], 1, frozenset({key})) for key in order}

    def _resolve(self, node: JsonValue, depth: int, path: frozenset[str]) -> JsonValue:
        self.spend(depth)
        if isinstance(node, list):
            return [self._resolve(item, depth + 1, path) for item in node]
        if not isinstance(node, dict):
            return node
        key = node.get(_REF)
        if len(node) == 1 and isinstance(key, str) and key in self.cache and key not in path:
            return self._resolve(self.cache[key], depth + 1, path | {key})
        return {name: self._resolve(member, depth + 1, path) for name, member in node.items()}


# Astro `serializeObject` PROP_TYPE: 0 value, 1 JSON array, 2 RegExp, 3 Date, 4 Map, 5 Set, 6 BigInt, 7 URL,
# 8-10 typed arrays, 11 ±Infinity; the items of 1, 4 and 5 are tuples themselves, those of 8-10 numbers.
_ASTRO_LAST_TYPE = 11
_ASTRO_TUPLE_ARRAYS = frozenset({1, 4, 5})
_ASTRO_NUMBER_ARRAYS = frozenset({8, 9, 10})
_ASTRO_INFINITY = 11


def revive_astro_props(props: JsonValue) -> JsonValue | None:
    """Astro island props revived as Astro's client does (`astro-island.ts`), as JSON: a RegExp, Date, BigInt or URL
    is its written string, a Map its `[key, value]` pairs, a Set or typed array its items, `undefined` and ±Infinity
    `null`. None when `props` is not an object whose every value is a `[type, value]` tuple (type 0..11)."""
    if not isinstance(props, dict) or not props or not all(_is_astro_tuple(value) for value in props.values()):
        return None
    try:
        return _revive_object(props, 0, _Budget())
    except _TooLarge:
        return None


def _is_astro_tuple(value: JsonValue) -> bool:
    return isinstance(value, list) and 1 <= len(value) <= 2 and _index(value[0], _ASTRO_LAST_TYPE + 1) is not None


def _revive_tuple(raw: JsonValue, depth: int, budget: _Budget) -> JsonValue:
    budget.spend(depth)
    if not isinstance(raw, list) or len(raw) != 2 or not _is_astro_tuple(raw):
        return None  # Astro writes `undefined` as `[0]`
    kind, value = raw
    if kind == 0:
        return _revive_object(value, depth + 1, budget) if isinstance(value, dict) else value
    if kind in _ASTRO_TUPLE_ARRAYS and isinstance(value, list):
        return [_revive_tuple(item, depth + 1, budget) for item in value]
    if kind in _ASTRO_NUMBER_ARRAYS and isinstance(value, list):
        return value
    return None if kind == _ASTRO_INFINITY else value


def _revive_object(raw: dict[str, JsonValue], depth: int, budget: _Budget) -> JsonValue:
    return {key: _revive_tuple(value, depth + 1, budget) for key, value in raw.items()}
