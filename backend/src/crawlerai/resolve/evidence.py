"""Evidence, calibration and τ (SPEC-05 §4.9, ARCHITECTURE §10, INV-22): what a field's choice becomes.

Preference chose a value, or declined (`resolve.preference`). Here a chosen value gets its evidence bucket, the
bucket's precision measured on dev as its confidence, and the `calibrated` flag; a calibrated bucket below τ abstains.
An uncalibrated bucket publishes with `calibrated=false` (§10: a deliberate trade-off for progressive cold mode).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.collect.locator import format_locator
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.derive import Derived
from crawlerai.resolve.preference import Chosen, Preference
from crawlerai.resolve.types import Derivation, Evidence, FieldOutcome, FieldSet, Probability
from crawlerai.schemas.types import FieldType, SchemaDef

# ARCHITECTURE §10, OPEN_QUESTIONS #3: a calibrated bucket below τ abstains.
TAU_REQUIRED: Final = 0.97
TAU_OPTIONAL: Final = 0.95
# A bucket with fewer than 20 dev labels reports `calibrated=false` (owner-delegated, D-1740: ARCHITECTURE §10 said 30).
MIN_CALIBRATED_N: Final = 20
# ARCHITECTURE §10 buckets by source kind: an adapter or an API recipe; one structured-data standard (schema.org
# JSON-LD and microdata, the Open Graph protocol); a structural DOM value (§8.1), which follows no structured-data
# standard; a value of the page's captured calls, the network data-source layer (Appendix A #59); role C's grounded
# values. A config value's bucket is its field status; js_state has none.
_ADAPTER: frozenset[SourceKind] = frozenset({"adapter", "api"})
_BUCKET: Mapping[SourceKind, Evidence] = {
    "jsonld": "structured",
    "microdata": "structured",
    "og": "structured",
    "dom": "dom",
    "xhr": "network",
    "llm": "llm_grounded",
}


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Bucket(_Model):
    n: int = Field(ge=0)  # published fields of the bucket in the dev run
    precision: Probability | None  # `None` when no labeled field measured it


class Calibration(_Model):
    """`backend/data/calibration.json`: per `"field_type|evidence"` bucket, its fitted golden-set confidence
    (`eval.calibrate`); a bucket the fit lacked is not in it, so uncalibrated."""

    calibration_version: Literal[1] = 1
    source_split: Literal["dev"] = "dev"
    git_sha: str
    buckets: dict[str, Bucket]

    def measure(self, type_: FieldType, evidence: Evidence, *, row: bool = False) -> tuple[float | None, bool]:
        """The bucket's confidence and whether it is calibrated: measured on at least `MIN_CALIBRATED_N` fields. A row
        sub-field's bucket is `list.<type>|<evidence>` (SPEC-13 §4.5): a row value can be wrong in a way a page value
        cannot (a wrong row match), so it is measured apart."""
        bucket = self.buckets.get(f"{'list.' if row else ''}{type_.value}|{evidence}")
        if bucket is None:
            return None, False
        return bucket.precision, bucket.precision is not None and bucket.n >= MIN_CALIBRATED_N


def load_calibration(path: Path) -> Calibration | None:
    """The calibration at `path`, stamped `source_split: dev`; `None` when none was fitted, so every bucket is
    uncalibrated, as `core.engine_version` reports it (`cal.none`)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return Calibration.model_validate_json(text)


def evidence_of(chosen: Candidate, agreeing: tuple[Candidate, ...], *, corroborated: bool) -> Evidence | None:
    """The §10 bucket of a published value, `adapter` > `agreed` > the chosen kind's bucket (D-0021). `corroborated`
    is the config's field status (SPEC-08); `None` when no bucket holds the value (a lone js_state value)."""
    if chosen.source_kind in _ADAPTER:
        return "adapter"
    # §8.1, §10: only independent candidates count, so a state value admitted by equality never agrees with itself.
    if len({c.source_kind for c in (chosen, *agreeing) if c.independent}) >= 2:
        return "agreed"
    if chosen.source_kind == "config":
        return "config_corroborated" if corroborated else "config_uncorroborated"
    return _BUCKET.get(chosen.source_kind)


def required_fields(schema: SchemaDef) -> frozenset[str]:
    """The fields a record needs (§10 "Incomplete pages"): required ones, and every member of a required group."""
    grouped = {name for group in schema.required_groups for name in group}
    return frozenset(name for name, spec in schema.fields.items() if spec.required) | grouped


