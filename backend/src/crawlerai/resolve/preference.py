"""Preference (resolution spec rule 4, §10): which of a field's candidates publishes.

A candidate is kept when it normalized (validity), belongs to the target (ownership, §4.6) and is not a value taken
from the request URL's query (INV-13); every other one is rejected with its reason. Of the kept candidates, an
exact-match type publishes only when all agree (INV-14); text, long_text, url and image_url take the first source kind
of the type's order in `source_precedence.yaml`. A page's Offer fields come from one Offer (INV-15).

On a detail page (variants spec, INV-38), no variant is a default: every Offer of the target and of
its variants joins the atomic-offer rule, so a value that varies across variants publishes only in the row-mapped
`variants` field. An identifier field the target states nothing for takes the value every variant states alike (variant
fill).

Evidence buckets, confidence and τ are the next stage's (`resolve.evidence`); this module only chooses.
"""

import json
from collections.abc import Callable, Hashable, Iterator, Mapping, Sequence
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
from crawlerai.normalize import money, url
from crawlerai.normalize.base import BASES, Ambiguous, Invalid, Ok, Raw
from crawlerai.normalize.dispatch import equal, equality_key, resource_key
from crawlerai.normalize.text import text_form
from crawlerai.resolve.ownership import OFFER, EntityGraph
from crawlerai.resolve.supersede import superseded
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PRECEDENCE_FILE = "source_precedence.yaml"
# The types whose candidates rank by source kind; every other type publishes only on agreement.
PRECEDENCE_TYPES = frozenset({FieldType.TEXT, FieldType.LONG_TEXT, FieldType.URL, FieldType.IMAGE_URL})
# What `crawlerai eval fit-precedence` stamps on the file; every other key names a field type.
STAMP = frozenset({"source_split", "git_sha"})
_SOURCE_KINDS: frozenset[str] = frozenset(get_args(SourceKind))
# The screening stages in the order a candidate meets them; a missing field states the furthest one reached.
_STAGES = ("invalid", "ambiguous", "not_owned", "url_param")
# GS1 GTIN and a seller's SKU identify one product, so a variant's identifies the variant (variants spec, variant fill).
_FILLED_SCHEMES = frozenset({"gtin", "sku"})
_HTTPS = "https"  # RFC 9110 §4.2.2

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
class Resolver:
    """Preference for one entity, `target`: a detail page's target (§4.6), a listing's page or one of its rows (§4.7).
    Its fields' candidates are screened, then chosen per type. `page_values`: whether page-level candidates are the
    target's (`EntityGraph.owned_by`). `owns` stands in for ownership where the owner is not one entity: a variant's
    rows (variants spec)."""

    graph: EntityGraph
    target: Entity
    page: PageFacts
    orders: Orders
    page_values: bool = True
    variant_fill: bool = False  # a detail page's target only (variants spec)
    owns: Callable[[Candidate], bool] | None = None

    def prefer(self, schema: SchemaDef, candidates: Sequence[Candidate]) -> dict[str, Preference]:
        return self.prefer_fields(schema.fields, candidates)

    def prefer_fields(
        self, fields: Mapping[str, FieldSpec], candidates: Sequence[Candidate], *, prefix: str = ""
    ) -> dict[str, Preference]:
        """Every field's preference; a candidate is a field's when its field is `prefix` and the name (a row-mapped
        field's sub-fields are `<field>.<sub-field>`, variants spec)."""
        by_field = {name: [c for c in candidates if c.field == f"{prefix}{name}"] for name in fields}
        screened = {name: self.screen(by_field[name]) for name in fields}
        # In schema order: the anchor takes the first Offer seen on a tie.
        offer_fields = [name for name, spec in fields.items() if self._is_offer_field(spec)]
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

    def _fill(self, spec: FieldSpec, candidates: Sequence[Candidate], preference: Preference) -> Preference:
        """Variant fill (variants spec): a gtin or sku field the target states nothing for (no candidate is the
        target's) takes its variants' candidates when every variant has one and all agree: the value is common to
        the variants. A value the target states is never replaced, and no other field is filled."""
        if not self.variant_fill or spec.type is not FieldType.IDENTIFIER or spec.scheme not in _FILLED_SCHEMES:
            return preference
        if any(self.graph.owned_by(c, self.target, page_values=self.page_values) for c in candidates):
            return preference
        pooled = [self._variant_kept(member, candidates) for member in self.graph.variants(self.target)]
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
        kept, rejected = _best_settled(spec, kept, rejected)
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
        if _offers_disagree(offered, spec):
            return "offers_disagree"
        if all(c.entity_id != anchor for c in kept):
            return "offer_split"
        return None

    def _by_precedence(
        self, spec: FieldSpec, kept: list[Candidate], choosable: list[Candidate], rejected: list[Rejection]
    ) -> Preference:
        order = self.orders[rule_type(spec)]
        # A fragment of another candidate's value (`supersede`) ranks nowhere; it can still agree with the winner.
        fragments = superseded(spec, kept)
        live, live_choosable = _without(kept, fragments), _without(choosable, fragments)
        # A kind outside the order is not ranked on dev, so it never wins; it can still agree.
        kind = next((k for k in order if any(c.source_kind == k for c in live_choosable)), None)
        if kind is None:
            return _all_rejected("missing", "unranked", kept, rejected)
        chosen = _winner(spec, kind, live, live_choosable, order)
        if chosen is None:
            return _all_rejected("conflict", "disagree", kept, rejected)
        agreeing: list[Candidate] = []
        lower: list[Rejection] = []
        for c in kept:
            if c is chosen:
                continue
            if _equal(c, chosen, spec) or _one_file([c, chosen], spec):
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


