"""Location normalizer (SPEC-04 §4.4, ARCHITECTURE §9): `{text, locality, region, country, remote_flag}`.

A location publishes what the page states and nothing it does not: no place is looked up, completed or inferred.
- `text` is the place as the page writes it: a string, a `Place`'s `name`, or a `PostalAddress`'s stated parts
  joined in the order locality, region, country. Nothing in it is parsed: several places, regions or alternatives
  ("A or B") stay one text as written (owner, 2026-10-16).
- `locality`, `region` are a `PostalAddress`'s `addressLocality` and `addressRegion` as written.
- `country` is an ISO 3166-1 alpha-2 code, and only when `addressCountry` states one (schema.org recommends the
  alpha-2 code). A country stated by name stays in `text`; no code is derived from it.
- `remote_flag` is `true` only from `jobLocationType` `TELECOMMUTE` or a `type:remote` phrase, never from a missing
  location. No standard states "not remote" as a flag, so it is `None` when the input does not say.

Each is `None` when the input does not state it. Accepted input: a string, or a schema.org
`PostalAddress`, or a `Place` holding one under `address` or naming itself in `name`, with `jobLocationType` beside
them. Declines: input stating nothing is `Invalid("no_match")`; an `addressCountry` written as two letters that are
no ISO 3166-1 code is `Invalid("unknown_country")`.
"""

import unicodedata
from collections.abc import Callable, Mapping
from functools import cache

from babel import Locale
from pydantic import JsonValue

from crawlerai.normalize import vocab
from crawlerai.normalize.base import Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate
from crawlerai.schemas.types import FieldSpec, FieldType

# schema.org `jobLocationType`: "TELECOMMUTE for telecommute jobs"; JSON-LD may write it as a schema.org IRI or a
# compact IRI (JSON-LD 1.1 §4.1.5).
_TELECOMMUTE = frozenset(
    {"TELECOMMUTE", "https://schema.org/TELECOMMUTE", "http://schema.org/TELECOMMUTE", "schema:TELECOMMUTE"}
)

