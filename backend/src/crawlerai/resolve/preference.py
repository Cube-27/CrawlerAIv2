"""Preference (resolution spec, "Candidate score"): which of a field's candidates publishes.

A candidate is kept when it normalized (validity), belongs to the target (ownership, §4.6: scope match 0 otherwise) and
is not a value taken from the request URL's query (INV-13); every other one is rejected with its reason. The kept
candidates are scored (`resolve.score`: source weight times scope match times agreement) and the value of the best score
publishes; the candidates of every other value are rejected `outscored`. A field whose kept candidates state more than
one value publishes with a reason, the disagreement flag (`disagree`, `offers_disagree`, `offer_split`). Where the best
score is shared by two values the field is a `conflict`. A list of the item's facts (a job's places) publishes every
member its values state instead (`_union`): two sources stating different members are not rivals. A price is a
`conflict` too when amounts differ and no role explains it (`_price_winner`: the visible price, the shown variant);
amounts that differ only in currency publish, the currency unknown (C7: an unclear currency never drops a price).

Offers (INV-15, variants spec): the anchor Offer is the one of the variant the target shows (its own sku or gtin is
that variant's), else the one holding values for the most offer fields; its values and the target's own have scope 1,
another Offer's `OTHER_OFFER`. Availability and the other offer fields but money are a variant's: where the Offers
disagree, the target takes only the shown variant's value, else the field is `offers_disagree`; a field only another
Offer than the anchor states is `offer_split`. An identifier field the target states nothing for takes the value every
variant states alike (variant fill).

Evidence buckets, confidence and min_confidence are the next stage's (`resolve.evidence`); this module only chooses.
"""

import json
import re
from collections.abc import Callable, Hashable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import Literal, cast, get_args
from urllib.parse import parse_qsl, urlsplit

import yaml
from pydantic import JsonValue

from crawlerai.collect.base import PAGE, Candidate, Entity
from crawlerai.collect.json_doc import scalars
from crawlerai.db.models import SourceKind
from crawlerai.normalize import money, url
from crawlerai.normalize.base import Ambiguous, Invalid, Ok, Raw, raw_key
from crawlerai.normalize.dispatch import with_member
from crawlerai.normalize.text import text_form
from crawlerai.resolve.identity import VARIANT
from crawlerai.resolve.ownership import OFFER, EntityGraph
from crawlerai.resolve.score import (
    OTHER_OFFER,
    OWN,
    PRECEDENCE_TYPES,
    Group,
    Scope,
    rank,
    rule_type,
    same_value,
    value_of,
)
from crawlerai.schemas.paths import parse_paths, price_role
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

__all__ = ["PRECEDENCE_TYPES", "Chosen", "PageFacts", "Preference", "Resolver", "Unpublished", "rule_type"]

PRECEDENCE_FILE = "source_precedence.yaml"
# What the fit stamped on the file (frozen 2026-10-18; evaluation spec); every other key names a field type.
STAMP = frozenset({"source_split", "git_sha"})
_SOURCE_KINDS: frozenset[str] = frozenset(get_args(SourceKind))
# The screening stages in the order a candidate meets them; a missing field states the furthest one reached.
_STAGES = ("invalid", "ambiguous", "not_owned", "url_param", "range_bound")
# GS1 GTIN and a seller's SKU identify one product, so a variant's identifies the variant (variants spec).
_VARIANT_IDS = frozenset({"gtin", "sku"})
_HTTPS = "https"  # RFC 9110 §4.2.2
# Why a field publishes with a flag, or is a conflict.
DISAGREE = "disagree"
OFFERS_DISAGREE = "offers_disagree"
OFFER_SPLIT = "offer_split"
OUTSCORED = "outscored"

Orders = Mapping[FieldType, tuple[SourceKind, ...]]  # per precedence type, the source kinds, first weighs most
Rejection = tuple[Candidate, str]  # a candidate that does not publish, with its reason


