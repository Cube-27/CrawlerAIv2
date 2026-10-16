"""The enum normalizer and the vocabulary framework (SPEC-04 §4.4, ARCHITECTURE §9): schema.org members by IRI or
name, language-tagged type vocabularies by token sequence (never substring order), and declines on no match, two
members, and empty input (INV-06)."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from crawlerai.normalize import enum, vocab
from crawlerai.normalize.base import Ambiguous, Context, Invalid, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
SCHEMA = FieldSpec(type=FieldType.ENUM, vocab="schema:ItemAvailability")
TYPE = FieldSpec(type=FieldType.ENUM, vocab="type:availability")

# schema.org ItemAvailability, as the standard lists its members.
MEMBERS = (
    "BackOrder",
    "Discontinued",
    "InStock",
    "InStoreOnly",
    "LimitedAvailability",
    "MadeToOrder",
    "OnlineOnly",
    "OutOfStock",
    "PreOrder",
    "PreSale",
    "Reserved",
    "SoldOut",
)

_members = st.sampled_from(MEMBERS)
_whitespace = st.text(alphabet=st.characters(categories=["Zs", "Cc"]).filter(str.isspace), max_size=8)
# Words that are no availability phrase and hold no part of one, so they cannot complete or split an entry.
_filler = st.lists(st.sampled_from(["the", "item", "is", "now", "very", "red", "size"]), max_size=4).map(" ".join)
# What may follow a member phrase without joining its first clause: punctuation, a digit, a line break.
_rest = st.sampled_from(["", ".", " (5 available)", "\nShips today", ": 3", " 7", "!"])


def _phrase(member: str) -> str:
    # De-camel-casing, as SPEC-04 §4.4 builds the `type:availability` en entries.
    return " ".join(re.findall(r"[A-Z][a-z]*", member)).lower()


# Schema vocabularies


@given(_members, st.sampled_from(["https://schema.org/{}", "http://schema.org/{}", "schema:{}", "{}"]), _whitespace)
def test_a_schema_member_matches_by_iri_or_name(member: str, form: str, pad: str) -> None:
    assert enum.normalize(pad + form.format(member) + pad, SCHEMA, CTX) == Ok(member)


@given(_members)
def test_a_json_ld_node_reference_to_a_member_matches(member: str) -> None:
    assert enum.normalize({"@id": f"https://schema.org/{member}"}, SCHEMA, CTX) == Ok(member)


@pytest.mark.parametrize(
    "raw",
    ["https://schema.org/Instock", "https://schema.org/Product", "https://example.test/InStock", "red", "available"],
)
def test_a_name_that_is_no_member_is_invalid(raw: str) -> None:
    assert enum.normalize(raw, SCHEMA, CTX) == Invalid("not_a_member")


@given(_members, _whitespace, _rest)
def test_text_opening_with_a_member_phrase_matches_through_the_vocabulary_of_its_members(
    member: str, pad: str, rest: str
) -> None:
    # Page text ("In stock") names no member, but `type:availability` maps phrases to ItemAvailability members. The
    # phrase is the text's whole first clause; what follows a punctuation mark, a digit or a line break is not read.
    assert enum.normalize(f"{pad}{_phrase(member).title()}{rest}", SCHEMA, CTX) == Ok(member)


@given(_members, st.sampled_from([str, str.upper, str.lower]))
def test_a_member_name_written_in_any_case_matches(member: str, case: Callable[[str], str]) -> None:
    # schema.org member names, case folded, as the Open Graph `product:availability` values write them ("instock").
    assert enum.normalize(case(member), SCHEMA, CTX) == Ok(member)


def test_text_stating_two_members_is_ambiguous() -> None:
    assert enum.normalize("in stock, sold out", SCHEMA, CTX) == Ambiguous("several_members", ("InStock", "SoldOut"))


@pytest.mark.parametrize(
    "raw",
    [
        "Not in stock",
        "not in stock",
        "Currently in stock",
        "In stock soon",
        "Out of stock online",
        "5 in stock",
        "0 in stock",
        "Available",
        "in-stock-ish",
    ],
)
def test_a_phrase_that_does_not_make_up_the_first_clause_is_no_member(raw: str) -> None:
    # A word before or inside the clause qualifies or negates the phrase; no word list can tell which, so it declines.
    assert enum.normalize(raw, SCHEMA, CTX) == Invalid("not_a_member")
    assert enum.normalize(raw, TYPE, CTX) == Invalid("no_match")


@given(_members, _members, _filler)
def test_text_stating_another_member_after_the_first_clause_is_ambiguous(a: str, b: str, middle: str) -> None:
    assume(a != b)
    assume(not set(_phrase(a).split()) & set(_phrase(b).split()))

    result = enum.normalize(f"{_phrase(a)}. {middle} {_phrase(b)}", SCHEMA, CTX)

    assert result == Ambiguous("several_members", tuple(sorted((a, b))))


def test_text_on_a_page_in_a_language_without_phrases_is_no_member() -> None:
    ctx = CTX.model_copy(update={"html_lang": "xx"})

    assert enum.normalize("in stock", SCHEMA, ctx) == Invalid("not_a_member")


def test_an_iri_outside_schema_org_is_never_read_as_text() -> None:
    assert enum.normalize("https://example.test/in-stock", SCHEMA, CTX) == Invalid("not_a_member")


@pytest.mark.parametrize("raw", [3, None, ["InStock"], {"@id": 3}, {"@id": "InStock", "name": "x"}])
def test_a_schema_value_that_is_neither_a_string_nor_a_node_reference_is_invalid(raw: object) -> None:
    assert enum.normalize(raw, SCHEMA, CTX) == Invalid("not_a_string")  # type: ignore[arg-type]


# Type vocabularies


@given(_members, _rest)
def test_each_availability_phrase_matches_its_member_as_the_first_clause(member: str, rest: str) -> None:
    raw = f"{_phrase(member).upper()}{rest}"

    assert enum.normalize(raw, TYPE, CTX) == Ok(member)


@given(_members, st.sampled_from(["-", "_", "  ", "\u00a0", "\u2013"]))
def test_spaces_dashes_and_connectors_separate_the_tokens_of_one_clause(member: str, separator: str) -> None:
    raw = separator.join(_phrase(member).split())

    assert enum.normalize(raw, TYPE, CTX) == Ok(member)


@given(_members)
def test_a_phrase_written_without_separators_does_not_match(member: str) -> None:
    raw = _phrase(member).replace(" ", "")
    assume(" " in _phrase(member))

    assert enum.normalize(raw, TYPE, CTX) == Invalid("no_match")


@given(_members, _members, _filler)
def test_two_members_in_one_input_are_ambiguous(a: str, b: str, middle: str) -> None:
    assume(a != b)
    assume(not set(_phrase(a).split()) & set(_phrase(b).split()))

    result = enum.normalize(f"{_phrase(a)}, {middle} {_phrase(b)}", TYPE, CTX)

    assert result == Ambiguous("several_members", tuple(sorted((a, b))))


@given(_members, _filler)
def test_a_member_repeated_is_one_member(member: str, middle: str) -> None:
    assert enum.normalize(f"{_phrase(member)}; {middle} {_phrase(member)}", TYPE, CTX) == Ok(member)


@given(_whitespace)
def test_empty_input_is_invalid(raw: str) -> None:
    assert enum.normalize(raw, TYPE, CTX) == Invalid("empty")
    assert enum.normalize(raw, SCHEMA, CTX) == Invalid("empty")


def test_a_type_value_that_is_not_a_string_is_invalid() -> None:
    assert enum.normalize({"@id": "InStock"}, TYPE, CTX) == Invalid("not_a_string")


def test_a_lone_surrogate_is_invalid() -> None:
    assert enum.normalize("in \ud800 stock", TYPE, CTX) == Invalid("surrogate")


def test_compatibility_forms_and_case_fold_before_matching() -> None:
    # NFKC maps fullwidth letters (here "IN STOCK", U+FF29 and on) to ASCII, then casefold lowers them.
    fullwidth = "\uff29\uff2e \uff33\uff34\uff2f\uff23\uff2b"

    assert enum.normalize(fullwidth, TYPE, CTX) == Ok("InStock")


@pytest.mark.parametrize(("html_lang", "og_locale"), [("en-GB", None), (None, "en_US"), (" EN ", "en_GB")])
def test_a_page_in_the_vocabulary_language_matches(html_lang: str | None, og_locale: str | None) -> None:
    ctx = Context(captured_at=CTX.captured_at, html_lang=html_lang, og_locale=og_locale)

    assert enum.normalize("in stock", TYPE, ctx) == Ok("InStock")


def test_a_page_in_a_language_without_a_vocabulary_declines() -> None:
    ctx = Context(captured_at=CTX.captured_at, html_lang="xx")

    assert enum.normalize("in stock", TYPE, ctx) == Invalid("no_vocabulary_for_language")


@pytest.mark.parametrize("ref", ["type:nonexistent", "schema:NoSuchEnumeration"])
def test_an_unknown_vocabulary_declines(ref: str) -> None:
    spec = FieldSpec(type=FieldType.ENUM, vocab=ref)

    assert enum.normalize("InStock", spec, CTX) == Invalid("unknown_vocab")


def test_a_spec_of_another_type_is_a_programming_error() -> None:
    spec = FieldSpec(type=FieldType.TEXT)

    with pytest.raises(TypeError):
        enum.normalize("in stock", spec, CTX)


def test_the_dispatcher_sends_enum_to_the_enum_module() -> None:
    assert normalize("https://schema.org/SoldOut", SCHEMA, CTX) == Ok("SoldOut")


# The matcher, over generated vocabularies


_word = st.from_regex(r"[a-z]{2,6}", fullmatch=True)


@given(_word, _word, _word)
def test_a_shorter_entry_inside_a_longer_word_never_matches(prefix: str, stem: str, other: str) -> None:
    # "unavailable" must not match "available": tokens, never substrings.
    assume(other not in {stem, prefix + stem})
    entries = vocab.Entries.of({"A": [stem], "B": [other]})

    assert entries.find(vocab.tokens(prefix + stem)) == frozenset()


@given(_word, _word, _word)
def test_the_longest_entry_wins_over_an_entry_inside_it(a: str, b: str, c: str) -> None:
    assume(len({a, b, c}) == 3)
    entries = vocab.Entries.of({"SHORT": [f"{a} {b}"], "LONG": [f"{a} {b} {c}"]})

    assert entries.find(vocab.tokens(f"{a} {b} {c}")) == frozenset({"LONG"})
    assert entries.find(vocab.tokens(f"{a} {b}")) == frozenset({"SHORT"})


@given(_word, _word, _word)
def test_entries_at_separate_places_all_count(a: str, b: str, c: str) -> None:
    assume(len({a, b, c}) == 3)
    entries = vocab.Entries.of({"LONG": [f"{a} {b}"], "SHORT": [c]})

    assert entries.find(vocab.tokens(f"{c} {a} {b}")) == frozenset({"LONG", "SHORT"})


@pytest.mark.parametrize(
    ("codes", "error"),
    [
        ({"A": ["In-Stock"]}, "not in token form"),
        ({"A": [""]}, "not in token form"),
        ({"A": ["in stock"], "B": ["in stock"]}, "listed under two codes"),
    ],
)
def test_a_malformed_vocabulary_is_refused(codes: dict[str, list[str]], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        vocab.Entries.of(codes)


# The shipped data


def test_the_availability_vocabulary_is_the_de_camel_cased_item_availability_members() -> None:
    entries = vocab.type_vocabulary("availability")

    assert entries is not None
    assert set(entries) == {"en"}
    assert entries["en"].phrases == {_phrase(m): m for m in MEMBERS}
    assert vocab.schema_members("ItemAvailability") == frozenset(MEMBERS)


def test_every_vocabulary_directory_has_a_justification() -> None:
    # C4: each vocabulary file names its source next to it.
    root = Path(vocab.__file__).parent
    directories = {path.parent for path in root.rglob("*.json")}

    assert directories
    assert [d for d in directories if not (d / "JUSTIFICATION.md").is_file()] == []
