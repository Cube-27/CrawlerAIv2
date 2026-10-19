"""The label vocabulary of a schema's fields (extraction spec, "Label vocabulary"): the words a page writes next to a
field's value, in a label-value pair of its markup or a `PropertyValue` of its structured data.

A field's labels are its name (`review_count`: "Review count"), the schema.org property its path names (`reviewCount`,
`brand` for `Product.brand.name`), the caller's description of it, and the synonyms role S drafted once for the schema
(`SchemaDef.labels`: cached with it, editable, in any language; `llm.roles.s_labels`). All of them come from the
schema, never from a phrase list in code (C4); without drafted synonyms the vocabulary is the schema's own words. A
label names a field when its words equal one of these, case-folded after NFKC.
"""

import re
import unicodedata

from crawlerai.schemas.paths import named_property, parse_paths
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# Words of a label or a name: runs of letters and digits; a lower-case letter or digit followed by a capital starts a
# new word, as schema.org's lowerCamelCase property names join theirs (schema.org, "Data model": naming conventions).
_WORD = re.compile(r"[^\W_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

Words = tuple[str, ...]


def labelled(spec: FieldSpec) -> bool:
    """Whether a label can name the field's value: an object holds several fields, and a label names one; a list of
    values (a page's tags, a job's places) is named by the label its items are written under, a list of lists or of
    objects by none."""
    if spec.type is FieldType.LIST:
        return spec.item is not None and spec.item.type not in (FieldType.LIST, FieldType.OBJECT)
    return spec.type is not FieldType.OBJECT


def field_labels(schema: SchemaDef) -> dict[Words, list[str]]:
    """The fields each label's words name."""
    drafted = schema.labels or {}
    labels: dict[Words, list[str]] = {}
    for name, spec in schema.fields.items():
        if not labelled(spec):
            continue
        texts = [name, *properties(spec), *([spec.description] if spec.description else []), *drafted.get(name, ())]
        for form in dict.fromkeys(form for form in map(words, texts) if form):
            labels.setdefault(form, []).append(name)
    return labels


def properties(spec: FieldSpec) -> list[str]:
    """The schema.org properties a field's paths name (`named_property`)."""
    return [named_property(p) for p in parse_paths(spec.schema_org)] if spec.schema_org is not None else []


def words(text: str) -> Words:
    """`text`'s words, case-folded, after Unicode NFKC (UAX #15): "Review count:", `review_count` and `reviewCount`
    are all ("review", "count")."""
    spaced = _CAMEL.sub(" ", unicodedata.normalize("NFKC", text))
    return tuple(word.casefold() for word in _WORD.findall(spaced))