@dataclass(frozen=True, slots=True)
class Chosen:
    """The field publishes `candidate`'s normalized value. `agreeing` are the other kept candidates of its value;
    `kept` are all the candidates that passed screening, `candidate` included. `flag`: why a published field's kept
    candidates did not all agree (`disagree`, `offers_disagree`, `offer_split`), else None."""

    candidate: Candidate
    agreeing: tuple[Candidate, ...]
    rejected: tuple[Rejection, ...]
    kept: tuple[Candidate, ...]
    flag: str | None = None


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
class _Offers:
    """The page's Offers as preference reads them: `anchor`, the Offers whose values have scope 1 (none: every Offer
    has), and `shown`, the Offers of the variant the target shows (variants spec)."""

    anchor: frozenset[str] = frozenset()
    shown: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Resolver:
    """Preference for one entity, `target`: a detail page's target (§4.6), a listing's page or one of its rows (§4.7).
    Its fields' candidates are screened, then scored. `page_values`: whether page-level candidates are the target's
    (`EntityGraph.owned_by`). `owns` stands in for ownership where the owner is not one entity: a variant's rows
    (variants spec). `detail`: a detail page's target, which reads the variant it shows and fills from its variants.
    `confident`: whether a chosen value of the named field would publish at the request's `min_confidence`
    (`resolve.evidence`); None: every one would."""

    graph: EntityGraph
    target: Entity
    page: PageFacts
    orders: Orders
    page_values: bool = True
    detail: bool = False
    owns: Callable[[Candidate], bool] | None = None
    confident: Callable[[str, FieldSpec, "Chosen"], bool] | None = None

    def prefer(self, schema: SchemaDef, candidates: Sequence[Candidate]) -> dict[str, Preference]:
        return self.prefer_fields(schema.fields, candidates)

    def prefer_fields(
        self, fields: Mapping[str, FieldSpec], candidates: Sequence[Candidate], *, prefix: str = ""
    ) -> dict[str, Preference]:
        """Every field's preference; a candidate is a field's when its field is `prefix` and the name (a row-mapped
        field's sub-fields are `<field>.<sub-field>`, variants spec)."""
        by_field = {name: [c for c in candidates if c.field == f"{prefix}{name}"] for name in fields}
        screened = {name: self.screen(by_field[name]) for name in fields}
        bounds = _range_bounds(fields, screened)
        screened = {
            name: _without_bounds(*found, bounds) if price_role(fields[name]) == "price" else found
            for name, found in screened.items()
        }
        # In schema order: the anchor takes the first Offer seen on a tie.
        offer_fields = [name for name, spec in fields.items() if self._is_offer_field(spec)]
        offers = self._page_offers(fields, candidates, screened, offer_fields)
        chosen = {
            name: self._choose(spec, *screened[name], offers=offers, offer_field=name in offer_fields)
            for name, spec in fields.items()
        }
        return {name: self._fill(spec, by_field[name], chosen[name]) for name, spec in fields.items()}

    def prefer_field(self, spec: FieldSpec, candidates: Sequence[Candidate]) -> Preference:
        """One field on its own, outside the page's Offers: for values derived after preference (`derive`)."""
        return self._choose(spec, *self.screen(candidates), offers=_Offers(), offer_field=False)

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

    def _choose(
        self, spec: FieldSpec, kept: list[Candidate], rejected: list[Rejection], *, offers: _Offers, offer_field: bool
    ) -> Preference:
        if not kept:
            return Unpublished("missing", _missing_reason(rejected), tuple(rejected))
        groups = rank(spec, kept, self._scope(offers), self.orders.get(rule_type(spec), ()))
        if groups[0].score <= 0:  # every kind outside the fitted order, or a fragment (resolve.score)
            return _all_rejected("missing", "unranked", kept, rejected)
        if not offer_field and _members(spec):
            return _union(spec, [g for g in groups if g.score > 0], kept, rejected)
        return self._settled(spec, groups, kept, rejected, offers=offers, offer_field=offer_field)

    def _settled(
        self,
        spec: FieldSpec,
        groups: list[Group],
        kept: list[Candidate],
        rejected: list[Rejection],
        *,
        offers: _Offers,
        offer_field: bool,
    ) -> Preference:
        """The value that publishes of the ranked `groups` (a scored best one), or the field's conflict."""
        top = groups[0]
        if rule_type(spec) is FieldType.MONEY:
            won = self._price_winner(top, groups, offers, offer_field=offer_field)
            if isinstance(won, str):
                return _all_rejected("conflict", won, kept, rejected)
            top = won
        elif offer_field:
            top = self._shown_value([g for g in groups if g.score > 0], offers) or top
        top, rivals, tied = _contest(spec, groups, top)
        flag = self._flag(top, groups, rivals, offers, offer_field=offer_field)
        if rule_type(spec) is FieldType.MONEY:
            return _price(spec, top, tied, kept, rejected, flag)
        refused = self._refused(top, tied, groups, offers, offer_field=offer_field)
        if refused is not None:
            return _all_rejected("conflict", refused, kept, rejected)
        return _published(spec, top, kept, rejected, flag)

    def _price_winner(self, top: Group, groups: list[Group], offers: _Offers, *, offer_field: bool) -> Group | str:
        """The group whose amount publishes as the price, or why none does (`conflict`). Amounts that differ are
        rival prices, and each is explained by its role before the field is refused:
        - the visible price: the one amount a rendered `dom` value states beats the structured, meta or data-call
          amounts (stale markup is the common cause; HTML Standard: struck `s`/`del` text is already no value);
        - the shown variant (INV-38): its Offer's amount beats the amounts of other Offers (other variants or sellers);
        - a list or was price, a unit, member, installment or bundle price are not candidates of this field: the
          price path's predicates leave out struck, list, member and unit price specifications (`schemas.paths`), the
          DOM collectors skip struck text and amounts written per unit or per period (`normalize.units`), and a
          visible amount bounding a stated price range is rejected `range_bound` (`_range_bounds`).
        An amount two candidates of one source role state for the same variant, with nothing explaining it, is the
        product's price by no evidence: `conflict` (owner: accuracy before coverage). Amounts that differ only in
        currency are not rivals (C7: the currency is unknown, not the price)."""
        contenders = [top, *(g for g in groups[1:] if g.score > 0 and not _same_amount(top, g))]
        visible = [g for g in contenders if any(c.source_kind == "dom" and c.independent for c in g.members)]
        if len(contenders) > 1 and len(visible) == 1:
            return visible[0]
        if (shown := self._shown_value(contenders, offers)) is not None:
            return shown  # the shown variant's Offer states its own price, however the others score
        if offer_field and self._split(top, offers):  # only another Offer than the anchor states it (INV-15)
            return OFFER_SPLIT
        if len(contenders) == 1:
            return top
        return OFFERS_DISAGREE if offer_field and self._offers_disagree(groups) else DISAGREE

    def _shown_value(self, contenders: list[Group], offers: _Offers) -> Group | None:
        """The one value (an amount, an availability) the shown variant's Offers state when every other value is
        only an Offer outside it (INV-38): the other variants' values are theirs, not the item's."""

        def inside(group: Group) -> bool:
            return any(self._offer_of(c) in offers.shown for c in group.members)

        def elsewhere(group: Group) -> bool:
            return all((o := self._offer_of(c)) is not None and o not in offers.shown for c in group.members)

        shown = [g for g in contenders if inside(g)]
        return shown[0] if len(shown) == 1 and all(elsewhere(g) for g in contenders if g not in shown) else None

    def _refused(
        self, top: Group, tied: list[Group], groups: list[Group], offers: _Offers, *, offer_field: bool
    ) -> str | None:
        """Why the best value of a field other than money does not publish: Offers that disagree on a variant's value
        when it is not the shown variant's (`offers_disagree`), a value only another Offer than the anchor states
        (`offer_split`), or a best score two values share (`disagree`, C7: decline rather than guess)."""
        if offer_field and self._offers_disagree(groups):
            return None if self._shown_value([top, *tied], offers) is top else OFFERS_DISAGREE
        if offer_field and self._split(top, offers):
            return OFFER_SPLIT
        return DISAGREE if tied else None

    def _flag(
        self, top: Group, groups: list[Group], rivals: list[Group], offers: _Offers, *, offer_field: bool
    ) -> str | None:
        """The flag of a published value: its Offers disagree (the shown variant's value publishes all the same), only
        another Offer than the anchor states it (a price), or its other candidates state other values."""
        if offer_field and self._offers_disagree(groups):
            return OFFERS_DISAGREE
        if offer_field and self._split(top, offers):
            return OFFER_SPLIT
        return DISAGREE if rivals else None

    def _split(self, top: Group, offers: _Offers) -> bool:
        """Whether only Offers other than the anchor state the value (INV-15)."""
        return bool(offers.anchor) and all(self._offer_of(c) not in (None, *offers.anchor) for c in top.members)

    def _offers_disagree(self, groups: list[Group]) -> bool:
        """Whether two of the field's values are stated by Offers (§4.8)."""
        return sum(any(self._offer_of(c) is not None for c in g.members) for g in groups) > 1

    def _scope(self, offers: _Offers) -> Scope:
        """Scope match (`resolve.score`): 1 for the target's own values and the anchor Offer's, `OTHER_OFFER` for
        another Offer's."""

        def scope(candidate: Candidate) -> Fraction:
            offer = self._offer_of(candidate)
            return OWN if not offers.anchor or offer is None or offer in offers.anchor else OTHER_OFFER

        return scope

    def _page_offers(
        self,
        fields: Mapping[str, FieldSpec],
        candidates: Sequence[Candidate],
        screened: Mapping[str, tuple[list[Candidate], list[Rejection]]],
        offer_fields: Sequence[str],
    ) -> _Offers:
        """The anchor Offer: on a detail page the Offers of the variant the target shows, else the one holding values
        for the most offer fields."""
        anchor = self._anchor({name: screened[name][0] for name in offer_fields})
        offers = _Offers(frozenset(() if anchor is None else (anchor,)))
        if not self.detail:
            return offers
        # The target's own sku and gtin, as they publish, select the variant it shows (variants spec).
        ids = [name for name in _variant_ids(fields) if name in fields]
        stated = {name: self._choose(fields[name], *screened[name], offers=offers, offer_field=False) for name in ids}
        shown, other = self._shown_offers(fields, candidates, self._published_ids(fields, stated))
        shown |= self._lone_offers(frozenset(source_of(offer) for offer in shown)) - other
        return _Offers(shown, shown) if shown else offers

    def _published_ids(
        self, fields: Mapping[str, FieldSpec], stated: Mapping[str, Preference]
    ) -> list[tuple[Candidate, FieldSpec]]:
        """The sku and gtin values the target publishes as its own: chosen, its own or the page's (not an Offer's),
        and confident at the request's `min_confidence`."""
        return [
            (decision.candidate, fields[name])
            for name, decision in stated.items()
            if isinstance(decision, Chosen)
            and self.graph.owner_of(decision.candidate).id in (self.target.id, PAGE)
            and (self.confident is None or self.confident(name, fields[name], decision))
        ]

    def _lone_offers(self, named: frozenset[str]) -> frozenset[str]:
        """The Offers of the target each of whose sources (`_source`) other than `named` states one alone: a source's
        one Offer of the item is its offer, the variant the page shows (resolution spec, Atomic offers). A source
        listing several states which of them each is by its sku or gtin."""
        by_source: dict[str, list[str]] = {}
        for offer in self.graph.offers(self.target):
            by_source.setdefault(source_of(offer.id), []).append(offer.id)
        return frozenset(o[0] for source, o in by_source.items() if len(o) == 1 and source not in named)

    def _shown_offers(
        self, fields: Mapping[str, FieldSpec], candidates: Sequence[Candidate], own: list[tuple[Candidate, FieldSpec]]
    ) -> tuple[frozenset[str], frozenset[str]]:
        """The Offers of the variant the target shows (variants spec): of the target's Offers and variants, those
        whose sku or gtin (a field's or a row sub-field's) equals one of `own`, at most one per source, with every
        other source's Offer stating the same sku or gtin as one of them (GS1 GTIN and a seller's SKU identify one
        variant, whichever source states it); none when no unit matches or a source names two. Second, the Offers
        whose sku or gtin names another variant than those: never the shown one's."""
        ids = _variant_ids(fields)
        stated = [
            (unit, c, ids[c.field])
            for c in candidates
            if c.field in ids and isinstance(c.normalized, Ok) and (unit := self._unit(c)) is not None
        ]
        matched = _shown_units(stated, own)
        other = {unit for unit, _, _ in stated if own and unit not in matched}
        return self._offers_of(matched), self._offers_of(other)

    def _offers_of(self, units: set[str]) -> frozenset[str]:
        return frozenset(offer for unit in units for offer in self._unit_offers(unit))

    def _unit_offers(self, unit: str) -> frozenset[str]:
        """A variant's Offers, or the one Offer `unit` is."""
        held = self.graph.entities[unit]
        return frozenset(o.id for o in self.graph.offers(held)) if held.via == VARIANT else frozenset({held.id})

    def _unit(self, candidate: Candidate) -> str | None:
        """The variant or Offer of the target that holds the candidate: a `hasVariant` member, or an Offer of the
        target itself; None for any other owner."""
        owner = self.graph.owner_of(candidate)
        if self.graph.is_a(owner, OFFER) and owner.parent is not None:
            holder = self.graph.entities[owner.parent]
            return owner.id if holder.id == self.target.id else self._variant_id(holder)
        return self._variant_id(owner)

    def _variant_id(self, entity: Entity) -> str | None:
        return entity.id if entity.via == VARIANT and entity.parent == self.target.id else None

    def _fill(self, spec: FieldSpec, candidates: Sequence[Candidate], preference: Preference) -> Preference:
        """Variant fill (variants spec): a gtin or sku field the target states nothing for (no candidate is the
        target's) takes its variants' candidates when every variant has one and all agree: the value is common to
        the variants. A value the target states is never replaced, and no other field is filled."""
        if not self.detail or spec.type is not FieldType.IDENTIFIER or spec.scheme not in _VARIANT_IDS:
            return preference
        if any(self.graph.owned_by(c, self.target, page_values=self.page_values) for c in candidates):
            return preference
        pooled = [self._variant_kept(member, candidates) for member in self.graph.variants(self.target)]
        if not pooled or not all(pooled):
            return preference
        kept = [c for member_kept in pooled for c in member_kept]
        if not all(same_value(a, b, spec) for a, b in combinations(kept, 2)):
            return preference
        rejected = tuple(r for r in preference.rejected if not any(r[0] is c for c in kept))
        return Chosen(kept[0], tuple(kept[1:]), rejected, tuple(kept))

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


