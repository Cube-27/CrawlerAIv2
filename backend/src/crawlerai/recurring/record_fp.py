"""Record fingerprints and changed fields (SPEC-11 §4.4, ARCHITECTURE §14 row 3, INV-10): what decides whether a
re-extracted entity is a new record version, and which of its fields changed. Both are pure functions of the records'
published values (`record.data`, ARCHITECTURE §6).

Values are compared as canonical JSON (RFC 8259 text with sorted object keys and no insignificant whitespace), the form
they are stored in: list order counts, object key order does not, and `true` is not `1`.
"""

import json
from collections.abc import Mapping

from pydantic import JsonValue

from crawlerai.schemas.types import SchemaDocument
from crawlerai.storage.capture_bundle import sha256_hex

__all__ = ["changed_fields", "record_fingerprint"]


def record_fingerprint(record_data: Mapping[str, JsonValue], schema: SchemaDocument) -> str:
    """`sha256(canonical_json(...))`, hex, over the published values of the schema's required fields and the members of
    its required groups: the fields that make a record complete (ARCHITECTURE §10). A field that did not publish is
    left out, so it differs from one that published `null`."""
    keyed = {name: record_data[name] for name in _fingerprinted(schema) if name in record_data}
    return sha256_hex(_canonical(keyed).encode())


def changed_fields(
    previous: Mapping[str, JsonValue], current: Mapping[str, JsonValue], schema: SchemaDocument
) -> list[str]:
    """The schema's fields, in schema order, whose published value differs between two versions of a record: a field
    that published a different value, or published in only one of them (it became published, or abstained or went
    missing)."""
    return [name for name in schema.fields if _published(previous, name) != _published(current, name)]


def _fingerprinted(schema: SchemaDocument) -> set[str]:
    required = {name for name, spec in schema.fields.items() if spec.required}
    return required.union(*schema.required_groups)


def _published(data: Mapping[str, JsonValue], name: str) -> str | None:
    return _canonical(data[name]) if name in data else None


def _canonical(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
