"""Metrics and the aggregate report (SPEC-03 §4.6, §4.7; ARCHITECTURE §16.3).

Pure functions over labels and engine output: `build_report` scores replayed pages against their checked labels,
and `export_aggregate` turns a report into the form that may leave the protected job (no pages, small cells
suppressed).

`FieldOutput`, `PageOutput` and `SchemaFields` are the parts of SPEC-05's `ExtractionResult` and SPEC-04's
`SchemaDef` that metrics read. Those specs bring the full types; callers then pass them instead, and these go.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from crawlerai.core.capture import BlockClass
from crawlerai.db.models import EvalCategory, ExtractionMode, PageKind, Split
from crawlerai.eval.labels import FieldLabel, FieldShape, LabelRow, Labels, parse_labels, values_equal
from crawlerai.normalize import url

# ARCHITECTURE §16.3: hidden and fresh aggregates suppress cells with fewer than 10 labeled fields.
MIN_CELL = 10

# ARCHITECTURE §10 evidence buckets and §6 `extraction_config.field_status`.
Evidence = Literal["adapter", "structured", "agreed", "config_corroborated", "config_uncorroborated", "llm_grounded"]
CONFIG_EVIDENCE: frozenset[Evidence] = frozenset({"config_corroborated", "config_uncorroborated"})
ConfigFieldStatus = Literal["corroborated", "uncorroborated", "operator", "suspended"]
Cell = Literal["TP", "FP", "FN", "TN"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldOutput(_Model):
    status: Literal["published", "missing", "conflict", "abstained"]
    value: JsonValue = None
    evidence: Evidence | None = None


class PageOutput(_Model):
    block_class: BlockClass  # from the capture manifest
    mode: ExtractionMode
    llm_calls: int = 0
    fields: dict[str, FieldOutput] = {}  # detail: the entity; listing: page-level fields
    rows: tuple[dict[str, FieldOutput], ...] = ()  # listing rows


class ReplayFailed(_Model):
    """A page whose replay failed (§4.11): it is dropped from the metrics, which the `n_pages` gate catches."""

    error: str


class SchemaFields(_Model):
    name: str
    page_kind: PageKind
    fields: dict[str, FieldShape]
    required: frozenset[str] = frozenset()
    required_groups: tuple[frozenset[str], ...] = ()


class EvalCase(_Model):
    """One eval page with its replay. `config_status` is the field status in the page's `config_snapshot` (§4.5)."""

    page_id: str
    category: EvalCategory
    schema_def: SchemaFields
    labels: Labels
    output: PageOutput | ReplayFailed
    config_status: dict[str, ConfigFieldStatus] = {}

    @model_validator(mode="after")
    def _labels_fit_schema(self) -> Self:
        # The labels must fit the page's schema, so that a checked page scores every field of it (D-0168).
        parse_labels(self.labels.model_dump(mode="json"), self.schema_def.page_kind, self.schema_def.fields)
        return self


class Judgment(_Model):
    """One field scored against its label (§4.6). `entity` is `page`, `row[i]` for the i-th label row, or
    `extra[j]` for the j-th engine row that matched no label row."""

    field: str
    entity: str
    cell: Cell
    on_absent: bool  # the label says absent
    wrong_product: bool
    evidence: Evidence | None
    label_value: JsonValue
    output_value: JsonValue


class PageDetail(_Model):
    page_id: str
    category: EvalCategory
    schema_name: str
    error: str | None
    zero_touch: bool | None
    judgments: tuple[Judgment, ...]


class FieldMetrics(_Model):
    precision: float | None
    coverage: float | None
    abstain_rate: float | None
    false_publish_on_absent: float | None
    wrong_product: int
    n: int  # scored fields: TP + FP + FN + TN


class PrecisionMetrics(_Model):
    precision: float | None
    n: int  # published fields: TP + FP


class ZeroTouch(_Model):
    zero_touch: float
    n: int  # pages


class Usage(_Model):
    llm_calls_per_1k_pages: float
    n: int  # pages run in this mode


class Suppressed(_Model):
    """A cell under `MIN_CELL`, reported by its size only."""

    n: int