def _variant_ids(fields: Mapping[str, FieldSpec]) -> dict[str, FieldSpec]:
    """The sku and gtin fields, a row-mapped field's sub-fields (`<field>.<sub-field>`) included, by candidate field."""
    specs = dict(fields)
    for name, spec in fields.items():
        if spec.item is not None and spec.item.fields is not None:
            specs.update({f"{name}.{sub}": sub_spec for sub, sub_spec in spec.item.fields.items()})
    return {
        name: spec for name, spec in specs.items() if spec.type is FieldType.IDENTIFIER and spec.scheme in _VARIANT_IDS
    }


def intent_ambiguous(schema: SchemaDef, candidates: Sequence[Candidate]) -> dict[str, Preference]:
    """§4.6: with no single target, every field is a conflict and no candidate publishes."""
    return {
        name: Unpublished(
            "conflict", "intent_ambiguous", tuple((c, "intent_ambiguous") for c in candidates if c.field == name)
        )
        for name in schema.fields
    }


# schema.org AggregateOffer: `lowPrice` and `highPrice` state the range of its offers' prices.
_LOW_PRICE, _HIGH_PRICE = "lowPrice", "highPrice"
RANGE_BOUND = "range_bound"


_Bound = tuple[Decimal, str | None]  # a range bound's amount and the range's currency (`None`: unknown)


