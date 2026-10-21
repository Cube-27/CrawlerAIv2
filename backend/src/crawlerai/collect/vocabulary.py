"""The schema.org vocabulary (schemas spec): the type hierarchy, the properties and their sub-properties, and the
enumeration members of the pinned schema.org vocabulary file, and the check of a schema document's `schema_org` paths
and `schema:` references against it.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from pydantic import JsonValue

from crawlerai.core.engine_version import engine_data_dir
from crawlerai.schemas.paths import MappedPath, parse_paths
from crawlerai.schemas.types import FieldSpec

# The pinned schema.org release in `backend/data/manifest.json` (schemas spec, D-0018).
VOCABULARY_FILE = Path("schemaorg") / "schemaorg-all-https.jsonld"

# The vocabulary file's compact IRIs: `schema:` is https://schema.org/, `rdfs:Class` the RDF Schema class of classes.
_SCHEMA_PREFIX = "schema:"
_RDFS_CLASS = "rdfs:Class"
_SUB_CLASS_OF = "rdfs:subClassOf"
# RDF Schema: `rdf:Property` is the class of properties, `rdfs:subPropertyOf` relates a property to a broader one.
_RDF_PROPERTY = "rdf:Property"
_SUB_PROPERTY_OF = "rdfs:subPropertyOf"
# schema.org `identifier`: "The identifier property represents any kind of identifier for any kind of Thing".
IDENTIFIER = "identifier"
# schema.org namespaces: https is current, http the earlier one; the vocabulary treats both as the same terms.
NAMESPACES = ("https://schema.org/", "http://schema.org/")


def schema_term(iri: str) -> str | None:
    """The schema.org term an IRI names in either namespace (`http://schema.org/Product` is `Product`), else `None`."""
    return next((iri.removeprefix(n) for n in NAMESPACES if iri.startswith(n)), None)


class VocabularyMissing(RuntimeError):
    """The schema.org vocabulary file is not in the data directory: a deployment error, not bad input."""


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """The schema.org types, each with itself and every type it is a subclass of, transitively; each property's
    sub-properties, transitively (`narrower`), among them the properties that identify a thing (`identifier` and
    its sub-properties: `sku`, `gtin13`); the names of all properties; and the named instances of its types, an
    enumeration's members (`SalePrice`)."""

    supertypes: Mapping[str, frozenset[str]]
    narrower: Mapping[str, frozenset[str]] = field(default_factory=dict)
    properties: frozenset[str] = frozenset()
    members: frozenset[str] = frozenset()

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
        broader: dict[str, frozenset[str]] = {}
        members: set[str] = set()
        for node in graph:
            if not isinstance(node, dict):
                continue
            if (name := _term_name(node, _RDFS_CLASS)) is not None:
                parents[name] = frozenset(_schema_names(node.get(_SUB_CLASS_OF)))
            elif (name := _term_name(node, _RDF_PROPERTY)) is not None:
                broader[name] = frozenset(_schema_names(node.get(_SUB_PROPERTY_OF)))
            elif (name := _member_name(node)) is not None:
                members.add(name)
        narrower: dict[str, set[str]] = {}
        for name in broader:
            for ancestor in _ancestors(name, broader) - {name}:
                narrower.setdefault(ancestor, set()).add(name)
        return cls(
            {name: _ancestors(name, parents) for name in parents},
            {name: frozenset(names) for name, names in narrower.items()},
            frozenset(broader),
            frozenset(members),
        )

    @property
    def identifiers(self) -> frozenset[str]:
        return self.sub_properties(IDENTIFIER) | {IDENTIFIER}

    def __contains__(self, type_: object) -> bool:
        return type_ in self.supertypes

    def is_a(self, type_: str, ancestor: str) -> bool:
        return ancestor in self.supertypes.get(type_, frozenset())

    def sub_properties(self, prop: str) -> frozenset[str]:
        return self.narrower.get(prop, frozenset())

    def specific_first(self, names: Sequence[str]) -> tuple[str, ...]:
        """The vocabulary's types among `names`, each once, most specific first: a type that another listed type is a
        subtype of follows it."""
        known = list(dict.fromkeys(name for name in names if name in self))
        # By how many listed types are subtypes of each: a supertype of two listed types follows a supertype of one.
        return tuple(sorted(known, key=lambda t: sum(o != t and self.is_a(o, t) for o in known)))