class Report(_Model):
    report_version: Literal[1] = 1
    engine_version: str
    git_sha: str
    split: Split
    n_pages: int
    by_field_type: dict[str, FieldMetrics | Suppressed]
    by_field: dict[str, FieldMetrics | Suppressed]  # "schema|field"; empty in a hidden/fresh aggregate
    by_bucket: dict[str, PrecisionMetrics | Suppressed]  # "field_type|evidence"
    by_config_status: dict[str, PrecisionMetrics | Suppressed]  # "field_type|status"
    by_category: dict[str, ZeroTouch | Suppressed]
    acquisition: dict[str, dict[BlockClass, int] | Suppressed]  # per category
    usage: dict[str, Usage | Suppressed]  # per mode
    pages: tuple[PageDetail, ...] | None = None  # dev only, unsuppressed (§4.7)


def build_report(cases: Iterable[EvalCase], split: Split, engine_version: str, git_sha: str) -> Report:
    """Score every checked case. Pages that are not `checked` don't count (§4.3); failed replays are dropped from
    `n_pages` and every metric. Per-page detail is kept for dev only."""
    scored: list[tuple[EvalCase, PageOutput, list[Judgment], bool]] = []
    details: list[PageDetail] = []
    for case in sorted(cases, key=lambda c: c.page_id):
        if case.labels.status != "checked":
            continue
        match case.output:
            case ReplayFailed(error=error):
                details.append(_detail(case, error, None, ()))
            case PageOutput() as output:
                judgments = list(_judge_page(case.schema_def, case.labels, output))
                zero_touch = _zero_touch(case.schema_def, judgments)
                scored.append((case, output, judgments, zero_touch))
                details.append(_detail(case, None, zero_touch, tuple(judgments)))

    by_type: defaultdict[str, list[Judgment]] = defaultdict(list)
    by_field: defaultdict[str, list[Judgment]] = defaultdict(list)
    by_bucket: defaultdict[str, list[Judgment]] = defaultdict(list)
    by_config: defaultdict[str, list[Judgment]] = defaultdict(list)
    pages_by_category: defaultdict[str, list[tuple[bool, BlockClass]]] = defaultdict(list)
    pages_by_mode: defaultdict[str, list[PageOutput]] = defaultdict(list)
    for case, output, judgments, zero_touch in scored:
        pages_by_category[case.category].append((zero_touch, output.block_class))
        pages_by_mode[output.mode].append(output)
        for j in judgments:
            type_ = case.schema_def.fields[j.field].type
            by_type[type_].append(j)
            by_field[f"{case.schema_def.name}|{j.field}"].append(j)
            if j.evidence is not None:
                by_bucket[f"{type_}|{j.evidence}"].append(j)
            if (status := _config_status(case, j)) is not None:
                by_config[f"{type_}|{status}"].append(j)

    return Report(
        engine_version=engine_version,
        git_sha=git_sha,
        split=split,
        n_pages=len(scored),
        by_field_type={k: _field_metrics(v) for k, v in sorted(by_type.items())},
        by_field={k: _field_metrics(v) for k, v in sorted(by_field.items())},
        by_bucket={k: _precision(v) for k, v in sorted(by_bucket.items())},
        by_config_status={k: _precision(v) for k, v in sorted(by_config.items())},
        by_category={
            k: ZeroTouch(zero_touch=sum(zt for zt, _ in pages) / len(pages), n=len(pages))
            for k, pages in sorted(pages_by_category.items())
        },
        acquisition={
            k: dict(sorted(Counter(block_class for _, block_class in pages).items()))
            for k, pages in sorted(pages_by_category.items())
        },
        usage={
            k: Usage(llm_calls_per_1k_pages=1000 * sum(o.llm_calls for o in outs) / len(outs), n=len(outs))
            for k, outs in sorted(pages_by_mode.items())
        },
        pages=tuple(details) if split == "dev" else None,
    )


