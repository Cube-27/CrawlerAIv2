"""Preference (SPEC-05 §4.7, §4.8, ARCHITECTURE §8.2 rule 4, §10): which of a field's candidates publishes.

A candidate is kept when it normalized (validity), belongs to the target (ownership, §4.6) and is not a value taken
from the request URL's query (INV-13); every other one is rejected with its reason. Of the kept candidates, an
exact-match type publishes only when all agree (INV-14); text, long_text, url and image_url take the first source kind
of the type's order in `source_precedence.yaml`. A page's Offer fields come from one Offer (INV-15).

On a detail page (SPEC-13 §4.6), a variant the page URLs select is the only source of the Offer fields: other
holders' Offers are rejected `other_variant` (INV-36). An identifier field the target states nothing for takes its
variants' value: the selected variant's, or, with none selected, the value every variant states alike.

Evidence buckets, confidence and τ are the next stage's (`resolve.evidence`); this module only chooses.
"""

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Literal, cast, get_args
from urllib.parse import parse_qsl, urlsplit

import yaml
from pydantic import JsonValue

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.json_doc import scalars
from crawlerai.collect.schema_org_map import parse_paths
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Ambiguous, Invalid, Ok, Raw
from crawlerai.normalize.dispatch import equal, resource_key
from crawlerai.normalize.text import text_form
from crawlerai.resolve.ownership import OFFER, VARIANT, EntityGraph
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PRECEDENCE_FILE = "source_precedence.yaml"
# ARCHITECTURE §10: the types whose candidates rank by source kind; every other type publishes only on agreement.
PRECEDENCE_TYPES = frozenset({FieldType.TEXT, FieldType.LONG_TEXT, FieldType.URL, FieldType.IMAGE_URL})
# What `crawlerai eval fit-precedence` stamps on the file (INV-02); every other key names a field type.
STAMP = frozenset({"source_split", "eval_run_id", "git_sha"})
_SOURCE_KINDS: frozenset[str] = frozenset(get_args(SourceKind))
# The screening stages in the order a candidate meets them; a missing field states the furthest one reached.
_STAGES = ("invalid", "ambiguous", "not_owned", "url_param", "other_variant")
# GS1 GTIN and a seller's SKU identify one product, so a variant's identifies the variant (SPEC-13 §4.6, variant fill).
_FILLED_SCHEMES = frozenset({"gtin", "sku"})

Orders = Mapping[FieldType, tuple[SourceKind, ...]]  # per precedence type, the source kinds, first wins
Rejection = tuple[Candidate, str]  # a candidate that does not publish, with its reason


@dataclass(frozen=True, slots=True)
class Chosen:
    """The field publishes `candidate`'s normalized value. `agreeing` are the other kept candidates equal to it;
    `kept` are all the candidates that passed screening, `candidate` included."""

    candidate: Candidate
    agreeing: tuple[Candidate, ...]
    rejected: tuple[Rejection, ...]
    kept: tuple[Candidate, ...]


@dataclass(frozen=True, slots=True)
class Unpublished:
    status: Literal["missing", "conflict"]
    reason: str
    rejected: tuple[Rejection, ...]
    kept: tuple[Candidate, ...] = ()  # the candidates that passed screening and still did not publish


Preference = Chosen | Unpublished


@dataclass(frozen=True, slots=True)
class PageFacts:
    """What the URL-parameter rule reads of the page: the request URL's query values, and whether a value is shown."""

    query_values: frozenset[str]
    visible: Callable[[str], bool]

    @classmethod
    def of(cls, request_url: str, visible: Callable[[str], bool]) -> "PageFacts":
        # WHATWG URL Standard, application/x-www-form-urlencoded parsing: `+` is a space, triplets decode.
        pairs = parse_qsl(urlsplit(request_url).query)
        return cls(frozenset(form for _, value in pairs if (form := text_form(value))), visible)


@dataclass(frozen=True, slots=True)
class Variants:
    """The variant rules of a detail page's target (SPEC-13 §4.6): `selected` is the variant holder the page URLs
    select (`select_variant` in `resolve/intent.py`), or None."""

    selected: Entity | None


