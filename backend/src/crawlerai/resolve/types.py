"""What resolution returns (resolution spec): one outcome per schema field, and the result of one page.

The models hold INV-22: every published field carries `evidence`, `confidence`, `calibrated`, `source_kind` and
`locator`. Its confidence is its bucket's dev precision, so it is `None` only while the bucket has no dev measurement,
and then the field is `calibrated=false` (§10: uncalibrated buckets publish with the flag set). An unpublished field
holds no value and says why (§10 "Incomplete pages").
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from crawlerai.collect.base import Candidate
from crawlerai.collect.locator import LocatorText, PageUrlDerivation
from crawlerai.db.models import ExtractionMode, SourceKind
from crawlerai.normalize.base import Basis

# Evidence buckets.
Evidence = Literal[
    "adapter",
    "structured",
    "agreed",
    "dom",
    "network",
    "state",
    "config_corroborated",
    "config_uncorroborated",
    "llm_grounded",
    "derived",
]
FieldStatus = Literal["published", "missing", "conflict", "abstained"]
# resolution spec: the derivations core has, each a named function in `resolve/derive.py`.
Derivation = Literal[PageUrlDerivation, "absolutize"]
# `url_task.outcome` (§6), except that `error` is stored as `failed`.
Outcome = Literal["extracted", "partial", "no_match", "blocked", "shell", "not_found", "error"]
# Outcomes of a page that was not served (INV-11): no candidates and nothing published.
_NOT_SERVED: frozenset[Outcome] = frozenset({"blocked", "shell", "not_found"})
# Those, and a page whose resolution failed (§4.14): nothing is published.
_UNPUBLISHED: frozenset[Outcome] = _NOT_SERVED | {"error"}
# A probability: a bucket's measured precision (§4.9).
Probability = Annotated[float, Field(ge=0.0, le=1.0)]
# The attributes INV-22 requires of a published field; `confidence` is checked with `calibrated`.
_PUBLISHED_REQUIRES = ("value", "evidence", "source_kind", "locator")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldOutcome(_Model):
    """One field's outcome. A row-mapped field (variants spec) also holds `items`, one per published row in the order of
    `value`, and `dropped`, the rows that did not publish; every other field holds neither."""

    status: FieldStatus
    reason: str | None  # why the field is not published: `invalid`, `not_owned`, `below_tau`, `disagree`, ...
    value: JsonValue
    evidence: Evidence | None
    confidence: Probability | None
    calibrated: bool
    source_kind: SourceKind | None
    locator: LocatorText | None
    derived_by: Derivation | None
    chosen: Candidate | None
    # A published money value's weaker currency evidence (`Ok.basis`: `page`, `locale`, `unknown`), noted; else None.
    basis: Basis | None = None
    kept: tuple[Candidate, ...] = ()  # the candidates that passed screening (validity, ownership, INV-13)
    rejected: tuple[tuple[Candidate, str], ...]  # each with its reject reason
    items: "tuple[RowOutcome, ...] | None" = None
    dropped: "tuple[DroppedRow, ...] | None" = None

    @model_validator(mode="after")
    def _status_fits(self) -> Self:
        if self.status == "published":
            self._check_published()
        else:
            self._check_unpublished()
        if self.calibrated and self.confidence is None:
            raise ValueError("a calibrated field has a confidence")
        if self.items is not None and len(self.items) != (len(self.value) if isinstance(self.value, list) else 0):
            raise ValueError("a row-mapped field has one item per published row")
        return self

    def _check_published(self) -> None:
        for name in _PUBLISHED_REQUIRES:
            if getattr(self, name) is None:
                raise ValueError(f"a published field carries {name} (INV-22)")

    def _check_unpublished(self) -> None:
        if self.value is not None:
            raise ValueError(f"a {self.status} field holds no value")
        if self.reason is None:
            raise ValueError(f"a {self.status} field states its reason")


class RowOutcome(_Model):
    """A published row of a row-mapped field (variants spec, INV-34): every sub-field's outcome, published or not."""

    fields: dict[str, FieldOutcome]


class DroppedRow(_Model):
    """A row of a row-mapped field that did not publish: its row entities' locators, and why (variants spec)."""

    locators: tuple[LocatorText, ...]
    reason: str


FieldOutcome.model_rebuild()


# One entity's fields, by schema field name.
FieldSet = dict[str, FieldOutcome]


class LLMCallRecord(_Model):
    """One LLM call of the page, as `extraction.llm_calls` records it (llm spec)."""

    prompt_kind: str
    provider: str
    model: str
    request_hash: str
    tokens_in: int  # not served from, or written to, the provider's prompt cache
    tokens_out: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ExtractionResult(_Model):
    outcome: Outcome
    entity: FieldSet | None  # detail: the one entity; listing: the page-level fields
    rows: tuple[FieldSet, ...]  # listing rows
    candidates: tuple[Candidate, ...]
    llm_calls: tuple[LLMCallRecord, ...]
    mode: ExtractionMode
    record_confidence: Probability | None
    # What the collectors skipped and why (§4.14), for the page's log.
    diagnostics: tuple[str, ...] = ()
    # A listing's next-page candidates (§4.12), for the crawl frontier (jobs spec).
    next_pages: tuple[str, ...] = ()
    # Why a listing gave no rows (`no_rows` in `resolve.pipeline`); None for a listing with rows and for a detail page.
    reason: str | None = None
    # Per row item URL field, the query parameters its values were rid of (`resolve.row_keys`), for matching labels.
    session_params: dict[str, tuple[str, ...]] = {}

    @model_validator(mode="after")
    def _outcome_fits(self) -> Self:
        if self.outcome in _UNPUBLISHED and (self.entity is not None or self.rows):
            raise ValueError(f"a {self.outcome} page has no fields")
        # INV-11: a page that was not served yields no candidates; an `error` keeps its candidates for diagnostics.
        if self.outcome in _NOT_SERVED and self.candidates:
            raise ValueError(f"a {self.outcome} page has no candidates")
        return self