def assess_fields(
    schema: SchemaDef,
    decisions: Mapping[str, Preference | Derived],
    calibration: Calibration | None,
    corroborated: frozenset[str],
) -> FieldSet:
    """Every schema field's outcome, from its preference (or derivation) and the calibration."""
    required = required_fields(schema)
    return {
        name: assess(
            spec.type,
            decisions[name],
            calibration,
            tau=TAU_REQUIRED if name in required else TAU_OPTIONAL,
            corroborated=name in corroborated,
        )
        for name, spec in schema.fields.items()
    }


def assess(
    type_: FieldType,
    decision: Preference | Derived,
    calibration: Calibration | None,
    *,
    tau: float,
    corroborated: bool,
    row: bool = False,
) -> FieldOutcome:
    """One field's outcome: a chosen or derived value publishes with its bucket's measurement unless that bucket is
    calibrated below `tau`; a declined field keeps its status and reason. `row`: a row sub-field (SPEC-13 §4.5)."""
    if isinstance(decision, Derived) and decision.source is None:
        published = _page_url(decision)
    else:
        candidate = _candidate_value(decision, corroborated=corroborated)
        if isinstance(candidate, FieldOutcome):
            return candidate
        published = candidate
    confidence, calibrated = calibration.measure(type_, published.evidence, row=row) if calibration else (None, False)
    if calibrated and confidence is not None and confidence < tau:
        below = () if published.chosen is None else ((published.chosen, "below_tau"),)
        return _unpublished(
            "abstained",
            "below_tau",
            (*published.rejected, *below),
            kept=published.kept,
            evidence=published.evidence,
            confidence=confidence,
            calibrated=True,
        )
    return FieldOutcome(
        status="published",
        reason=None,
        value=published.value,
        evidence=published.evidence,
        confidence=confidence,
        calibrated=calibrated,
        source_kind=published.source_kind,
        locator=published.locator,
        derived_by=published.derived_by,
        chosen=published.chosen,
        kept=published.kept,
        rejected=published.rejected,
    )


@dataclass(frozen=True, slots=True)
class _Published:
    """A value about to publish, with its provenance (INV-22); its bucket is measured and held to τ next."""

    value: JsonValue
    evidence: Evidence
    source_kind: SourceKind
    locator: str
    derived_by: Derivation | None
    chosen: Candidate | None
    kept: tuple[Candidate, ...]
    rejected: tuple[tuple[Candidate, str], ...]


def _page_url(decision: Derived) -> _Published:
    # D-0355: no candidate states a page-URL derivation, so it carries the `derived` source kind and bucket and a
    # `derived:` locator naming the derivation.
    locator = format_locator("derived", decision.derived_by)
    return _Published(decision.value, "derived", "derived", locator, decision.derived_by, None, (), ())


def _candidate_value(decision: Preference | Derived, *, corroborated: bool) -> _Published | FieldOutcome:
    """A chosen candidate's value, or an absolutized one with its source candidate's provenance; else the field's
    unpublished outcome."""
    derived_by: Derivation | None = None
    if isinstance(decision, Derived):
        if decision.source is None:
            raise TypeError("a page-URL derivation has no candidate")
        value, derived_by = decision.value, decision.derived_by
        # The source is another field's candidate: none of this field's passed screening.
        decision = Chosen(decision.source, (), (), kept=())
    elif isinstance(decision, Chosen):
        value = _value(decision.candidate)
    else:
        return _unpublished(decision.status, decision.reason, decision.rejected, kept=decision.kept)
    chosen, rejected = decision.candidate, decision.rejected
    evidence = evidence_of(chosen, decision.agreeing, corroborated=corroborated)
    if evidence is None:
        return _unpublished("abstained", "no_bucket", (*rejected, (chosen, "no_bucket")), kept=decision.kept)
    return _Published(value, evidence, chosen.source_kind, chosen.locator, derived_by, chosen, decision.kept, rejected)


def _unpublished(
    status: Literal["missing", "conflict", "abstained"],
    reason: str,
    rejected: tuple[tuple[Candidate, str], ...],
    *,
    kept: tuple[Candidate, ...] = (),
    evidence: Evidence | None = None,
    confidence: float | None = None,
    calibrated: bool = False,
) -> FieldOutcome:
    # No value and none of a published value's provenance; an abstention keeps the measurement that caused it.
    return FieldOutcome(
        status=status,
        reason=reason,
        value=None,
        evidence=evidence,
        confidence=confidence,
        calibrated=calibrated,
        source_kind=None,
        locator=None,
        derived_by=None,
        chosen=None,
        kept=kept,
        rejected=rejected,
    )


def _value(chosen: Candidate) -> JsonValue:
    # Preference chooses only candidates that normalized (validity, §10).
    if not isinstance(chosen.normalized, Ok):
        raise TypeError("only a normalized candidate publishes")
    return chosen.normalized.value