def _best_settled(
    spec: FieldSpec, kept: list[Candidate], rejected: list[Rejection]
) -> tuple[list[Candidate], list[Rejection]]:
    """Normalization spec, money: a value whose currency rests on weaker evidence (`Ok.basis`: the page, its locale,
    or none) stands only where no better-settled candidate contradicts it. The others' values are kept when they equal
    a best-settled one (they agree with it), else rejected `weaker_currency`; the best-settled come first, so one of
    them is chosen."""
    if rule_type(spec) is not FieldType.MONEY:
        return kept, rejected
    rank = {id(c): _settled_rank(c) for c in kept}
    best = min(rank.values())
    strongest = [c for c in kept if rank[id(c)] == best]
    agreeing = [c for c in kept if rank[id(c)] == best or any(_equal(c, s, spec) for s in strongest)]
    weaker = [(c, "weaker_currency") for c in kept if not any(c is a for a in agreeing)]
    return sorted(agreeing, key=lambda c: rank[id(c)]), [*rejected, *weaker]


def _settled_rank(candidate: Candidate) -> int:
    """0 for a value that states its currency, else 1 + the place of its basis in `BASES` (weakest last)."""
    basis = candidate.normalized.basis if isinstance(candidate.normalized, Ok) else None
    return 0 if basis is None else 1 + BASES.index(basis)


def _without(candidates: Sequence[Candidate], excluded: Sequence[Candidate]) -> list[Candidate]:
    return [c for c in candidates if not any(c is e for e in excluded)]


def _by_agreement(spec: FieldSpec, kept: list[Candidate], chosen: Candidate, rejected: list[Rejection]) -> Preference:
    # INV-14: exact-match values publish only when every kept candidate agrees.
    agreeing = tuple(c for c in kept if c is not chosen)
    if not _all_agree(kept, spec):
        if not _currency_only(spec, kept):
            return _all_rejected("conflict", "disagree", kept, rejected)
        unknown = _currency_unknown(chosen)
        kept = [unknown if c is chosen else c for c in kept]
        chosen = unknown
    return Chosen(chosen, agreeing, tuple(rejected), tuple(kept))


def _currency_only(spec: FieldSpec, kept: Sequence[Candidate]) -> bool:
    """Normalization spec, money (owner #68): candidates on equally strong currency evidence that state one amount in
    different currencies agree on the amount, which publishes; only the currency is unsettled."""
    return spec.type is FieldType.MONEY and money.same_amount([_value(c) for c in kept])


def _currency_unknown(candidate: Candidate) -> Candidate:
    """The candidate's amount with its currency unknown (basis `unknown`): its evidence is contradicted (C7)."""
    normalized = candidate.normalized
    checked = normalized.checked if isinstance(normalized, Ok) else False
    value = money.without_currency(_value(candidate))
    return candidate.model_copy(update={"normalized": Ok(value, basis="unknown", checked=checked)})


def _winner(
    spec: FieldSpec, kind: SourceKind, kept: list[Candidate], choosable: list[Candidate], order: Sequence[SourceKind]
) -> Candidate | None:
    """The candidate of the winning kind that publishes. Two values from that kind leave the order nothing to decide
    between (C7: decline, never guess), unless they are renditions of one image (`_one_file`), or one entity's values
    and another kind names one of them."""
    winners = [c for c in kept if c.source_kind == kind]
    if _all_agree(winners, spec) or _one_file(winners, spec):
        return _secure_first([c for c in choosable if c.source_kind == kind], spec)
    named = _named_member(spec, winners, kept, order)
    return named if named is not None and any(c is named for c in choosable) else None


