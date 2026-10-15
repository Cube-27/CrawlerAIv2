"""Enum normalizer (SPEC-04 §4.4, ARCHITECTURE §9): a member code of the field's vocabulary.

- `schema:<Enumeration>`: the input is a string or a JSON-LD node reference (`{"@id": …}`) naming a member by IRI
  (`https://schema.org/InStock`, `http://schema.org/InStock`), compact IRI (`schema:InStock`) or name (`InStock`).
  The value is the member name.
- `type:<name>`: the input is a string; a phrase of the vocabulary matches when its tokens are a contiguous run of
  the input's tokens (`crawlerai.normalize.vocab`). The value is the phrase's code.

No match is `Invalid`; two members in one input are `Ambiguous`.
"""

from collections.abc import Hashable

from pydantic import JsonValue

from crawlerai.normalize import vocab
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate, raw_key
from crawlerai.schemas.types import FieldSpec, FieldType

# schema.org names its terms under https://schema.org/ and, earlier, http://schema.org/ (schema.org, "Data model");
# `schema:` is the prefix its JSON-LD context declares for compact IRIs (JSON-LD 1.1 §4.1.5).
_SCHEMA_PREFIXES = ("https://schema.org/", "http://schema.org/", "schema:")


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize an enum field against its vocabulary (SPEC-04 §4.4). An unknown vocabulary declines, as an unknown
    type does (§4.7), so a schema that names one cannot crash a job."""
    if spec.type is not FieldType.ENUM or spec.vocab is None:
        raise TypeError(f"the enum normalizer does not handle type {spec.type} without a vocab")
    kind, name = spec.vocab.split(":", 1)
    if kind == "schema":
        return _schema_member(raw, name)
    return _type_code(raw, name, ctx)


def _schema_member(raw: Raw, enumeration: str) -> NormalizeResult:
    members = vocab.schema_members(enumeration)
    if members is None:
        return Invalid("unknown_vocab")
    # JSON-LD 1.1 §9.5: a node reference is a node object holding only `@id`.
    if isinstance(raw, dict) and raw.keys() == {"@id"}:
        raw = raw["@id"]
    if not isinstance(raw, str):
        return Invalid("not_a_string")
    # Surrounding white space is not part of an IRI (RFC 3987 §3.1 excludes it from the IRI syntax).
    name = raw.strip()
    if not name:
        return Invalid("empty")
    prefix = next((p for p in _SCHEMA_PREFIXES if name.startswith(p)), "")
    name = name.removeprefix(prefix)
    if name not in members:
        return Invalid("not_a_member")
    return Ok(name)


def _type_code(raw: Raw, name: str, ctx: Context) -> NormalizeResult:
    by_language = vocab.type_vocabulary(name)
    if by_language is None:
        return Invalid("unknown_vocab")
    if not isinstance(raw, str):
        return Invalid("not_a_string")
    if has_surrogate(raw):
        return Invalid("surrogate")
    words = vocab.tokens(raw)
    if not words:
        return Invalid("empty")
    codes = vocab.find_codes(by_language, words, ctx)
    if codes is None:
        return Invalid("no_vocabulary_for_language")
    if not codes:
        return Invalid("no_match")
    if len(codes) > 1:
        return Ambiguous("several_members", tuple(sorted(codes)))
    return Ok(next(iter(codes)))


def equal(a: JsonValue, b: JsonValue, _spec: FieldSpec) -> bool:
    """SPEC-04 §4.5: exact. A normalized value has one form (one code per member)."""
    return a == b


def key(value: JsonValue, _spec: FieldSpec) -> Hashable:
    return raw_key(value)  # equality is exact
