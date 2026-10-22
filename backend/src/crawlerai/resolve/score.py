"""The candidate score (resolution spec, "Candidate score"): one number per kept candidate of a field, the product of
its source weight, its scope match and its value's cross-source agreement. Preference publishes the value of the best
score (`resolve.preference`); this module only scores.

- Source weight: how far the candidate's own evidence is trusted, before any other candidate is looked at. For text,
  long_text, url and image_url it is the kind's place in the type's order fitted on dev (`source_precedence.yaml`):
  the first kind weighs 1, each later place 1/n less, a kind outside the order 0; a fragment of another candidate's
  value (`supersede`) weighs 0. For money it is the strength of the currency evidence (normalization spec, `Ok.basis`):
  a stated currency weighs 1, each weaker basis of `BASES` 1/(len(BASES)+1) less. Every other type has no measured
  order between kinds, so every kind weighs 1. A fallback (`Candidate.fallback`: a platform's own record standing in
  for the property, not the page's statement of it) weighs 0 beside an independent candidate that is none: it fills
  the field only where the page states no value, and lends no agreement to a value the page states.
- Scope match: whether the candidate is the requested product's own (`resolve.preference` passes it): 1 for the
  target's own values and its anchor Offer's, `OTHER_OFFER` for another Offer of the target or of its variants.
- Agreement: the share of the field's independent evidence that states the candidate's value: per source kind the
  weight of its best candidate, summed over the kinds stating the value, over the sum for every kind stating any.
  Only independent candidates count (§8.1: an admitted state value is admitted because it equals another). With no
  independent candidate every value has agreement 1.

Candidates that state one value form a group (equal after normalization, or renditions of one image file,
`resource_key`); a group scores its best member's score. Groups rank by score, then by their first member's place in
collector order.
"""

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Final, cast, get_args

import yaml
from pydantic import JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import BASES, Ok
from crawlerai.normalize.dispatch import equal, equality_key, resource_key
from crawlerai.resolve.supersede import superseded
from crawlerai.schemas.types import FieldSpec, FieldType

# The types whose source weight is the fitted order of source kinds; every other type weighs every kind alike.
PRECEDENCE_TYPES: Final = frozenset({FieldType.TEXT, FieldType.LONG_TEXT, FieldType.URL, FieldType.IMAGE_URL})
# Another Offer of the target, or of one of its variants, than the anchor: the product's, but not the offer the page
# states for it (atomic offers, INV-15). Half the anchor's, so it outscores the anchor's value only with at least twice
# its source weight times agreement. Scores are exact fractions, so two values tie only when their scores are equal.
OTHER_OFFER: Final = Fraction(1, 2)
OWN: Final = Fraction(1)
_NONE: Final = Fraction(0)

Scope = Callable[[Candidate], Fraction]

PRECEDENCE_FILE = "source_precedence.yaml"
# What the fit stamped on the file (frozen 2026-10-18; evaluation spec); every other key names a field type.
STAMP = frozenset({"source_split", "git_sha"})
_SOURCE_KINDS: frozenset[str] = frozenset(get_args(SourceKind))


@dataclass(frozen=True, slots=True)
class Score:
    weight: Fraction
    scope: Fraction
    agreement: Fraction

    @property
    def value(self) -> Fraction:
        return self.weight * self.scope * self.agreement


@dataclass(frozen=True, slots=True)
class Group:
    """Kept candidates stating one value, in collector order, with each one's score; `score` is the best of them."""

    members: tuple[Candidate, ...]
    scores: tuple[Score, ...]
    first: int  # the first member's place among the kept candidates

    @property
    def score(self) -> Fraction:
        return max(s.value for s in self.scores)

    @property
    def best(self) -> tuple[Candidate, ...]:
        """The members of the group's score, in collector order."""
        top = self.score
        return tuple(c for c, s in zip(self.members, self.scores, strict=True) if s.value == top)