def export_aggregate(report: Report) -> Report:
    """The report as it may leave the protected job (§4.7): no per-page rows, and every cell under `MIN_CELL`
    reduced to its `n`. Page-level cells (category, acquisition, usage) count pages, which is stricter than counting
    the fields on them. Per-field cells stay in the job for hidden and fresh: their keys name schemas, and §4.7 and C10
    expose aggregates per field type and evidence bucket only.

    Hidden and fresh aggregates also suppress complementarily (§16.3, D-0234), in every group of cells that sums to
    a reported total: the bucket cells and the config-status cells of one field type (published fields of that
    type), and the category cells and the usage cells (pages, which sum to `n_pages`)."""
    dev = report.split == "dev"
    by_category = _complement(_suppress_all(report.by_category), _whole, dev)
    return report.model_copy(
        update={
            "by_field_type": _suppress_all(report.by_field_type),
            "by_field": _suppress_all(report.by_field) if dev else {},
            "by_bucket": _complement(_suppress_all(report.by_bucket), _field_type, dev),
            "by_config_status": _complement(_suppress_all(report.by_config_status), _field_type, dev),
            "by_category": by_category,
            # Acquisition counts the same pages as the category's zero-touch cell, so it shares that suppression.
            "acquisition": {
                k: cell if isinstance(cell, Suppressed) else report.acquisition[k] for k, cell in by_category.items()
            },
            "usage": _complement(_suppress_all(report.usage), _whole, dev),
            "pages": None,
        }
    )


def generalization_gap(dev: Report, fresh: Report) -> dict[str, float]:
    """`precision_dev - precision_fresh` per field type (§4.6), where both have a reported precision."""
    gap: dict[str, float] = {}
    for type_, cell in sorted(dev.by_field_type.items()):
        other = fresh.by_field_type.get(type_)
        if (
            isinstance(cell, FieldMetrics)
            and isinstance(other, FieldMetrics)
            and cell.precision is not None
            and other.precision is not None
        ):
            gap[type_] = cell.precision - other.precision
    return gap


def _config_status(case: EvalCase, judgment: Judgment) -> ConfigFieldStatus | None:
    # Fields published from a config are measured per the field's status in the page's config snapshot (§4.5).
    if judgment.evidence not in CONFIG_EVIDENCE:
        return None
    return case.config_status.get(judgment.field)


def _detail(case: EvalCase, error: str | None, zero_touch: bool | None, judgments: tuple[Judgment, ...]) -> PageDetail:
    return PageDetail(
        page_id=case.page_id,
        category=case.category,
        schema_name=case.schema_def.name,
        error=error,
        zero_touch=zero_touch,
        judgments=judgments,
    )


def _judge_page(schema: SchemaFields, labels: Labels, output: PageOutput) -> Iterator[Judgment]:
    # Fields labeled at page level: on a detail page all of them, on a listing page the `scope: page` ones (D-0168
    # makes a checked page label every one).
    for name, label in sorted(labels.fields.items()):
        yield _judge(name, "page", label, output.fields.get(name), schema.fields[name])
    if schema.page_kind == "detail":
        return
    matches = _match_rows(labels.rows, output.rows)
    for i, row in enumerate(labels.rows):
        out_row = output.rows[matches[i]] if i in matches else {}
        for name, label in sorted(row.fields.items()):
            yield _judge(name, f"row[{i}]", label, out_row.get(name), schema.fields[name])
    matched = set(matches.values())
    for j, out_row in enumerate(output.rows):
        if j not in matched:
            yield from _unmatched_row(j, out_row, schema)


def _unmatched_row(j: int, row: Mapping[str, FieldOutput], schema: SchemaFields) -> Iterator[Judgment]:
    # §4.6: an engine row that matches no label row is FP for every published field.
    for name, out in sorted(row.items()):
        if out.status == "published" and name in schema.fields:
            yield Judgment(
                field=name,
                entity=f"extra[{j}]",
                cell="FP",
                on_absent=False,
                wrong_product=False,
                evidence=out.evidence,
                label_value=None,
                output_value=out.value,
            )


def _match_rows(label_rows: Sequence[LabelRow], rows: Sequence[Mapping[str, FieldOutput]]) -> dict[int, int]:
    """Label row index → engine row index, matched by canonicalized `url` (§4.6), in page order, one to one."""
    matches: dict[int, int] = {}
    taken: set[int] = set()
    for i, label_row in enumerate(label_rows):
        label = label_row.fields.get("url")
        if label is None or label.absent:
            continue
        for j, row in enumerate(rows):
            out = row.get("url")
            if j not in taken and out is not None and out.status == "published" and url.equal(label.value, out.value):
                matches[i] = j
                taken.add(j)
                break
    return matches


