"""Evidence, calibration and τ (SPEC-05 §4.9, ARCHITECTURE §10, INV-02, INV-22): what a field's choice becomes.

Preference chose a value, or declined (`resolve.preference`). Here a chosen value gets its evidence bucket, the
bucket's precision measured on dev as its confidence, and the `calibrated` flag; a calibrated bucket below τ abstains.
An uncalibrated bucket publishes with `calibrated=false` (§10: a deliberate trade-off for progressive cold mode).
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.db.models import EvalRunId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.derive import Derived
from crawlerai.resolve.preference import Chosen, Preference
from crawlerai.resolve.types import Derivation, Evidence, FieldOutcome, FieldSet, Probability
from crawlerai.schemas.types import FieldType, SchemaDef

# ARCHITECTURE §10, OPEN_QUESTIONS #3: a calibrated bucket below τ abstains.
TAU_REQUIRED: Final = 0.97
TAU_OPTIONAL: Final = 0.95
# ARCHITECTURE §10: a bucket with fewer than 30 dev labels reports `calibrated=false`.
MIN_CALIBRATED_N: Final = 30
# ARCHITECTURE §10 buckets by source kind: an adapter or an API recipe; one structured-data standard (schema.org
# JSON-LD and microdata, the Open Graph protocol); role C's grounded values.
_ADAPTER: frozenset[SourceKind] = frozenset({"adapter", "api"})
_STRUCTURED: frozenset[SourceKind] = frozenset({"jsonld", "microdata", "og"})


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Bucket(_Model):
    n: int = Field(ge=0)  # published fields of the bucket in the dev run
    precision: Probability | None  # `None` when no labeled field measured it


class Calibration(_Model):
    """`backend/data/calibration.json`: per `"field_type|evidence"` bucket, its dev measurement (INV-02)."""

    calibration_version: Literal[1] = 1
    source_split: Literal["dev"] = "dev"
    eval_run_id: EvalRunId
    git_sha: str
    buckets: dict[str, Bucket]

    def measure(self, type_: FieldType, evidence: Evidence) -> tuple[float | None, bool]:
        """The bucket's confidence and whether it is calibrated: measured on at least `MIN_CALIBRATED_N` fields."""
        bucket = self.buckets.get(f"{type_.value}|{evidence}")
        if bucket is None:
            return None, False
        return bucket.precision, bucket.precision is not None and bucket.n >= MIN_CALIBRATED_N


def load_calibration(path: Path) -> Calibration | None:
    """The calibration at `path`, stamped `source_split: dev` (INV-02); `None` when none was fitted, so every bucket is
    uncalibrated, as `core.engine_version` reports it (`cal.none`)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return Calibration.model_validate_json(text)


def evidence_of(chosen: Candidate, agreeing: tuple[Candidate, ...], *, corroborated: bool) -> Evidence | None:
    """The §10 bucket of a published value, `adapter` > `agreed` > the chosen kind's bucket (D-0021). `corroborated`
    is the config's field status (SPEC-08); `None` when no bucket holds the value (a lone js_state or xhr value)."""
    if chosen.source_kind in _ADAPTER:
        return "adapter"
    # §8.1, §10: only independent candidates count, so a state value admitted by equality never agrees with itself.
    if len({c.source_kind for c in (chosen, *agreeing) if c.independent}) >= 2:
        return "agreed"
    if chosen.source_kind in _STRUCTURED:
        return "structured"
    if chosen.source_kind == "config":
        return "config_corroborated" if corroborated else "config_uncorroborated"
    if chosen.source_kind == "llm":
        return "llm_grounded"
    return None


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
) -> FieldOutcome:
    """One field's outcome: a chosen or derived value publishes with its bucket's measurement unless that bucket is
    calibrated below `tau`; a declined field keeps its status and reason."""
    derived_by: Derivation | None = None
    if isinstance(decision, Derived):
        if decision.source is None:
            # D-0355: a page-URL derivation has no candidate, source kind or bucket, which INV-22 requires.
            return _unpublished("missing", "no_provenance", ())
        value, derived_by = decision.value, decision.derived_by
        decision = Chosen(decision.source, (), ())
    elif isinstance(decision, Chosen):
        value = _value(decision.chosen)
    else:
        return _unpublished(decision.status, decision.reason, decision.rejected, kept=decision.kept)
    chosen, rejected = decision.chosen, decision.rejected
    evidence = evidence_of(chosen, decision.agreeing, corroborated=corroborated)
    if evidence is None:
        return _unpublished("abstained", "no_bucket", (*rejected, (chosen, "no_bucket")), kept=decision.kept)
    confidence, calibrated = calibration.measure(type_, evidence) if calibration else (None, False)
    if calibrated and confidence is not None and confidence < tau:
        return _unpublished(
            "abstained",
            "below_tau",
            (*rejected, (chosen, "below_tau")),
            kept=decision.kept,
            evidence=evidence,
            confidence=confidence,
            calibrated=True,
        )
    return FieldOutcome(
        status="published",
        reason=None,
        value=value,
        evidence=evidence,
        confidence=confidence,
        calibrated=calibrated,
        source_kind=chosen.source_kind,
        locator=chosen.locator,
        derived_by=derived_by,
        chosen=chosen,
        kept=decision.kept,
        rejected=rejected,
    )


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
