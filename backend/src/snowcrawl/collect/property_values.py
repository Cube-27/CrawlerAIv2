"""Label-value pairs of structured data: a schema.org `PropertyValue` names a
value by a label, its `name` or its `propertyID`, and states it as its `value`. Under an entity's
`additionalProperty` ("a property-value pair representing an additional characteristic of the entity") or its
`identifier`, a pair whose label is one of a field's labels (`collect.labels`) gives that field the pair's value, owned
by that entity: a related item's pairs stay that item's, so resolution never gives them to the page's item.
"""

from collections.abc import Iterator, Mapping, Sequence

from snowcrawl.collect.base import Candidate
from snowcrawl.collect.labels import Words, field_labels, words
from snowcrawl.collect.schema_org_map import Node, Typed, candidate
from snowcrawl.db.models import SourceKind
from snowcrawl.normalize.base import Context
from snowcrawl.schemas.types import SchemaDef

# schema.org: the properties of a Thing whose values are `PropertyValue`s, and a PropertyValue's label and value.
_HOLDERS = ("additionalProperty", "identifier")
_LABELS = ("name", "propertyID")
_VALUE = "value"


def labelled_values(
    entities: Sequence[Typed], schema: SchemaDef, ctx: Context, *, source_kind: SourceKind, diagnostics: list[str]
) -> Iterator[Candidate]:
    """A candidate per scalar `value` of each entity's property-value pairs that a field's label names."""
    labels = field_labels(schema)
    for entity, name, raw, locator in _labelled(entities, labels):
        found = candidate(name, schema.fields[name], entity, source_kind, raw, locator, ctx, diagnostics)
        if found is not None:
            yield found


def _labelled(
    entities: Sequence[Typed], labels: Mapping[Words, Sequence[str]]
) -> Iterator[tuple[str, str, str | int | float, str]]:
    """Each entity's id, a field its pair's label names, and the pair's value with its locator."""
    for entity in entities:
        for pair in _pairs(entity.node):
            names = dict.fromkeys(n for label in _label_texts(pair) for n in labels.get(words(label), ()))
            for raw, locator in _scalars(pair):
                yield from ((entity.id, name, raw, locator) for name in names)


def _pairs(node: Node) -> Iterator[Node]:
    for holder in _HOLDERS:
        yield from (value.node for value in node.values(holder) if value.node is not None)


def _label_texts(pair: Node) -> Iterator[str]:
    for prop in _LABELS:
        yield from (value.raw for value in pair.values(prop) if isinstance(value.raw, str))


def _scalars(pair: Node) -> Iterator[tuple[str | int | float, str]]:
    """The pair's values that are text or a number (a nested node is none), with their locators."""
    for value in pair.values(_VALUE):
        if value.node is None and isinstance(value.raw, str | int | float) and not isinstance(value.raw, bool):
            yield value.raw, value.locator