def _bounds_it(shown: _Bound | None, bounds: frozenset[_Bound]) -> bool:
    if shown is None:
        return False
    amount, currency = shown
    return any(bound == amount and (None in (currency, ours) or currency == ours) for bound, ours in bounds)


def _range_bounds(
    fields: Mapping[str, FieldSpec], screened: Mapping[str, tuple[list[Candidate], list[Rejection]]]
) -> frozenset[_Bound]:
    """The amounts that bound a price range structured data states (an AggregateOffer's `lowPrice` and `highPrice`,
    kept for a range field) whose bounds differ, each with the range's currency: the page's prices span them, so
    neither one is the item's price."""
    ranges = (c for name, (kept, _) in screened.items() if fields[name].type is FieldType.RANGE for c in kept)
    return frozenset(bound for candidate in ranges for bound in _stated_bounds(candidate))


def _stated_bounds(candidate: Candidate) -> tuple[_Bound, ...]:
    """A price range candidate's bounds, when it is an AggregateOffer's and they differ."""
    value, raw = value_of(candidate), candidate.raw
    if not (isinstance(raw, dict) and _LOW_PRICE in raw and _HIGH_PRICE in raw and isinstance(value, dict)):
        return ()
    low, high = Decimal(str(value["min"])), Decimal(str(value["max"]))
    currency = value.get("currency")
    known = currency if isinstance(currency, str) else None
    bounds = {(low, known), (high, known)}
    return tuple(bounds) if len(bounds) > 1 else ()  # equal bounds state one price, no range