@dataclass(frozen=True, slots=True)
class Resolver:
    """Preference for one entity, `target`: a detail page's target (§4.6), a listing's page or one of its rows (§4.7).
    Its fields' candidates are screened, then chosen per type. `page_values`: whether page-level candidates are the
    target's (`EntityGraph.owned_by`). `owns` stands in for ownership where the owner is not one entity: a variant's
    rows (SPEC-13 §4.5)."""

    graph: EntityGraph
    target: Entity
    page: PageFacts
    orders: Orders
    page_values: bool = True
    variants: Variants | None = None  # a detail page's target only (SPEC-13 §4.6)
    owns: Callable[[Candidate], bool] | None = None

    def prefer(self, schema: SchemaDef, candidates: Sequence[Candidate]) -> dict[str, Preference]:
        return self.prefer_fields(schema.fields, candidates)

    def prefer_fields(
        self, fields: Mapping[str, FieldSpec], candidates: Sequence[Candidate], *, prefix: str = ""
    ) -> dict[str, Preference]:
        """Every field's preference; a candidate is a field's when its field is `prefix` and the name (a row-mapped
        field's sub-fields are `<field>.<sub-field>`, SPEC-13 §4.2)."""
        by_field = {name: [c for c in candidates if c.field == f"{prefix}{name}"] for name in fields}
        screened = {name: self.screen(by_field[name]) for name in fields}
        # In schema order: the anchor takes the first Offer seen on a tie.
        offer_fields = [name for name, spec in fields.items() if self._is_offer_field(spec)]
        if self.variants is not None and self.variants.selected is not None:
            selected = self.graph.offers_of(self.variants.selected)
            screened |= {name: self._from_selected(*screened[name], selected) for name in offer_fields}
        anchor = self._anchor({name: screened[name][0] for name in offer_fields})
        chosen = {
            name: self._choose(spec, *screened[name], anchor=anchor if name in offer_fields else None)
            for name, spec in fields.items()
        }
        return {name: self._fill(spec, by_field[name], chosen[name]) for name, spec in fields.items()}

    def prefer_field(self, spec: FieldSpec, candidates: Sequence[Candidate]) -> Preference:
        """One field on its own, outside the page's Offer anchor: for values derived after preference (`derive`)."""
        return self._choose(spec, *self.screen(candidates), anchor=None)

    def screen(self, candidates: Sequence[Candidate]) -> tuple[list[Candidate], list[Rejection]]:
        """The candidates kept by validity, ownership and the URL-parameter rule, and the others with their reason."""
        kept: list[Candidate] = []
        rejected: list[Rejection] = []
        for candidate in candidates:
            reason = self._reject_reason(candidate)
            if reason is None:
                kept.append(candidate)
            else:
                rejected.append((candidate, reason))
        return kept, rejected

    def _reject_reason(self, candidate: Candidate) -> str | None:
        if isinstance(candidate.normalized, Invalid):
            return "invalid"
        if isinstance(candidate.normalized, Ambiguous):
            return "ambiguous"
        if not self._owned(candidate):
            return "not_owned"
        # §8.2 rule 4 (INV-13): a value the request URL carries is not evidence about the page unless the page shows it.
        if any(text_form(s) in self.page.query_values and not self.page.visible(s) for s in _scalars(candidate.raw)):
            return "url_param"
        return None

    def _owned(self, candidate: Candidate) -> bool:
        if self.owns is not None:
            return self.owns(candidate)
        return self.graph.owned_by(candidate, self.target, page_values=self.page_values)

    def _from_selected(
        self, kept: list[Candidate], rejected: list[Rejection], selected: frozenset[str]
    ) -> tuple[list[Candidate], list[Rejection]]:
        """INV-36: with a selected variant, an Offer field's Offer candidates come from the selected holder's Offers
        only; other holders' are `other_variant`."""
        others = [c for c in kept if (offer := self._offer_of(c)) is not None and offer not in selected]
        return _without(kept, others), [*rejected, *((c, "other_variant") for c in others)]

    def _fill(self, spec: FieldSpec, candidates: Sequence[Candidate], preference: Preference) -> Preference:
        """Variant fill (SPEC-13 §4.6): a gtin or sku field the target states nothing for (no candidate is the
        target's) takes the selected variant's candidates, or, with no variant selected, its variants' when every
        variant has one and all agree. A value the target states is never replaced, and no other field is filled."""
        if self.variants is None or spec.type is not FieldType.IDENTIFIER or spec.scheme not in _FILLED_SCHEMES:
            return preference
        if any(self.graph.owned_by(c, self.target, page_values=self.page_values) for c in candidates):
            return preference
        selected = self.variants.selected
        if selected is not None and selected.via == VARIANT:
            members: tuple[Entity, ...] = (selected,)
        else:
            members = self.graph.variants(self.target)
        pooled = [self._variant_kept(member, candidates) for member in members]
        if not pooled or not all(pooled):
            return preference
        kept = [c for member_kept in pooled for c in member_kept]
        rejected = [r for r in preference.rejected if not any(r[0] is c for c in kept)]
        filled = _by_agreement(spec, kept, kept[0], rejected)
        return filled if isinstance(filled, Chosen) else preference

    def _variant_kept(self, member: Entity, candidates: Sequence[Candidate]) -> list[Candidate]:
        """The candidates the variant `member` holds itself that pass screening, as they would for it as a target."""
        own = [c for c in candidates if c.entity_id == member.id]
        return Resolver(self.graph, member, self.page, self.orders, page_values=False).screen(own)[0]

    def _is_offer_field(self, spec: FieldSpec) -> bool:
        # A field whose `schema_org` path starts at Offer (or a subtype), in every alternative, holds a part of an
        # offer (§4.8).
        return spec.schema_org is not None and all(
            self.graph.vocabulary.is_a(path.root, OFFER) for path in parse_paths(spec.schema_org)
        )

    def _offer_of(self, candidate: Candidate) -> str | None:
        owner = self.graph.owner_of(candidate)
        return owner.id if self.graph.is_a(owner, OFFER) else None

    def _anchor(self, offer_fields: Mapping[str, Sequence[Candidate]]) -> str | None:
        """The Offer the page's offer fields come from (INV-15): the one holding kept candidates for the most of
        them, the first seen on a tie; `None` when no Offer holds any."""
        coverage: dict[str, int] = {}
        for kept in offer_fields.values():
            for offer in dict.fromkeys(o for c in kept if (o := self._offer_of(c)) is not None):
                coverage[offer] = coverage.get(offer, 0) + 1
        return max(coverage, key=coverage.__getitem__) if coverage else None

    def _choose(
        self, spec: FieldSpec, kept: list[Candidate], rejected: list[Rejection], *, anchor: str | None
    ) -> Preference:
        if not kept:
            return Unpublished("missing", _missing_reason(rejected), tuple(rejected))
        choosable = kept
        if anchor is not None:
            split = self._offer_split(spec, kept, anchor)
            if split is not None:
                return _all_rejected("conflict", split, kept, rejected)
            choosable = [c for c in kept if c.entity_id == anchor]
        if rule_type(spec) in PRECEDENCE_TYPES:
            return self._by_precedence(spec, kept, choosable, rejected)
        return _by_agreement(spec, kept, choosable[0], rejected)

    def _offer_split(self, spec: FieldSpec, kept: list[Candidate], anchor: str) -> str | None:
        """§4.8: several Offers publish a field only when all agree, and only from the anchor Offer."""
        offered = [c for c in kept if self._offer_of(c) is not None]
        if any(a.entity_id != b.entity_id and not _equal(a, b, spec) for a, b in combinations(offered, 2)):
            return "offers_disagree"
        if all(c.entity_id != anchor for c in kept):
            return "offer_split"
        return None

    def _by_precedence(
        self, spec: FieldSpec, kept: list[Candidate], choosable: list[Candidate], rejected: list[Rejection]
    ) -> Preference:
        order = self.orders[rule_type(spec)]
        # A kind outside the order is not ranked on dev, so it never wins; it can still agree.
        kind = next((k for k in order if any(c.source_kind == k for c in choosable)), None)
        if kind is None:
            return _all_rejected("missing", "unranked", kept, rejected)
        chosen = _winner(spec, kind, kept, choosable)
        if chosen is None:
            return _all_rejected("conflict", "disagree", kept, rejected)
        agreeing: list[Candidate] = []
        lower: list[Rejection] = []
        for c in kept:
            if c is chosen:
                continue
            if _equal(c, chosen, spec):
                agreeing.append(c)
            else:
                lower.append((c, "precedence"))
        return Chosen(chosen, tuple(agreeing), (*rejected, *lower), tuple(kept))