# schema.org: "An Enumeration is a type whose members are named instances of it" (`schema:Enumeration`).
_ENUMERATION = "Enumeration"


def reference_errors(fields: Mapping[str, FieldSpec], vocabulary: Vocabulary) -> list[tuple[str, str]]:
    """The `schema_org` paths and `schema:` enum references of a schema document's `fields` that the pinned schema.org
    vocabulary does not define, as (field path, reason) pairs (schemas spec). A path's root must be a type, each step,
    predicate and `+` join a property and a predicate's value a member or type; a `schema:` reference must be an
    enumeration. `type:` references name the shipped type vocabularies, which the normalizer declines on when unknown
    (`unknown_vocab`)."""
    errors: list[tuple[str, str]] = []
    for name, spec in fields.items():
        _reference_errors(f"fields.{name}", spec, vocabulary, errors)
    return errors


def _reference_errors(path: str, spec: FieldSpec, vocabulary: Vocabulary, errors: list[tuple[str, str]]) -> None:
    if spec.schema_org is not None:
        errors.extend((f"{path}.schema_org", reason) for reason in _path_problems(spec.schema_org, vocabulary))
    if spec.vocab is not None and spec.vocab.startswith("schema:"):
        enumeration = spec.vocab.removeprefix("schema:")
        if not vocabulary.is_a(enumeration, _ENUMERATION) or enumeration == _ENUMERATION:
            errors.append((f"{path}.vocab", f"{enumeration} is not a schema.org enumeration"))
    if spec.item is not None:
        _reference_errors(f"{path}.item", spec.item, vocabulary, errors)
    for sub_name, sub in (spec.fields or {}).items():
        _reference_errors(f"{path}.fields.{sub_name}", sub, vocabulary, errors)


def _path_problems(schema_org: str, vocabulary: Vocabulary) -> list[str]:
    return [
        problem for alternative in parse_paths(schema_org) for problem in _alternative_problems(alternative, vocabulary)
    ]


def _alternative_problems(path: MappedPath, vocabulary: Vocabulary) -> Iterator[str]:
    if path.root not in vocabulary:
        yield f"{path.root} is not a schema.org type"
    predicates = [p for filters in path.filters for p in filters]
    for prop in dict.fromkeys((*path.steps, *(p.name for p in predicates), *path.joined)):
        if prop not in vocabulary.properties:
            yield f"{prop} is not a schema.org property"
    for value in dict.fromkeys(p.value for p in predicates if p.value is not None):
        if value not in vocabulary.members and value not in vocabulary:
            yield f"{value} is not a schema.org enumeration member or type"


def pinned_reference_errors(fields: Mapping[str, FieldSpec]) -> list[tuple[str, str]]:
    """`reference_errors` against the pinned vocabulary (`default_vocabulary`), for every path that stores a schema
    (schemas spec, "schema.org paths"). A process without the vocabulary file checks syntax only, as it extracts no
    records (`load_engine_data`)."""
    try:
        vocabulary = default_vocabulary()
    except VocabularyMissing:
        return []
    return reference_errors(fields, vocabulary)


@cache
def default_vocabulary() -> Vocabulary:
    """The vocabulary from the engine directory's `data/`, read once."""
    data = engine_data_dir()
    if data is None:
        raise VocabularyMissing("no engine directory: the schema.org vocabulary is read from its data/")
    return Vocabulary.read(data / VOCABULARY_FILE)


def _term_name(node: Mapping[str, JsonValue], kind: str) -> str | None:
    """The schema.org term a vocabulary node defines when it is typed `kind` (`rdfs:Class`, `rdf:Property`)."""
    types = node.get("@type")
    is_kind = types == kind or (isinstance(types, list) and kind in types)
    node_id = node.get("@id")
    if is_kind and isinstance(node_id, str) and node_id.startswith(_SCHEMA_PREFIX):
        return node_id.removeprefix(_SCHEMA_PREFIX)
    return None


def _member_name(node: Mapping[str, JsonValue]) -> str | None:
    """The schema.org term a vocabulary node names as an instance of a schema.org type (`schema:SalePrice`, typed
    `schema:PriceTypeEnumeration`)."""
    types = node.get("@type")
    node_id = node.get("@id")
    listed = types if isinstance(types, list) else [types]
    typed = any(isinstance(t, str) and t.startswith(_SCHEMA_PREFIX) for t in listed)
    if typed and isinstance(node_id, str) and node_id.startswith(_SCHEMA_PREFIX):
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