# The keys of a normalized location (the module docstring).
_VALUE_KEYS = frozenset({"text", "locality", "region", "country", "remote_flag"})
_PARTS = ("locality", "region", "country")


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize a location (SPEC-04 §4.4)."""
    if spec.type is not FieldType.LOCATION:
        raise TypeError(f"the location normalizer does not handle type {spec.type}")
    if isinstance(raw, str):
        return _text(raw, ctx)
    if isinstance(raw, dict):
        return _structured(raw, ctx)
    return Invalid("not_a_location")


def equal(a: JsonValue, b: JsonValue, _spec: FieldSpec) -> bool:
    """SPEC-04 §4.5: `remote_flag` and `country` equal, `locality` equal after Unicode case folding; `region` and
    `text` (by `vocab.tokens`, so case, accents of form and punctuation don't count) count only when both values have
    one. Not transitive: a value without a region equals two values in different regions."""
    if a == b:
        return True
    if not (isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys() == _VALUE_KEYS):
        return False
    return (
        a["remote_flag"] == b["remote_flag"]
        and a["country"] == b["country"]
        and _casefolded(a["locality"]) == _casefolded(b["locality"])
        and _either_missing_or(a["region"], b["region"], _casefolded)
        and _either_missing_or(a["text"], b["text"], _tokens)
    )


def _either_missing_or(a: JsonValue, b: JsonValue, key: Callable[[JsonValue], JsonValue]) -> bool:
    return a is None or b is None or key(a) == key(b)


def _casefolded(value: JsonValue) -> JsonValue:
    return value.casefold() if isinstance(value, str) else value


def _tokens(value: JsonValue) -> JsonValue:
    return list(vocab.tokens(value)) if isinstance(value, str) else value


def _value(text: str | None, parts: Mapping[str, str | None], remote: bool) -> dict[str, JsonValue]:
    # Tri-state: `true` when stated, else `None`: a page that does not say is not a page that says "not remote".
    return {"text": text, **{name: parts.get(name) for name in _PARTS}, "remote_flag": True if remote else None}


def _text(given: str, ctx: Context, *, remote: bool = False) -> NormalizeResult:
    if has_surrogate(given):
        return Invalid("surrogate")
    text = _part(given)
    words = vocab.tokens(text or "")
    if text is None or not words:
        return Invalid("empty")
    return Ok(_value(text, {}, remote or _says_remote(text, ctx)))


def _telecommute(value: JsonValue) -> bool:
    """Whether a `jobLocationType` value is TELECOMMUTE. JSON-LD 1.1 lets a property hold an array of values (§4.3)
    or a node object naming its IRI in `@id` (§4.1); any one TELECOMMUTE value makes the job remote."""
    if isinstance(value, list):
        return any(_telecommute(item) for item in value)
    if isinstance(value, dict):
        value = value.get("@id")
    return isinstance(value, str) and value in _TELECOMMUTE


def _says_remote(text: str, ctx: Context) -> bool:
    # A phrase is stated only as a whole clause ("Lakeside, Remote"): "not remote" has other words in its clause, and
    # no standard lists the words that negate (C4, C7), so it states nothing (INV-37's rule, D-1272).
    entries = vocab.entries_for(vocab.type_vocabulary("remote") or {}, vocab.context_languages(ctx))
    return bool(vocab.clause_codes(text, entries))


def _structured(raw: Mapping[str, JsonValue], ctx: Context) -> NormalizeResult:
    # schema.org: `Place.address` is a PostalAddress (or text); `JobPosting.jobLocationType` is beside the location.
    remote = _telecommute(raw.get("jobLocationType"))
    address = raw.get("address", raw)
    if isinstance(address, str):
        address = {"name": address}
    if not isinstance(address, dict):
        return Invalid("not_a_location")
    country_written = _country_written(address.get("addressCountry"))
    parts = {
        "locality": _part(address.get("addressLocality")),
        "region": _part(address.get("addressRegion")),
        "country": None,
    }
    if country_written is not None and _looks_like_a_code(country_written):
        if country_written.upper() not in iso_3166_alpha2():
            return Invalid("unknown_country")
        parts["country"] = country_written.upper()
    stated = [p for p in (parts["locality"], parts["region"], country_written) if p]
    if stated:
        return Ok(_value(", ".join(stated), parts, remote))
    if name := _part(raw.get("name")) or _part(address.get("name")):
        return _text(name, ctx, remote=remote)
    return Ok(_value(None, parts, remote)) if remote else Invalid("no_match")


def _country_written(given: JsonValue) -> str | None:
    """`addressCountry` as the page writes it: schema.org allows text or a `Country`, which states itself by its
    `identifier` or `name`."""
    if isinstance(given, dict):
        given = given.get("identifier") or given.get("name")
    return _part(given)


def _looks_like_a_code(written: str) -> bool:
    # ISO 3166-1 alpha-2: two letters of the basic Latin alphabet.
    return len(written) == 2 and written.isascii() and written.isalpha()


def _part(given: JsonValue) -> str | None:
    """A stated part as written: NFC, with each run of whitespace (`str.isspace`) one space."""
    if not isinstance(given, str):
        return None
    return " ".join(unicodedata.normalize("NFC", given).split()) or None


# ISO 3166-1 "exceptional reservations" (the standard's list of codes reserved at a body's request, which the
# standard does not assign to a country): CLDR names regions by some of them.
_EXCEPTIONALLY_RESERVED = frozenset({"AC", "CP", "CQ", "DG", "EA", "EU", "EZ", "FX", "IC", "SU", "TA", "UK", "UN"})


@cache
def iso_3166_alpha2() -> frozenset[str]:
    """The ISO 3166-1 alpha-2 codes CLDR names regions by (via Babel), less the ranges ISO 3166-1 leaves to users
    (AA, QM to QZ, XA to XZ, ZZ) and its exceptional reservations (EU, EZ, UN, ...), which name no country."""
    return frozenset(
        code
        for code in Locale("en").territories
        if isinstance(code, str)
        and _looks_like_a_code(code)
        and code not in _EXCEPTIONALLY_RESERVED
        and not (code in {"AA", "ZZ"} or code[0] == "X" or ("QM" <= code <= "QZ"))
    )