def intent_ambiguous(schema: SchemaDef, candidates: Sequence[Candidate]) -> dict[str, Preference]:
    """§4.6: with no single target, every field is a conflict and no candidate publishes."""
    return {
        name: Unpublished(
            "conflict", "intent_ambiguous", tuple((c, "intent_ambiguous") for c in candidates if c.field == name)
        )
        for name in schema.fields
    }


def _by_agreement(spec: FieldSpec, kept: list[Candidate], chosen: Candidate, rejected: list[Rejection]) -> Preference:
    # ARCHITECTURE §10, INV-14: exact-match values publish only when every kept candidate agrees.
    if not _all_agree(kept, spec):
        return _all_rejected("conflict", "disagree", kept, rejected)
    return Chosen(chosen, tuple(c for c in kept if c is not chosen), tuple(rejected), tuple(kept))


def _winner(spec: FieldSpec, kind: SourceKind, kept: list[Candidate], choosable: list[Candidate]) -> Candidate | None:
    """The candidate of the winning kind that publishes. Two values from that kind leave the order nothing to decide
    between (C7: decline, never guess), unless they are one entity's values and another kind names one of them."""
    winners = [c for c in kept if c.source_kind == kind]
    if _all_agree(winners, spec):
        return next(c for c in choosable if c.source_kind == kind)
    named = _named_member(spec, winners, kept)
    return named if named is not None and any(c is named for c in choosable) else None