def _without_bounds(
    kept: list[Candidate], rejected: list[Rejection], bounds: frozenset[_Bound]
) -> tuple[list[Candidate], list[Rejection]]:
    """The price's candidates with the visible amounts that are a stated range's bound (`_range_bounds`) rejected
    `range_bound` (resolution spec, "Candidate score"): "From $80" beside `lowPrice` 80 states the range, not the
    price. An amount in another currency than the range's is no bound; a currency either leaves unknown may be."""
    bound = [c for c in kept if c.source_kind == "dom" and _bounds_it(money.amount_and_currency(value_of(c)), bounds)]
    return [c for c in kept if c not in bound], [*rejected, *((c, RANGE_BOUND) for c in bound)]


def _same_amount(a: Group, b: Group) -> bool:
    return money.same_amount([value_of(a.members[0]), value_of(b.members[0])])


def _price(
    spec: FieldSpec, top: Group, tied: list[Group], kept: list[Candidate], rejected: list[Rejection], flag: str | None
) -> Chosen:
    """A price no other amount contests publishes (`_price_winner`): of values sharing the best score, which state one
    amount, the first stated; in different currencies, the amount with its currency unknown (basis `unknown`: an
    unclear currency never drops a price, C7)."""
    chosen = _published(spec, top, kept, rejected, flag)
    if not tied or not money.same_amount([value_of(c) for g in (top, *tied) for c in g.best]):
        return chosen
    unknown = _currency_unknown(chosen.candidate)
    return Chosen(
        unknown,
        chosen.agreeing,
        chosen.rejected,
        tuple(unknown if c is chosen.candidate else c for c in kept),
        chosen.flag,
    )


