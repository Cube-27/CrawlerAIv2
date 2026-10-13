"""Properties of the metric table (SPEC-03 §4.6, §4.7) over generated label/output pairs: each field lands in the
cell its construction says, the ratios follow from the cells, page and row order don't matter, and the exported
aggregate suppresses every small cell, complements a lone suppressed cell in its group, and carries no host (INV-01,
INV-25)."""

import random
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, get_args

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.eval.labels import Labels
from crawlerai.eval.metrics import (
    MIN_CELL,
    EvalCase,
    FieldMetrics,
    FieldOutput,
    PageOutput,
    PrecisionMetrics,
    Report,
    SchemaFields,
    Suppressed,
    Usage,
    ZeroTouch,
    build_report,
    export_aggregate,
)
from crawlerai.resolve.types import Evidence
from crawlerai.schemas.types import FieldSpec, FieldType

Behaviour = Literal["right", "wrong", "distractor", "abstain"]

# Values are URLs on reserved hosts, so a leak of any label or output value into an aggregate is visible.
_HOST = re.compile(r"[a-z0-9-]+\.(?:example|test)\b")


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
            # Complementary suppression may hide a cell of 10 or more as well (D-0234); its exact rule is tested below.
            assert cell in (Suppressed(n=full[key].n), full[key])
            assert full[key].n >= MIN_CELL or isinstance(cell, Suppressed)
    for key, cell in aggregate.acquisition.items():
        assert cell == (Suppressed(n=cell.n) if isinstance(cell, Suppressed) else report.acquisition[key])
    assert _HOST.search(aggregate.model_dump_json()) is None


_n = st.integers(min_value=0, max_value=30)


def _keyed(left: list[str], right: list[str]) -> st.SearchStrategy[dict[str, int]]:
    return st.dictionaries(st.tuples(st.sampled_from(left), st.sampled_from(right)).map("|".join), _n)


_TYPES = ["money", "text", "url"]
_EVIDENCE: list[str] = list(get_args(Evidence))
_STATUSES = ["corroborated", "uncorroborated", "operator", "suspended"]


@given(
    _keyed(_TYPES, _EVIDENCE),
    _keyed(_TYPES, _STATUSES),
    st.dictionaries(st.sampled_from(["platform_store", "custom_store", "api_backed", "job_board", "mixed"]), _n),
    st.dictionaries(st.sampled_from(["adhoc", "config"]), _n),
    st.sampled_from(["hidden", "fresh"]),
)
def test_no_suppressed_cell_is_derivable_from_its_group(
    buckets: dict[str, int], statuses: dict[str, int], categories: dict[str, int], modes: dict[str, int], split: str
) -> None:
    report = _cell_report(buckets, statuses, categories, modes, split)
    aggregate = export_aggregate(report)

    # Bucket and config-status cells sum to their field type's cell; category and usage cells sum to `n_pages`.
    groups: list[tuple[str, Callable[[str], str]]] = [
        ("by_bucket", lambda k: k.split("|")[0]),
        ("by_config_status", lambda k: k.split("|")[0]),
        ("by_category", lambda _: ""),
        ("usage", lambda _: ""),
    ]
    for table, group_of in groups:
        full: Mapping[str, PrecisionMetrics | ZeroTouch | Usage] = getattr(report, table)
        out: Mapping[str, object] = getattr(aggregate, table)
        for group in {group_of(k) for k in full}:
            _assert_group_suppressed(full, out, [k for k in full if group_of(k) == group])
    assert _suppressed(aggregate.acquisition) == _suppressed(aggregate.by_category)


def _cell_report(
    buckets: dict[str, int], statuses: dict[str, int], categories: dict[str, int], modes: dict[str, int], split: str
) -> Report:
    return Report.model_validate(
        {
            "engine_version": "e1",
            "git_sha": "abc",
            "split": split,
            "n_pages": sum(categories.values()),
            "by_field_type": {},
            "by_field": {},
            "by_bucket": {k: PrecisionMetrics(precision=0.5, n=n) for k, n in buckets.items()},
            "by_config_status": {k: PrecisionMetrics(precision=0.5, n=n) for k, n in statuses.items()},
            "by_category": {k: ZeroTouch(zero_touch=0.5, n=n) for k, n in categories.items()},
            "acquisition": {k: {"ok": n} for k, n in categories.items()},
            "usage": {k: Usage(llm_calls_per_1k_pages=1.0, n=n) for k, n in modes.items()},
        }
    )


def _suppressed(cells: Mapping[str, object]) -> set[str]:
    return {k for k, v in cells.items() if isinstance(v, Suppressed)}


def _assert_group_suppressed(
    full: Mapping[str, PrecisionMetrics | ZeroTouch | Usage], out: Mapping[str, object], keys: list[str]
) -> None:
    """The cells `keys` of one group, as `export_aggregate` writes them (`out`) from the report's cells (`full`)."""
    hidden = {k for k in keys if isinstance(out[k], Suppressed)}
    small = {k for k in keys if full[k].n < MIN_CELL}
    # Every small cell is hidden, and every visible cell is reported unchanged.
    assert small <= hidden
    assert all(out[k] == full[k] for k in keys if k not in hidden)
    # One hidden cell alone in a group of several would be its total minus the visible cells (§16.3).
    assert len(hidden) != 1 or len(keys) == 1
    # The complement adds exactly one cell, the smallest of the rest, and only to a lone small cell.
    if len(small) == 1 and len(keys) > 1:
        rest = [full[k].n for k in keys if k not in small]
        assert len(hidden - small) == 1
        assert full[(hidden - small).pop()].n == min(rest)
    else:
        assert hidden == small