def _named_member(spec: FieldSpec, members: list[Candidate], kept: list[Candidate]) -> Candidate | None:
    """The one of an entity's several values for a field that an independent candidate of another source kind names.

    A property written with several values (JSON-LD 1.1 §4.3.1: an array is a set of values, in no significant
    order; HTML microdata: a repeated itemprop) gives a single-valued field several candidates of one entity, and
    no order among them says which is meant. When the values that independent candidates of other kinds equal
    (Open Graph's `og:image`, a field's one value) are one value, it is the one the page means; a namer equal to
    none of them is then rejected by precedence as usual. With no equal one, an image_url value may name one by its
    file (`resource_key`: the same image in another rendition). Anything else stays a conflict. Admitted state
    values are never independent, so they never select (§8.1)."""
    if len({c.entity_id for c in members}) != 1:
        return None
    namers = [o for o in kept if o.independent and o.source_kind != members[0].source_kind]
    named = [m for m in members if any(_equal(o, m, spec) for o in namers)] or _same_resource(spec, members, namers)
    return named[0] if named and _all_agree(named, spec) else None


def _same_resource(spec: FieldSpec, members: list[Candidate], namers: list[Candidate]) -> list[Candidate]:
    keys = {resource_key(_value(o), spec) for o in namers} - {None}
    return [m for m in members if resource_key(_value(m), spec) in keys]


def _without(candidates: list[Candidate], removed: list[Candidate]) -> list[Candidate]:
    return [c for c in candidates if not any(c is r for r in removed)]


def _all_rejected(
    status: Literal["missing", "conflict"], reason: str, kept: list[Candidate], rejected: list[Rejection]
) -> Unpublished:
    return Unpublished(status, reason, (*rejected, *((c, reason) for c in kept)), tuple(kept))


def _missing_reason(rejected: list[Rejection]) -> str:
    if not rejected:
        return "no_candidates"
    return max((reason for _, reason in rejected), key=_STAGES.index)


def rule_type(spec: FieldSpec) -> FieldType:
    # A list's values are its items', so it ranks or agrees as its item type does; an object agrees as a whole.
    return spec.item.type if spec.type is FieldType.LIST and spec.item is not None else spec.type


def _all_agree(candidates: Sequence[Candidate], spec: FieldSpec) -> bool:
    # Every pair: the location type's equality is not transitive (SPEC-04 §4.5).
    return all(_equal(a, b, spec) for a, b in combinations(candidates, 2))


def _equal(a: Candidate, b: Candidate, spec: FieldSpec) -> bool:
    return equal(_value(a), _value(b), spec)


def _value(candidate: Candidate) -> JsonValue:
    if not isinstance(candidate.normalized, Ok):
        raise TypeError("only kept candidates are compared")
    return candidate.normalized.value


def _scalars(raw: Raw) -> Iterator[str]:
    """The raw value's strings and numbers as text: what could have been copied from a query parameter."""
    return (value if isinstance(value, str) else json.dumps(value) for _, value in scalars(raw))


def load_precedence(path: Path) -> dict[FieldType, tuple[SourceKind, ...]]:
    """The orders of a `source_precedence.yaml`: fitted on dev only (INV-02), with one order per precedence type."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("source_split") != "dev":
        raise ValueError(
            f"{PRECEDENCE_FILE}: not a mapping stamped `source_split: dev`; the order is fitted on dev only"
        )
    orders = parse_orders(document)
    typed: dict[FieldType, tuple[SourceKind, ...]] = {}
    for type_ in sorted(PRECEDENCE_TYPES):
        if type_.value not in orders:
            raise ValueError(f"{PRECEDENCE_FILE}: no order for {type_.value}")
        typed[type_] = orders.pop(type_.value)
    if orders:
        raise ValueError(f"{PRECEDENCE_FILE}: {sorted(orders)} rank by agreement, not by an order")
    return typed


def parse_orders(document: object) -> dict[str, tuple[SourceKind, ...]]:
    """Every top-level key but the stamp names a field type and holds its list of source kinds."""
    if not isinstance(document, dict):
        raise ValueError(f"{PRECEDENCE_FILE} is not a mapping")
    orders: dict[str, tuple[SourceKind, ...]] = {}
    for type_, order in document.items():
        if type_ in STAMP:
            continue
        if not isinstance(order, list) or not all(isinstance(kind, str) for kind in order):
            raise ValueError(f"{PRECEDENCE_FILE}: {type_} is not a list of source kinds")
        if unknown := sorted(set(order) - _SOURCE_KINDS):
            raise ValueError(f"{PRECEDENCE_FILE}: {type_} names an unknown source kind {unknown}")
        orders[str(type_)] = cast(tuple[SourceKind, ...], tuple(order))
    return orders