def _published(
    spec: FieldSpec, top: Group, kept: list[Candidate], rejected: list[Rejection], flag: str | None
) -> Chosen:
    """The best group's best member publishes, the others of its value agree, and every other value is outscored."""
    chosen = _largest_renditions(top, _secure_first(top.best, spec), spec)
    agreeing = tuple(c for c in top.members if c is not chosen)
    lower = [(c, OUTSCORED) for c in kept if not any(c is m for m in top.members)]
    return Chosen(chosen, agreeing, (*rejected, *lower), tuple(kept), flag)


# The item types whose lists hold members rather than one rival value per source (`_members`): a list of lists or of
# objects (variants) is a value as a whole, a list of images or links is settled by the files it names, and amounts
# are rival prices (`_price_winner`).
_WHOLE_ITEMS = frozenset({FieldType.LIST, FieldType.OBJECT, FieldType.URL, FieldType.IMAGE_URL, FieldType.MONEY})


def _members(spec: FieldSpec) -> bool:
    """Whether the field is a list of facts of the item, each one a member (a job's places): two sources stating
    different ones state more members of the item, not rival values (resolution spec, "Candidate score")."""
    return spec.type is FieldType.LIST and spec.item is not None and spec.item.type not in _WHOLE_ITEMS


def _union(spec: FieldSpec, groups: list[Group], kept: list[Candidate], rejected: list[Rejection]) -> Chosen:
    """The list of every member the field's ranked values state, best first (`dispatch.with_member`: one member for
    two statements of it), as the best group's candidate: no other value is outscored. One value publishes as is."""
    top = groups[0]
    if len(groups) == 1:
        return _published(spec, top, kept, rejected, None)
    item = cast(FieldSpec, spec.item)
    members: list[JsonValue] = []
    for group in groups:
        stated = value_of(group.best[0])
        for value in stated if isinstance(stated, list) else [stated]:
            members = with_member(members, value, item)
    chosen = top.best[0]
    union = _listing(chosen, members, [c for g in groups for c in g.best[:1]])
    agreeing = tuple(c for c in top.members if c is not chosen)
    return Chosen(union, agreeing, tuple(rejected), tuple(kept))


def _currency_unknown(candidate: Candidate) -> Candidate:
    """The candidate's amount with its currency unknown (basis `unknown`): its evidence is contradicted (C7)."""
    normalized = candidate.normalized
    checked = normalized.checked if isinstance(normalized, Ok) else False
    value = money.without_currency(value_of(candidate))
    return candidate.model_copy(update={"normalized": Ok(value, basis="unknown", checked=checked)})


