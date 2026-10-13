"""What resolution returns (SPEC-05 §4.2): one outcome per schema field, and the result of one page.

The models hold INV-22: every published field carries `evidence`, `confidence`, `calibrated`, `source_kind` and
`locator`. Its confidence is its bucket's dev precision, so it is `None` only while the bucket has no dev measurement,
and then the field is `calibrated=false` (§10: uncalibrated buckets publish with the flag set). An unpublished field
holds no value and says why (§10 "Incomplete pages").
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from crawlerai.collect.base import Candidate
from crawlerai.collect.locator import LocatorText
from crawlerai.db.models import ExtractionMode, SourceKind

# ARCHITECTURE §10 evidence buckets.
Evidence = Literal["adapter", "structured", "agreed", "config_corroborated", "config_uncorroborated", "llm_grounded"]
FieldStatus = Literal["published", "missing", "conflict", "abstained"]
# SPEC-05 §4.8: the derivations core has, each a named function in `resolve/derive.py`.
Derivation = Literal["canonical_link", "final_url", "absolutize"]
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
    rejected: tuple[tuple[Candidate, str], ...]  # each with its reject reason

    @model_validator(mode="after")
    def _status_fits(self) -> Self:
        if self.status == "published":
            for name in _PUBLISHED_REQUIRES:
                if getattr(self, name) is None:
                    raise ValueError(f"a published field carries {name} (INV-22)")
        else:
            if self.value is not None:
                raise ValueError(f"a {self.status} field holds no value")
            if self.reason is None:
                raise ValueError(f"a {self.status} field states its reason")
        if self.calibrated and self.confidence is None:
            raise ValueError("a calibrated field has a confidence")
        return self


# One entity's fields, by schema field name.
FieldSet = dict[str, FieldOutcome]


class LLMCallRecord(_Model):
    """One LLM call of the page, as `extraction.llm_calls` records it (SPEC-06 §4.2)."""

    prompt_kind: str
    provider: str
    model: str
    request_hash: str
    tokens_in: int
    tokens_out: int


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
    # A listing's next-page candidates (§4.12), for the crawl frontier (SPEC-10 §4.5).
    next_pages: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _outcome_fits(self) -> Self:
        if self.outcome in _UNPUBLISHED and (self.entity is not None or self.rows):
            raise ValueError(f"a {self.outcome} page has no fields")
        # INV-11: a page that was not served yields no candidates; an `error` keeps its candidates for diagnostics.
        if self.outcome in _NOT_SERVED and self.candidates:
            raise ValueError(f"a {self.outcome} page has no candidates")
        return self