def _judge(name: str, entity: str, label: FieldLabel, out: FieldOutput | None, shape: FieldShape) -> Judgment:
    published = out if out is not None and out.status == "published" else None
    value = published.value if published else None
    if published:
        cell: Cell = "FP" if label.absent or not values_equal(value, label.value, shape) else "TP"
    else:
        cell = "TN" if label.absent else "FN"
    return Judgment(
        field=name,
        entity=entity,
        cell=cell,
        on_absent=label.absent,
        wrong_product=published is not None and any(values_equal(value, d, shape) for d in label.distractors),
        evidence=published.evidence if published else None,
        label_value=label.value,
        output_value=value,
    )


def _zero_touch(schema: SchemaFields, judgments: Sequence[Judgment]) -> bool:
    """Every required field is TP, and every required group has a TP member and no FP member (§4.6), on each entity
    the page has; and the engine published no row that the labels don't have."""
    if any(j.entity.startswith("extra[") for j in judgments):
        return False
    if any(j.field in schema.required and j.cell != "TP" for j in judgments):
        return False
    for group in schema.required_groups:
        cells: defaultdict[str, set[Cell]] = defaultdict(set)
        for j in judgments:
            if j.field in group:
                cells[j.entity].add(j.cell)
        if any("TP" not in c or "FP" in c for c in cells.values()):
            return False
    return True


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _field_metrics(judgments: Sequence[Judgment]) -> FieldMetrics:
    count = Counter(j.cell for j in judgments)
    tp, fp, fn, tn = count["TP"], count["FP"], count["FN"], count["TN"]
    fp_absent = sum(j.cell == "FP" and j.on_absent for j in judgments)
    return FieldMetrics(
        precision=_ratio(tp, tp + fp),
        coverage=_ratio(tp, tp + fn),
        abstain_rate=_ratio(fn + tn, len(judgments)),
        false_publish_on_absent=_ratio(fp_absent, fp_absent + tn),
        wrong_product=sum(j.wrong_product for j in judgments),
        n=len(judgments),
    )


def _precision(judgments: Sequence[Judgment]) -> PrecisionMetrics:
    count = Counter(j.cell for j in judgments)
    tp, fp = count["TP"], count["FP"]
    return PrecisionMetrics(precision=_ratio(tp, tp + fp), n=tp + fp)


def _suppress_all[C: FieldMetrics | PrecisionMetrics | ZeroTouch | Usage | Suppressed](
    table: Mapping[str, C],
) -> dict[str, C | Suppressed]:
    return {k: _suppress(v) for k, v in table.items()}


def _suppress[C: FieldMetrics | PrecisionMetrics | ZeroTouch | Usage | Suppressed](cell: C) -> C | Suppressed:
    return Suppressed(n=cell.n) if cell.n < MIN_CELL else cell


def _complement[C: PrecisionMetrics | ZeroTouch | Usage](
    table: Mapping[str, C | Suppressed], group_of: Callable[[str], str], dev: bool
) -> dict[str, C | Suppressed]:
    """Complementary suppression (§16.3): a group whose cells sum to a reported total must not show all its cells
    but one, or that one is the total minus the others. So when exactly one cell of a group is suppressed, the
    next-smallest cell (ties by key) is suppressed too; with two hidden, only their sum is derivable. A group of one
    cell equals its total, which is reported at its own size by design, so it is left as is. Dev is reported in full
    (§4.7), so it gets none."""
    out = dict(table)
    if dev:
        return out
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for key in table:
        groups[group_of(key)].append(key)
    for keys in groups.values():
        visible = [k for k in keys if not isinstance(out[k], Suppressed)]
        if len(keys) - len(visible) == 1 and visible:
            nearest = min(visible, key=lambda k: (out[k].n, k))
            out[nearest] = Suppressed(n=out[nearest].n)
    return out


def _field_type(key: str) -> str:
    # "field_type|evidence" and "field_type|status": the group is the field type.
    return key.split("|", 1)[0]


def _whole(_key: str) -> str:
    # Category and usage cells count pages; together they count every page in `n_pages`.
    return ""