def rank(spec: FieldSpec, kept: Sequence[Candidate], scope: Scope, order: Sequence[SourceKind]) -> list[Group]:
    """The kept candidates' value groups, best score first (module docstring)."""
    weights = source_weights(spec, kept, order)
    members = _grouped(spec, kept)
    total = _support(kept, weights)
    groups = []
    for indices in members:
        group = [kept[i] for i in indices]
        agreement = _support(group, weights) / total if total else OWN
        scores = tuple(Score(weights[id(c)], scope(c), agreement) for c in group)
        groups.append(Group(tuple(group), scores, indices[0]))
    return sorted(groups, key=lambda g: (-g.score, g.first))


def source_weights(spec: FieldSpec, kept: Sequence[Candidate], order: Sequence[SourceKind]) -> dict[int, Fraction]:
    """Each kept candidate's source weight, by `id` (module docstring)."""
    weights = _kind_weights(spec, kept, order)
    if any(c.independent and not c.fallback for c in kept):
        return {id(c): _NONE if c.fallback else weights[id(c)] for c in kept}
    return weights


def _kind_weights(spec: FieldSpec, kept: Sequence[Candidate], order: Sequence[SourceKind]) -> dict[int, Fraction]:
    type_ = rule_type(spec)
    if type_ in PRECEDENCE_TYPES:
        fragments = {id(c) for c in superseded(spec, kept)}
        return {id(c): _NONE if id(c) in fragments else _place(c.source_kind, order) for c in kept}
    if type_ is FieldType.MONEY:
        return {id(c): _currency_strength(c) for c in kept}
    return {id(c): OWN for c in kept}


def _place(kind: SourceKind, order: Sequence[SourceKind]) -> Fraction:
    return Fraction(len(order) - order.index(kind), len(order)) if kind in order else _NONE


def _currency_strength(candidate: Candidate) -> Fraction:
    """1 for a value that states its currency, else 1 less (1 + the place of its basis in `BASES`) / (len + 1)."""
    basis = candidate.normalized.basis if isinstance(candidate.normalized, Ok) else None
    return OWN if basis is None else 1 - Fraction(1 + BASES.index(basis), len(BASES) + 1)


def _support(candidates: Sequence[Candidate], weights: dict[int, Fraction]) -> Fraction:
    """The weight of the independent evidence among `candidates`: per source kind, its best candidate's weight."""
    best: dict[SourceKind, Fraction] = {}
    for c in candidates:
        if c.independent:
            best[c.source_kind] = max(best.get(c.source_kind, _NONE), weights[id(c)])
    return sum(best.values(), _NONE)


def _grouped(spec: FieldSpec, kept: Sequence[Candidate]) -> list[list[int]]:
    """The kept candidates' places, by value: equal keys (`equality_key`) or files (`resource_key`) meet in one pass;
    a value with neither joins the first group whose first value it equals (the location type's equality is not
    transitive, schemas spec)."""
    groups: list[list[int]] = []
    by_key: dict[Hashable, list[int]] = {}
    for i, candidate in enumerate(kept):
        key = _key(candidate, spec)
        if key is not None:
            if key not in by_key:
                by_key[key] = []
                groups.append(by_key[key])
            by_key[key].append(i)
            continue
        group = next((g for g in groups if same_value(kept[g[0]], candidate, spec)), None)
        if group is None:
            groups.append([i])
        else:
            group.append(i)
    return groups


def _key(candidate: Candidate, spec: FieldSpec) -> Hashable | None:
    value = value_of(candidate)
    if rule_type(spec) is FieldType.IMAGE_URL and (file := resource_key(value, spec)) is not None:
        return ("file", file)
    key = equality_key(value, spec)
    return None if key is None else ("value", key)


def same_value(a: Candidate, b: Candidate, spec: FieldSpec) -> bool:
    """Whether two kept candidates state one value: equal, or image values naming the same files."""
    if equal(value_of(a), value_of(b), spec):
        return True
    keys = {resource_key(value_of(c), spec) for c in (a, b)}
    return len(keys) == 1 and None not in keys


def rule_type(spec: FieldSpec) -> FieldType:
    # A list's values are its items', so it weighs as its item type does; an object agrees as a whole.
    return spec.item.type if spec.type is FieldType.LIST and spec.item is not None else spec.type


def value_of(candidate: Candidate) -> JsonValue:
    if not isinstance(candidate.normalized, Ok):
        raise TypeError("only kept candidates are scored")
    return candidate.normalized.value


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
