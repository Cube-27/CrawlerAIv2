"""Enum normalizer (SPEC-04 §4.4, ARCHITECTURE §9): a member code of the field's vocabulary.

- `schema:<Enumeration>`: the input is a string or a JSON-LD node reference (`{"@id": …}`) naming a member by IRI
  (`https://schema.org/InStock`, `http://schema.org/InStock`), compact IRI (`schema:InStock`) or name (`InStock`).
  The value is the member name. Other text, not an IRI, is read as the `type:` path reads it, against each type
  vocabulary whose codes are all members of the enumeration (`type:availability` for `ItemAvailability`), and a
  member name in any case also counts (`instock`), so a page that states "In stock (5 available)" gives `InStock`.
- `type:<name>`: the input is a string; it states a code when the tokens of its first clause are exactly one of the
  code's phrases (`crawlerai.normalize.vocab`), and no other code's phrase appears later in it. "Not in stock" states
  nothing (D-0782).

No match is `Invalid`; two members in one input are `Ambiguous`.
"""

import re
from collections.abc import Hashable, Mapping

from pydantic import JsonValue

from crawlerai.normalize import vocab
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate, raw_key
from crawlerai.schemas.types import FieldSpec, FieldType

# schema.org names its terms under https://schema.org/ and, earlier, http://schema.org/ (schema.org, "Data model");
# `schema:` is the prefix its JSON-LD context declares for compact IRIs (JSON-LD 1.1 §4.1.5).
_SCHEMA_PREFIXES = ("https://schema.org/", "http://schema.org/", "schema:")
# An absolute IRI starts with its scheme and a colon (RFC 3987 §2.2, RFC 3986 §3.1) and holds no white space; it names
# a resource, so it is never read as text.
_IRI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:\S*")


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize an enum field against its vocabulary (SPEC-04 §4.4). An unknown vocabulary declines, as an unknown
    type does (§4.7), so a schema that names one cannot crash a job."""
    if spec.type is not FieldType.ENUM or spec.vocab is None:
        raise TypeError(f"the enum normalizer does not handle type {spec.type} without a vocab")
    kind, name = spec.vocab.split(":", 1)
    if kind == "schema":
        return _schema_member(raw, name, ctx)
    return _type_code(raw, name, ctx)


def _schema_member(raw: Raw, enumeration: str, ctx: Context) -> NormalizeResult:
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
    member = name.removeprefix(prefix)
    if member in members:
        return Ok(member)
    if prefix or _IRI.fullmatch(name):
        return Invalid("not_a_member")
    return _stated_member(name, members, ctx)


def _stated_member(text: str, members: frozenset[str], ctx: Context) -> NormalizeResult:
    """The member that `text` states through the type vocabularies whose codes are all `members` (their phrases name
    members of this enumeration and nothing else, the structural property the match rests on), or by a member name
    in any case: `instock`, as Open Graph `product:availability` writes it."""
    entries = [e for v in vocab.type_vocabularies_within(members) for e in _page_entries(v, ctx)]
    return _one_code(vocab.stated_codes(text, [*entries, vocab.name_entries(members)]), "not_a_member")


def _type_code(raw: Raw, name: str, ctx: Context) -> NormalizeResult:
    by_language = vocab.type_vocabulary(name)
    if by_language is None:
        return Invalid("unknown_vocab")
    if not isinstance(raw, str):
        return Invalid("not_a_string")
    if has_surrogate(raw):
        return Invalid("surrogate")
    if not vocab.tokens(raw):
        return Invalid("empty")
    entries = _page_entries(by_language, ctx)
    if not entries:
        return Invalid("no_vocabulary_for_language")
    return _one_code(vocab.stated_codes(raw, entries), "no_match")


def _page_entries(by_language: Mapping[str, vocab.Entries], ctx: Context) -> list[vocab.Entries]:
    return vocab.entries_for(by_language, vocab.context_languages(ctx))


def _one_code(codes: frozenset[str], none: str) -> NormalizeResult:
    """The one code found; two or more are `Ambiguous`, none is `Invalid(none)`."""
    if not codes:
        return Invalid(none)
    if len(codes) > 1:
        return Ambiguous("several_members", tuple(sorted(codes)))
    return Ok(next(iter(codes)))


def key(value: JsonValue, _spec: FieldSpec) -> Hashable:
    """Equality as a key (SPEC-04 §4.5): exact. A normalized value has one form (one code per member)."""
    return raw_key(value)