def _named_member(
    spec: FieldSpec, members: list[Candidate], kept: list[Candidate], order: Sequence[SourceKind]
) -> Candidate | None:
    """The one of an entity's several values for a field that independent candidates of another source kind name.

    A property written with several values (JSON-LD 1.1 §4.3.1: an array is a set of values, in no significant
    order; HTML microdata: a repeated itemprop) gives a single-valued field several candidates of one entity, and
    no order among them says which is meant. The other kinds' independent candidates name them kind by kind, in the
    type's precedence order (kinds outside it last): the first kind that names any decides. The values it equals
    (Open Graph's `og:image`, a field's one value) are the ones it names; with no equal one, an image_url value may
    name one by its file (`resource_key`: the same image in another rendition). When what it names is one value, or
    renditions of one file, that is the one the page means; anything else stays a conflict. Admitted state values
    are never independent, so they never select (§8.1)."""
    if len({c.entity_id for c in members}) != 1:
        return None
    namers = [o for o in kept if o.independent and o.source_kind != members[0].source_kind]
    for kind in _ranked_kinds(namers, order):
        named = _named_by(spec, members, [o for o in namers if o.source_kind == kind])
        if named:
            return _secure_first(named, spec) if _all_agree(named, spec) or _one_file(named, spec) else None
    return None


def _ranked_kinds(candidates: list[Candidate], order: Sequence[SourceKind]) -> list[SourceKind]:
    """The candidates' source kinds, each once, in precedence order; kinds outside the order last, as they come."""
    kinds = dict.fromkeys(c.source_kind for c in candidates)
    return [*(k for k in order if k in kinds), *(k for k in kinds if k not in order)]


def _named_by(spec: FieldSpec, members: list[Candidate], namers: list[Candidate]) -> list[Candidate]:
    """The members `namers` equal, else those whose file they name (`resource_key`)."""
    equal_ones = [m for m in members if any(_equal(o, m, spec) for o in namers)]
    if equal_ones:
        return equal_ones
    keys = {resource_key(_value(o), spec) for o in namers} - {None}
    return [m for m in members if resource_key(_value(m), spec) in keys]


def _one_file(candidates: Sequence[Candidate], spec: FieldSpec) -> bool:
    """Whether the candidates are image values (or lists of them) naming the same files, in other renditions: one
    image as the page states it more than once (`resource_key`), so they agree."""
    keys = {resource_key(_value(c), spec) for c in candidates}
    return len(keys) == 1 and None not in keys


def _secure_first(candidates: Sequence[Candidate], spec: FieldSpec) -> Candidate:
    """Of candidates that agree or are renditions of one file, those whose URLs all use `https` if any, else all: a
    rendition over `http` beside its `https` twin names the same file (`resource_key`), and `https` reaches it over
    TLS (RFC 9110 §4.2.2), so the page's secure statement of it publishes. Of a single image's renditions the largest
    publishes (`url.largest_rendition`), else the first."""
    if rule_type(spec) is not FieldType.IMAGE_URL:
        return candidates[0]
    secure = [c for c in candidates if _secure(_value(c))] or list(candidates)
    values = [_value(c) for c in secure]
    if spec.type is FieldType.IMAGE_URL and all(isinstance(v, str) for v in values):
        return secure[url.largest_rendition([v for v in values if isinstance(v, str)])]
    return secure[0]


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


def rule_type(spec: FieldSpec) -> FieldType:
    # A list's values are its items', so it ranks or agrees as its item type does; an object agrees as a whole.
    return spec.item.type if spec.type is FieldType.LIST and spec.item is not None else spec.type


def _all_agree(candidates: Sequence[Candidate], spec: FieldSpec) -> bool:
    keys = _equality_keys(candidates, spec)
    if keys is not None:
        return len(set(keys)) <= 1
    # Every pair: the location type's equality is not transitive (schemas spec).
    return all(_equal(a, b, spec) for a, b in combinations(candidates, 2))


def _offers_disagree(offered: Sequence[Candidate], spec: FieldSpec) -> bool:
    """Whether candidates of two different Offers differ. With an equivalence, that is two distinct values while more
    than one Offer states any: a candidate of another Offer than two different values' differs from one of them."""
    keys = _equality_keys(offered, spec)
    if keys is not None:
        return len(set(keys)) > 1 and len({c.entity_id for c in offered}) > 1
    return any(a.entity_id != b.entity_id and not _equal(a, b, spec) for a, b in combinations(offered, 2))


def _equality_keys(candidates: Sequence[Candidate], spec: FieldSpec) -> list[Hashable] | None:
    """The candidates' equality keys (`equality_key`: equal keys exactly when the values are equal), so that agreement
    is one pass over them; `None` when a value has none and pairs must be compared."""
    keys = [equality_key(_value(c), spec) for c in candidates]
    keyed = [key for key in keys if key is not None]
    return keyed if len(keyed) == len(keys) else None


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
    """The orders of a `source_precedence.yaml`: fitted on the golden set, with one order per precedence type."""
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