def _secure_first(candidates: Sequence[Candidate], spec: FieldSpec) -> Candidate:
    """Of candidates that agree or are renditions of one file, those whose URLs all use `https` if any, else all: a
    rendition over `http` beside its `https` twin names the same file (`resource_key`), and `https` reaches it over
    TLS (RFC 9110 §4.2.2), so the page's secure statement of it publishes. Of a single image's renditions the largest
    publishes (`url.largest_rendition`), else the first."""
    if rule_type(spec) is not FieldType.IMAGE_URL:
        return candidates[0]
    secure = [c for c in candidates if _secure(value_of(c))] or list(candidates)
    values = [value_of(c) for c in secure]
    if spec.type is FieldType.IMAGE_URL and all(isinstance(v, str) for v in values):
        return secure[url.largest_rendition([v for v in values if isinstance(v, str)])]
    return secure[0]


# A locator of one item of a list (`…['image'][2]`): the list's own locator, and the item's index.
_LIST_ITEM = re.compile(r"(.+)\[(\d{1,9})\]")


def _contest(spec: FieldSpec, groups: list[Group], top: Group) -> tuple[Group, list[Group], list[Group]]:
    """The best group, the other scored groups (its rivals), and those that tie with it (`_first_listed`)."""
    rivals = [g for g in groups if g is not top and g.score > 0]
    tied = [g for g in rivals if g.score == top.score]
    first = _first_listed(spec, [top, *tied])
    if first is None:
        return top, rivals, tied
    return first, [g for g in groups if g is not first and g.score > 0], []


def _first_listed(spec: FieldSpec, best: Sequence[Group]) -> Group | None:
    """Of image values that tie for the best score, the group holding the first item when all are items of one list of
    one node: a source listing a thing's images in order (RFC 8259 §1: an array is an ordered sequence) states its main
    image first, as Open Graph prefers the first of a repeated `og:image` (Open Graph protocol, "Arrays")."""
    if spec.type is not FieldType.IMAGE_URL or len(best) < 2:
        return None
    items = [(g, c, _LIST_ITEM.fullmatch(c.locator)) for g in best for c in g.best]
    found = [(g, (c.entity_id, c.source_kind, m.group(1)), int(m.group(2))) for g, c, m in items if m]
    if len(found) != len(items) or len({key for _, key, _ in found}) != 1:
        return None
    return min(found, key=lambda item: item[2])[0]


def _largest_renditions(top: Group, chosen: Candidate, spec: FieldSpec) -> Candidate:
    """The image value of the best group with each file at the largest rendition any member states: the members name
    the same files (`resource_key`), so the sources' weights settle which files the image is, and the rendition the
    page also states larger publishes (`url.preferred_rendition`), whichever source states it. A scalar publishes the
    member stating it; a list the chosen candidate with those renditions. Any other value is `chosen`."""
    if rule_type(spec) is not FieldType.IMAGE_URL or len(top.members) == 1:
        return chosen
    members = [chosen, *(c for c in top.members if c is not chosen)]
    stated = [_image_list(value_of(c)) for c in members]
    lists = [images for images in stated if images is not None]
    if len(lists) != len(members):
        return chosen
    largest = _at_largest(lists[0], lists[1:])
    if spec.type is FieldType.IMAGE_URL:
        return next((c for c, images in zip(members, lists, strict=True) if images == largest), chosen)
    if largest == lists[0]:
        return chosen
    return _listing(chosen, list(largest), members)


def _listing(chosen: Candidate, items: list[JsonValue], sources: Sequence[Candidate]) -> Candidate:
    """`chosen` holding the list `items`, gathered from `sources`' values, each item published as one of them writes it
    (`Ok.stated`: a URL as the page writes it, never its resolved form): one writing it in full, else the first."""
    written: dict[Hashable, JsonValue] = {}
    for value, as_written in (pair for source in sources for pair in _writings(source)):
        # Of two writings of one item, the one in full (an absolute URL in canonical form) publishes.
        if as_written == value or raw_key(value) not in written:
            written[raw_key(value)] = as_written
    stated = [written.get(raw_key(item), item) for item in items]
    normalized = replace(cast(Ok, chosen.normalized), value=items, stated=None if stated == items else stated)
    return chosen.model_copy(update={"normalized": normalized})


