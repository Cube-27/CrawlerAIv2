"""Properties of the metric table (evaluation spec, "Replay harness and metrics") over generated label/output pairs:
each field lands in the cell its construction says, the ratios follow from the cells, and page and row order don't
matter."""

import random
from collections import Counter
from dataclasses import dataclass
from typing import Literal, get_args

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.eval.labels import Labels
from crawlerai.eval.metrics import (
    EvalCase,
    FieldMetrics,
    FieldOutput,
    PageOutput,
    Report,
    SchemaFields,
    build_report,
)
from crawlerai.schemas.types import FieldSpec, FieldType

Behaviour = Literal["right", "wrong", "distractor", "abstain"]

# Values are URLs on reserved hosts, so a leak of any label or output value into an aggregate is visible.


@dataclass(frozen=True)
class FieldCase:
    type_: FieldType
    present: bool
    behaviour: Behaviour

    @property
    def cell(self) -> str:
        if self.behaviour == "abstain" or (not self.present and self.behaviour == "right"):
            return "FN" if self.present else "TN"
        return "TP" if self.behaviour == "right" else "FP"


_field = st.builds(
    FieldCase,
    st.sampled_from([t for t in FieldType if t not in (FieldType.LIST, FieldType.OBJECT)]),
    st.booleans(),
    st.sampled_from(get_args(Behaviour)),
)


# The parameters a type needs (SPEC-04 §4.2).
_PARAMETERS: dict[FieldType, dict[str, str]] = {
    FieldType.ENUM: {"vocab": "schema:ItemAvailability"},
    FieldType.IDENTIFIER: {"scheme": "sku"},
}


def _spec(type_: FieldType) -> FieldSpec:
    return FieldSpec.model_validate({"type": type_, **_PARAMETERS.get(type_, {})})


def _value(page: int, field: int, kind: str) -> str:
    return f"https://h{page}.example.test/{field}/{kind}"


def _case(page: int, fields: list[FieldCase], category: str) -> EvalCase:
    schema = SchemaFields(
        name="synthetic",
        page_kind="detail",
        fields={f"f{i}": _spec(f.type_) for i, f in enumerate(fields)},
        required=frozenset({"f0"}),
    )
    labels: dict[str, object] = {}
    output: dict[str, FieldOutput] = {}
    for i, f in enumerate(fields):
        right, distractor = _value(page, i, "right"), _value(page, i, "distractor")
        labels[f"f{i}"] = {
            "value": right if f.present else None,
            "absent": not f.present,
            "distractors": [distractor],
        }
        if f.cell in ("FN", "TN"):
            output[f"f{i}"] = FieldOutput(status="abstained")
        else:
            value = {"right": right, "wrong": _value(page, i, "wrong"), "distractor": distractor}[f.behaviour]
            output[f"f{i}"] = FieldOutput(status="published", value=value, evidence="structured")
    return EvalCase(
        page_id=f"page-{page:03}",
        category=category,  # type: ignore[arg-type]
        schema_def=schema,
        labels=Labels.model_validate(
            {"label_version": 1, "status": "checked", "labeler": "a", "checker": "b", "fields": labels}
        ),
        output=PageOutput(block_class="ok", mode="adhoc", fields=output),
    )


_pages = st.lists(
    st.tuples(st.lists(_field, min_size=1, max_size=4), st.sampled_from(["custom_store", "mixed"])),
    min_size=1,
    max_size=25,
)


def _build(pages: list[tuple[list[FieldCase], str]]) -> Report:
    cases = [_case(i, fields, category) for i, (fields, category) in enumerate(pages)]
    return build_report(cases, "dev", engine_version="e1", git_sha="abc")


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _metrics(of_type: list[FieldCase]) -> FieldMetrics:
    """A field type's metrics, counted from its fields' cells (SPEC-03 §4.6)."""
    c = Counter(f.cell for f in of_type)
    fp_absent = sum(f.cell == "FP" and not f.present for f in of_type)
    return FieldMetrics(
        precision=_ratio(c["TP"], c["TP"] + c["FP"]),
        coverage=_ratio(c["TP"], c["TP"] + c["FN"]),
        abstain_rate=_ratio(c["FN"] + c["TN"], len(of_type)),
        false_publish_on_absent=_ratio(fp_absent, fp_absent + c["TN"]),
        wrong_product=sum(f.behaviour == "distractor" for f in of_type),
        n=len(of_type),
    )


@given(_pages, st.randoms())
def test_each_field_lands_in_its_cell_and_the_ratios_follow_whatever_the_page_order(
    pages: list[tuple[list[FieldCase], str]], rnd: random.Random
) -> None:
    cases = [_case(i, fields, category) for i, (fields, category) in enumerate(pages)]
    report = build_report(cases, "dev", engine_version="e1", git_sha="abc")

    assert report.pages is not None
    expected = [(f"f{i}", f.cell) for fields, _ in pages for i, f in enumerate(fields)]
    assert [(j.field, j.cell) for p in report.pages for j in p.judgments] == expected
    # A page is zero-touch when its required field is TP.
    assert [p.zero_touch for p in report.pages] == [fields[0].cell == "TP" for fields, _ in pages]
    fields = [f for fs, _ in pages for f in fs]
    assert report.by_field_type == {t: _metrics([f for f in fields if f.type_ == t]) for t in {f.type_ for f in fields}}
    shuffled = list(cases)
    rnd.shuffle(shuffled)
    reordered = build_report(shuffled, "dev", engine_version="e1", git_sha="abc")
    assert reordered.model_dump_json() == report.model_dump_json()
