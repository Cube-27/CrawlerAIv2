"""Properties of the metric table (SPEC-03 §4.6, §4.7) over generated label/output pairs: each field lands in the
cell its construction says, the ratios follow from the cells, page and row order don't matter, and the exported
aggregate suppresses every small cell and carries no host (INV-01)."""

import random
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal, get_args

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.eval.labels import Labels, ScalarShape, ScalarType
from crawlerai.eval.metrics import (
    MIN_CELL,
    EvalCase,
    FieldMetrics,
    FieldOutput,
    PageOutput,
    Report,
    SchemaFields,
    Suppressed,
    build_report,
    export_aggregate,
)

Behaviour = Literal["right", "wrong", "distractor", "abstain"]

# Values are URLs on reserved hosts, so a leak of any label or output value into an aggregate is visible.
_HOST = re.compile(r"[a-z0-9-]+\.(?:example|test)\b")


@dataclass(frozen=True)
class FieldCase:
    type_: ScalarType
    present: bool
    behaviour: Behaviour

    @property
    def cell(self) -> str:
        if self.behaviour == "abstain" or (not self.present and self.behaviour == "right"):
            return "FN" if self.present else "TN"
        return "TP" if self.behaviour == "right" else "FP"


_field = st.builds(
    FieldCase,
    st.sampled_from(get_args(ScalarType)),
    st.booleans(),
    st.sampled_from(get_args(Behaviour)),
)


def _value(page: int, field: int, kind: str) -> str:
    return f"https://h{page}.example.test/{field}/{kind}"


def _case(page: int, fields: list[FieldCase], category: str) -> EvalCase:
    schema = SchemaFields(
        name="synthetic",
        page_kind="detail",
        fields={f"f{i}": ScalarShape(type=f.type_) for i, f in enumerate(fields)},
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


def _build(pages: list[tuple[list[FieldCase], str]], split: str = "dev") -> Report:
    cases = [_case(i, fields, category) for i, (fields, category) in enumerate(pages)]
    return build_report(cases, split, engine_version="e1", git_sha="abc")  # type: ignore[arg-type]


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


@given(_pages)
def test_each_field_lands_in_its_cell(pages: list[tuple[list[FieldCase], str]]) -> None:
    report = _build(pages)

    assert report.pages is not None
    expected = [(f"f{i}", f.cell) for fields, _ in pages for i, f in enumerate(fields)]
    assert [(j.field, j.cell) for p in report.pages for j in p.judgments] == expected


@given(_pages)
def test_ratios_follow_from_the_cells(pages: list[tuple[list[FieldCase], str]]) -> None:
    report = _build(pages)

    fields = [f for fs, _ in pages for f in fs]
    for type_ in {f.type_ for f in fields}:
        of_type = [f for f in fields if f.type_ == type_]
        c = Counter(f.cell for f in of_type)
        fp_absent = sum(f.cell == "FP" and not f.present for f in of_type)
        assert report.by_field_type[type_] == FieldMetrics(
            precision=_ratio(c["TP"], c["TP"] + c["FP"]),
            coverage=_ratio(c["TP"], c["TP"] + c["FN"]),
            abstain_rate=_ratio(c["FN"] + c["TN"], len(of_type)),
            false_publish_on_absent=_ratio(fp_absent, fp_absent + c["TN"]),
            wrong_product=sum(f.behaviour == "distractor" for f in of_type),
            n=len(of_type),
        )
    assert set(report.by_field_type) == {f.type_ for f in fields}


@given(_pages)
def test_a_page_is_zero_touch_when_its_required_field_is_tp(pages: list[tuple[list[FieldCase], str]]) -> None:
    report = _build(pages)

    assert report.pages is not None
    assert [p.zero_touch for p in report.pages] == [fields[0].cell == "TP" for fields, _ in pages]


@given(_pages, st.randoms())
def test_page_order_does_not_matter(pages: list[tuple[list[FieldCase], str]], rnd: random.Random) -> None:
    cases = [_case(i, fields, category) for i, (fields, category) in enumerate(pages)]
    shuffled = list(cases)
    rnd.shuffle(shuffled)

    a = build_report(cases, "dev", engine_version="e1", git_sha="abc")
    b = build_report(shuffled, "dev", engine_version="e1", git_sha="abc")
    assert a.model_dump_json() == b.model_dump_json()


@given(_pages, st.sampled_from(["hidden", "fresh"]))
def test_aggregate_suppresses_small_cells_and_names_no_host(
    pages: list[tuple[list[FieldCase], str]], split: str
) -> None:
    report = _build(pages, split)
    aggregate = export_aggregate(report)

    assert aggregate.pages is None
    assert aggregate.n_pages == report.n_pages
    # Per-(schema, field) cells stay in the job; the in-job report keeps them for the gate.
    assert aggregate.by_field == {}
    assert report.by_field.keys() == {f"synthetic|f{i}" for fields, _ in pages for i in range(len(fields))}
    for table in ("by_field_type", "by_bucket", "by_config_status", "by_category", "usage"):
        full, out = getattr(report, table), getattr(aggregate, table)
        assert out.keys() == full.keys()
        for key, cell in out.items():
            assert cell == (Suppressed(n=full[key].n) if full[key].n < MIN_CELL else full[key])
    for key, cell in aggregate.acquisition.items():
        assert cell == (Suppressed(n=cell.n) if isinstance(cell, Suppressed) else report.acquisition[key])
    assert _HOST.search(aggregate.model_dump_json()) is None
