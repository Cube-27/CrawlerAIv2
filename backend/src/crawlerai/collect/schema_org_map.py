"""The schema.org map (SPEC-05 §4.1, §4.5), shared by the structured-data collectors (JSON-LD, microdata): the type
hierarchy from the pinned schema.org vocabulary file, and a schema field's `schema_org` path read against a node.

A path `T.p[.q][+r]` (SPEC-04 §4.2) applies to every entity of type `T` or a subtype of it (`rdfs:subClassOf`). It
follows `p`, then `q`, through the nodes the values name; `+r` joins the last node's `r` to the value as one object.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import NamedTuple, Protocol

from pydantic import JsonValue

from crawlerai.core.engine_version import backend_dir, data_dir

# The pinned schema.org release in `backend/data/manifest.json` (SPEC-04 §4.6, D-0018).
VOCABULARY_FILE = Path("schemaorg") / "schemaorg-all-https.jsonld"

# The vocabulary file's compact IRIs: `schema:` is https://schema.org/, `rdfs:Class` the RDF Schema class of classes.
_SCHEMA_PREFIX = "schema:"
_RDFS_CLASS = "rdfs:Class"
_SUB_CLASS_OF = "rdfs:subClassOf"


class VocabularyMissing(RuntimeError):
    """The schema.org vocabulary file is not in the data directory: a deployment error, not bad input."""


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """The schema.org types, each with itself and every type it is a subclass of, transitively."""

    supertypes: Mapping[str, frozenset[str]]

    @classmethod
    def read(cls, path: Path) -> "Vocabulary":
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise VocabularyMissing(f"{path}: missing; run `crawlerai data fetch`") from None
        return cls.parse(json.loads(text))

    @classmethod
    def parse(cls, document: JsonValue) -> "Vocabulary":
        """The types of a schema.org vocabulary file: the `@graph` nodes typed `rdfs:Class` with a `schema:` id."""
        if not isinstance(document, dict) or not isinstance(graph := document.get("@graph"), list):
            raise ValueError("a schema.org vocabulary file is a JSON-LD document with a @graph")
        parents: dict[str, frozenset[str]] = {}
        for node in graph:
            if isinstance(node, dict) and (name := _class_name(node)) is not None:
                parents[name] = frozenset(_schema_names(node.get(_SUB_CLASS_OF)))
        return cls({name: _ancestors(name, parents) for name in parents})

    def __contains__(self, type_: object) -> bool:
        return type_ in self.supertypes

    def is_a(self, type_: str, ancestor: str) -> bool:
        return ancestor in self.supertypes.get(type_, frozenset())


@cache
def default_vocabulary() -> Vocabulary:
    """The vocabulary from `backend/data/` of the source tree, read once."""
    backend = backend_dir(Path(__file__))
    if backend is None:
        raise VocabularyMissing("no backend source tree: the schema.org vocabulary is read from backend/data/")
    return Vocabulary.read(data_dir(backend) / VOCABULARY_FILE)


def _class_name(node: Mapping[str, JsonValue]) -> str | None:
    types = node.get("@type")
    is_class = types == _RDFS_CLASS or (isinstance(types, list) and _RDFS_CLASS in types)
    node_id = node.get("@id")
    if is_class and isinstance(node_id, str) and node_id.startswith(_SCHEMA_PREFIX):
        return node_id.removeprefix(_SCHEMA_PREFIX)
    return None


def _schema_names(references: JsonValue) -> list[str]:
    names = []
    for ref in references if isinstance(references, list) else [references]:
        ref_id = ref.get("@id") if isinstance(ref, dict) else None
        if isinstance(ref_id, str) and ref_id.startswith(_SCHEMA_PREFIX):
            names.append(ref_id.removeprefix(_SCHEMA_PREFIX))
    return names


def _ancestors(name: str, parents: Mapping[str, frozenset[str]]) -> frozenset[str]:
    seen = {name}
    pending = [name]
    while pending:
        for parent in parents.get(pending.pop(), frozenset()):
            if parent not in seen:
                seen.add(parent)
                pending.append(parent)
    return frozenset(seen)


class MappedPath(NamedTuple):
    root: str  # the type the path starts at
    steps: tuple[str, ...]  # the properties followed, the last one holding the value
    joined: str | None  # `+r`: a property of the last node joined to the value


def parse_path(path: str) -> MappedPath:
    """A `schema_org` path, already checked by the schema document's pattern (SPEC-04 §4.2)."""
    path, _, joined = path.partition("+")
    root, *steps = path.split(".")
    return MappedPath(root, tuple(steps), joined or None)


@dataclass(frozen=True, slots=True)
class Value:
    """One value of a property: `raw` as the page states it (a node's JSON object for a node), where it is, and the
    node when the value is one whose properties a path can follow."""

    raw: JsonValue
    locator: str
    node: "Node | None" = None


class Node(Protocol):
    """A structured-data node: a JSON-LD object, or a microdata item."""

    def values(self, prop: str) -> Sequence[Value]: ...


@dataclass(frozen=True, slots=True)
class Selected:
    raw: JsonValue
    locator: str


# schema.org data model ("Conformance"): where a property expects a Thing, a text value is accepted; the text names
# that thing. So a path ending in `.name` takes the text that stands in for the thing.
_NAME = ("name",)


def select(node: Node, path: MappedPath, *, as_list: bool) -> list[Selected]:
    """The values `path` (after its root type) reaches from `node`: those on nodes first, then text standing in for a
    named thing, each in document order. Each value is its own selection; for a list field (`as_list`), a node's values
    of the last property are one selection, located at the first value."""
    holders: list[Node] = [node]
    named: list[Selected] = []
    for i, step in enumerate(path.steps[:-1]):
        names_thing = path.steps[i + 1 :] == _NAME and path.joined is None
        reached: list[Node] = []
        for holder in holders:
            for value in holder.values(step):
                if value.node is not None:
                    reached.append(value.node)
                elif names_thing and isinstance(value.raw, str):
                    named.append(Selected(value.raw, value.locator))
        holders = reached
    selected = [s for holder in holders for s in _last(holder, path, as_list=as_list)]
    return selected + named


def _last(holder: Node, path: MappedPath, *, as_list: bool) -> list[Selected]:
    values = holder.values(path.steps[-1])
    if not values:
        return []
    if as_list:
        return [Selected([v.raw for v in values], values[0].locator)]
    if path.joined is None:
        return [Selected(v.raw, v.locator) for v in values]
    companions = [c.raw for c in holder.values(path.joined)]
    extra: dict[str, JsonValue] = {}
    if companions:
        extra[path.joined] = companions[0] if len(companions) == 1 else companions
    return [Selected({path.steps[-1]: v.raw} | extra, v.locator) for v in values]