def _writings(candidate: Candidate) -> list[tuple[JsonValue, JsonValue]]:
    """Each value the candidate states, an item of its list or its scalar, with its writing (`Ok.published`)."""
    if not isinstance(candidate.normalized, Ok):
        return []
    value, published = candidate.normalized.value, candidate.normalized.published
    if isinstance(value, list) and isinstance(published, list):
        return list(zip(value, published, strict=True))
    return [(value, published)]


def _at_largest(images: list[str], others: Sequence[list[str]]) -> list[str]:
    """Each of `images`, in its order, at its largest rendition among `others`' renditions of its file
    (`url.same_file`), whatever position they list it at."""
    renditions = [[item, *(r for listed in others for r in listed if url.same_file(item, r))] for item in images]
    return [url.preferred_rendition(found) for found in renditions]


def _image_list(value: JsonValue) -> list[str] | None:
    """An image value as its URLs, a scalar as one; None when an item is no URL string."""
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, str)] if all(isinstance(i, str) for i in items) else None


def _secure(value: JsonValue) -> bool:
    items = value if isinstance(value, list) else [value]
    return all(isinstance(item, str) and urlsplit(item).scheme == _HTTPS for item in items)


def _all_rejected(
    status: Literal["missing", "conflict"], reason: str, kept: list[Candidate], rejected: list[Rejection]
) -> Unpublished:
    return Unpublished(status, reason, (*rejected, *((c, reason) for c in kept)), tuple(kept))


def _missing_reason(rejected: list[Rejection]) -> str:
    if not rejected:
        return "no_candidates"
    return max((reason for _, reason in rejected), key=_STAGES.index)


def _scalars(raw: Raw) -> Iterator[str]:
    """The raw value's strings and numbers as text: what could have been copied from a query parameter."""
    return (value if isinstance(value, str) else json.dumps(value) for _, value in scalars(raw))


def load_precedence(path: Path) -> dict[FieldType, tuple[SourceKind, ...]]:
    """The orders of a `source_precedence.yaml`: fitted once (frozen engine data, evaluation spec), with one order per
    precedence type."""
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


def _names(candidate: Candidate, spec: FieldSpec, ids: Sequence[tuple[Candidate, FieldSpec]]) -> bool:
    """Whether a sku or gtin candidate states one of `ids` of its own scheme."""
    return any(spec.scheme == o_spec.scheme and same_value(candidate, o, spec) for o, o_spec in ids)


_Stated = tuple[str, Candidate, FieldSpec]  # a variant or Offer, one sku or gtin candidate of it, and its field


def _shown_units(stated: Sequence[_Stated], own: Sequence[tuple[Candidate, FieldSpec]]) -> set[str]:
    """The variants and Offers whose sku or gtin is one of `own`, one per source, and the one of each other source
    stating the same sku or gtin as them; none when a source names two (`_one_each`)."""
    matched = {unit for unit, c, spec in stated if _names(c, spec, own)}
    if not matched or _one_each(matched) != matched:
        return set()
    named = {source_of(unit) for unit in matched}
    held = [(c, spec) for unit, c, spec in stated if unit in matched]
    return matched | _one_each({u for u, c, spec in stated if source_of(u) not in named and _names(c, spec, held)})


def _one_each(units: set[str]) -> set[str]:
    """The units whose source (`_source`) names no other of them: a source naming two variants names none."""
    sources = [source_of(unit) for unit in units]
    return {unit for unit, source in zip(units, sources, strict=True) if sources.count(source) == 1}


# The collectors whose entity ids name the document they read after the collector (`<collector>:<document>:<path>`):
# an adapter's answer (`adapter:<name>:`), and a JSON-LD script block (`jsonld:<block>:`), each a JSON-LD document of
# its own (JSON-LD 1.1 §7.1: a script element embeds one document), often written by another producer than the page's.
_DOCUMENTS = frozenset({"adapter", "jsonld"})


def source_of(entity_id: str) -> str:
    """The source an entity id names (`resolve.identity`): its collector, and for an adapter or a JSON-LD block the
    document it reads (`_DOCUMENTS`), so two adapters' answers, or two blocks, are two sources."""
    collector, _, rest = entity_id.partition(":")
    return f"{collector}:{rest.partition(':')[0]}" if collector in _DOCUMENTS else collector
