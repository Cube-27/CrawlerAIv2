"""Metrics and the golden-set report (evaluation spec, "Replay harness and metrics").

Pure functions over labels and engine output: `build_report` scores replayed pages against their labels.

A row-mapped field (SPEC-13 §4.10) is scored per sub-field, as `<field>.<sub>` in `list.<type>` cells: engine rows
match label rows by the field's key, and row precision and recall count the matches.

`FieldOutput`, `PageOutput` and `SchemaFields` are the parts of SPEC-05's `ExtractionResult` and SPEC-04's
`SchemaDef` that metrics read. Those specs bring the full types; callers then pass them instead, and these go.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from crawlerai.collect.schema_org_map import is_item_url
from crawlerai.core.capture import BlockClass
from crawlerai.db.models import EvalCategory, ExtractionMode, FieldStatus, PageKind, SourceKind, Split
from crawlerai.eval.labels import (
    DistractorKey,
    FieldLabel,
    LabelRow,
    Labels,
    LabelStatus,
    ListLabel,
    parse_labels,
    sub_fields,
)
from crawlerai.eval.presence import Capture
from crawlerai.eval.scoring import same
from crawlerai.normalize.dispatch import equal
from crawlerai.normalize.url_key import without_parameters
from crawlerai.resolve.preference import rule_type
from crawlerai.resolve.types import Evidence
from crawlerai.schemas.types import FieldSpec, FieldType

# §4.6: listing rows match by their canonicalized `url`.
_URL = FieldSpec(type=FieldType.URL)
# The label statuses that count by default: checked pages only (§16.2). Drafts count only in a dev report that asks
# for them (D-1461).
CHECKED: frozenset[LabelStatus] = frozenset({"checked"})

# ARCHITECTURE §10: the evidence buckets of config candidates.
CONFIG_EVIDENCE: frozenset[Evidence] = frozenset({"config_corroborated", "config_uncorroborated"})
Cell = Literal["TP", "FP", "FN", "TN"]
SourceCell = Literal["TP", "FP"]
# Which engine rows of a listing that match no label row count as FP (§4.6): every one (`all`), or only those among the
# first as many engine rows as the page has label rows (`labeled`, D-1480). A label holds the rows of the page as it
# was labeled, its first page; an adapter or a paging run reads the list's further pages too, whose rows no label
# holds, so the dev report scores both.
RowScope = Literal["all", "labeled"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldOutput(_Model):
    status: Literal["published", "missing", "conflict", "abstained"]
    value: JsonValue = None
    evidence: Evidence | None = None
    # Why the field is not published (`FieldOutcome.reason`: `below_tau`, `llm_unavailable`, ...), for triage.
    reason: str | None = None
    # The normalized values of the field's kept candidates (valid, owned, not a URL parameter), per source kind,
    # published or not: what `fit-precedence` scores each kind on (SPEC-05 §4.11).
    offered: dict[SourceKind, tuple[JsonValue, ...]] = {}
    # A row-mapped field's published rows (SPEC-13 §4.5): each sub-field's output.
    items: tuple[dict[str, "FieldOutput"], ...] = ()


class PageOutput(_Model):
    block_class: BlockClass  # from the capture manifest
    mode: ExtractionMode
    llm_calls: int = 0
    # LLM calls the page asked for that got no reply (no provider, no recording answered as unavailable): the
    # fields they were for stay missing, so a dev report tells the misses that depend on role C (D-1464).
    llm_unanswered: int = 0
    fields: dict[str, FieldOutput] = {}  # detail: the entity; listing: page-level fields
    rows: tuple[dict[str, FieldOutput], ...] = ()  # listing rows
    # Per row item URL field, the query parameters the engine dropped from its values, dropped from labels alike.
    session_params: dict[str, tuple[str, ...]] = {}
    # The page's LLM tokens, and their price in USD (`None` when a call's model has no known price).
    tokens_in: int = 0
    tokens_out: int = 0
    llm_usd: float | None = 0.0


class ReplayFailed(_Model):
    """A page whose replay failed: it is dropped from the metrics and `n_pages`, and listed with its error."""

    error: str


class SchemaFields(_Model):
    name: str
    page_kind: PageKind
    fields: dict[str, FieldSpec]
    required: frozenset[str] = frozenset()
    required_groups: tuple[frozenset[str], ...] = ()


class EvalCase(_Model):
    """One eval page with its replay. `config_status` is the field status in the page's `config_snapshot` (§4.5)."""

    page_id: str
    category: EvalCategory
    schema_def: SchemaFields
    labels: Labels
    output: PageOutput | ReplayFailed
    config_status: dict[str, FieldStatus] = {}
    # The capture's document, to tell whether it shows a value (`eval.presence`); `None` leaves presence unknown.
    document: str | None = None

    @model_validator(mode="after")
    def _labels_fit_schema(self) -> Self:
        # The labels must fit the page's schema, so that a checked page scores every field of it (D-0168).
        parse_labels(self.labels.model_dump(mode="json"), self.schema_def.page_kind, self.schema_def.fields)
        return self


class Judgment(_Model):
    """One field scored against its label (§4.6). `entity` is `page`, `row[i]` for the i-th label row, or
    `extra[j]` for the j-th engine row that matched no label row. A row-mapped field's sub-field is `<field>.<sub>`
    (SPEC-13 §4.10), its rows numbered the same way."""

    field: str
    entity: str
    cell: Cell
    on_absent: bool  # the label says absent
    wrong_product: bool
    evidence: Evidence | None
    label_value: JsonValue
    output_value: JsonValue
    # The engine's reason for leaving the field unpublished, when it output the field and did not publish it.
    reason: str | None = None
    # Each kind that offered a value: TP when every value it offered equals the label's value.
    sources: dict[SourceKind, SourceCell] = {}
    # Whether the capture shows the label's value (an engine row's own value for an unmatched row); `None` unknown.
    present: bool | None = None


class PageDetail(_Model):
    page_id: str
    category: EvalCategory
    schema_name: str
    error: str | None
    zero_touch: bool | None
    judgments: tuple[Judgment, ...]
    llm_unanswered: int = 0
    label_status: LabelStatus = "checked"


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


class SourceMetrics(_Model):
    precision: float | None
    coverage: float | None  # TP over the fields of the type whose label holds a value
    n: int  # fields the kind offered a value for: TP + FP


class RowMetrics(_Model):
    """Row matching of row-mapped fields (SPEC-13 §4.10)."""

    row_precision: float | None  # matched engine rows / engine rows
    row_recall: float | None  # matched label rows / label rows
    engine_rows: int
    n: int  # label rows


class PresenceMetrics(_Model):
    """How many of a field type's labeled values the capture shows: `ceiling` is the coverage no reading of the
    capture can pass, over the values whose presence is known."""

    present: int
    absent: int
    unknown: int
    ceiling: float | None


class CostMetrics(_Model):
    llm_calls: int
    tokens_in: int
    tokens_out: int
    usd: float | None  # `None` when a call's model has no known price
    tp: int  # correct fields over every page
    tokens_per_tp: float | None
    usd_per_tp: float | None


class ZeroTouch(_Model):
    zero_touch: float
    n: int  # pages


class Usage(_Model):
    llm_calls_per_1k_pages: float
    n: int  # pages run in this mode


class Report(_Model):
    report_version: Literal[1] = 1
    engine_version: str
    git_sha: str
    split: Split
    n_pages: int
    by_field_type: dict[str, FieldMetrics]
    by_field: dict[str, FieldMetrics]  # "schema|field"
    by_bucket: dict[str, PrecisionMetrics]  # "field_type|evidence"
    by_config_status: dict[str, PrecisionMetrics]  # "field_type|status"
    by_category: dict[str, ZeroTouch]
    acquisition: dict[str, dict[BlockClass, int]]  # per category
    usage: dict[str, Usage]  # per mode
    pages: tuple[PageDetail, ...] | None = None
    # "rule_type|source_kind" (SPEC-05 §4.11).
    by_source: dict[str, SourceMetrics] = {}
    # Row-mapped fields (SPEC-13 §4.10): over all of them, and per "schema|field". `None` when no scored page labels
    # one.
    row_matching: RowMetrics | None = None
    row_matching_by_field: dict[str, RowMetrics] = {}
    # The label statuses scored: checked only, unless the report asks for drafts too. A list, so a Python dump of the
    # report is still JSON, as `eval_run.metrics` holds it.
    label_statuses: list[LabelStatus] = ["checked"]
    # Per "page_kind|field_type", and the count of each kind of disagreement per "schema|field" (`disagreement`), for
    # triage.
    by_page_kind: dict[str, FieldMetrics] = {}
    disagreements: dict[str, dict[str, int]] = {}
    # Which unmatched engine rows count as FP (`RowScope`, D-1480).
    rows_scored: RowScope = "all"
    # Per schema, the stale label rows (`LabelRow.stale`) no engine row matched: counted here, never as misses.
    label_stale: dict[str, int] = {}
    # Per field type, the labeled values the capture shows (the coverage ceiling).
    presence: dict[str, PresenceMetrics] = {}
    cost: CostMetrics | None = None


@dataclass(frozen=True)
class _RowCount:
    """A row-mapped field's rows on one page, or summed over pages."""

    engine: int = 0
    label: int = 0
    matched: int = 0

    def __add__(self, other: "_RowCount") -> "_RowCount":
        return _RowCount(self.engine + other.engine, self.label + other.label, self.matched + other.matched)

    def metrics(self) -> RowMetrics:
        return RowMetrics(
            row_precision=_ratio(self.matched, self.engine),
            row_recall=_ratio(self.matched, self.label),
            engine_rows=self.engine,
            n=self.label,
        )


def build_report(
    cases: Iterable[EvalCase],
    split: Split,
    engine_version: str,
    git_sha: str,
    statuses: frozenset[LabelStatus] = CHECKED,
    rows: RowScope = "all",
) -> Report:
    """Score every case whose label status is in `statuses`: checked only, unless the report asks for drafts too,
    whose unlabeled fields are not scored. Failed replays are dropped from `n_pages` and every metric. `rows` says
    which unmatched engine rows count as FP (`RowScope`)."""
    scored, details, row_counts, stale = _score(cases, statuses, rows)
    by_type: defaultdict[str, list[Judgment]] = defaultdict(list)
    by_field: defaultdict[str, list[Judgment]] = defaultdict(list)
    by_bucket: defaultdict[str, list[Judgment]] = defaultdict(list)
    by_config: defaultdict[str, list[Judgment]] = defaultdict(list)
    by_kind: defaultdict[str, list[Judgment]] = defaultdict(list)
    pages_by_category: defaultdict[str, list[tuple[bool, BlockClass]]] = defaultdict(list)
    pages_by_mode: defaultdict[str, list[PageOutput]] = defaultdict(list)
    for case, output, judgments, zero_touch in scored:
        pages_by_category[case.category].append((zero_touch, output.block_class))
        pages_by_mode[output.mode].append(output)
        for j in judgments:
            type_ = _cell_type(case.schema_def, j.field)
            by_type[type_].append(j)
            by_field[f"{case.schema_def.name}|{j.field}"].append(j)
            by_kind[f"{case.schema_def.page_kind}|{type_}"].append(j)
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
        pages=tuple(details),
        by_source=_by_source((c.schema_def, js) for c, _, js, _ in scored),
        row_matching=sum(row_counts.values(), _RowCount()).metrics() if row_counts else None,
        row_matching_by_field={k: v.metrics() for k, v in sorted(row_counts.items())},
        label_statuses=sorted(statuses),
        by_page_kind={k: _field_metrics(v) for k, v in sorted(by_kind.items())},
        disagreements=_disagreements(by_field),
        rows_scored=rows,
        label_stale=dict(sorted(stale.items())),
        presence={k: _presence(v) for k, v in sorted(by_type.items())},
        cost=_cost([output for _, output, _, _ in scored], [j for _, _, js, _ in scored for j in js]),
    )


def disagreement(judgment: Judgment) -> str | None:
    """What kind of disagreement a judgment is, for triage; `None` for an agreement (TP, TN). FP: `wrong_value`, a
    value where the label says `absent` (`on_absent`), or a row the labels don't have (`extra_row`, with `:on_page` or
    `:not_on_page` when the capture's showing its value is known). FN: `declined:<reason>` when the engine output the
    field and gave a reason, else `absent` when the capture does not show the value, `unread` when it does, or
    `not_output` when that is unknown."""
    match judgment.cell:
        case "TP" | "TN":
            return None
        case "FP" if judgment.entity.startswith("extra["):
            return f"FP|extra_row{_shown(judgment.present, ':on_page', ':not_on_page', '')}"
        case "FP":
            return "FP|on_absent" if judgment.on_absent else "FP|wrong_value"
        case "FN" if judgment.reason is not None:
            return f"FN|declined:{judgment.reason}"
        case "FN":
            return f"FN|{_shown(judgment.present, 'unread', 'absent', 'not_output')}"


def _shown(present: bool | None, shown: str, not_shown: str, unknown: str) -> str:
    return unknown if present is None else shown if present else not_shown


def _presence(judgments: Sequence[Judgment]) -> PresenceMetrics:
    labeled = Counter(j.present for j in judgments if _labeled(j))
    present, absent = labeled[True], labeled[False]
    return PresenceMetrics(
        present=present, absent=absent, unknown=labeled[None], ceiling=_ratio(present, present + absent)
    )


def _cost(outputs: Sequence[PageOutput], judgments: Sequence[Judgment]) -> CostMetrics:
    tp = sum(j.cell == "TP" for j in judgments)
    tokens_in, tokens_out = sum(o.tokens_in for o in outputs), sum(o.tokens_out for o in outputs)
    prices = [o.llm_usd for o in outputs]
    usd = None if None in prices else sum(p for p in prices if p is not None)
    return CostMetrics(
        llm_calls=sum(o.llm_calls for o in outputs),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        usd=usd,
        tp=tp,
        tokens_per_tp=_ratio(tokens_in + tokens_out, tp),
        usd_per_tp=None if usd is None else _ratio_float(usd, tp),
    )


def _disagreements(by_field: Mapping[str, Sequence[Judgment]]) -> dict[str, dict[str, int]]:
    counts = {
        key: Counter(kind for j in judgments if (kind := disagreement(j)) is not None)
        for key, judgments in by_field.items()
    }
    return {key: dict(sorted(count.items())) for key, count in sorted(counts.items()) if count}


_Scored = tuple[EvalCase, PageOutput, list[Judgment], bool]


def _score(
    cases: Iterable[EvalCase], statuses: frozenset[LabelStatus], rows: RowScope
) -> tuple[list[_Scored], list[PageDetail], defaultdict[str, _RowCount], Counter[str]]:
    """Each case in `statuses` judged, with its zero-touch; each page's detail; the row counts of row-mapped fields;
    the unmatched stale label rows per schema."""
    scored: list[_Scored] = []
    details: list[PageDetail] = []
    row_counts: defaultdict[str, _RowCount] = defaultdict(_RowCount)
    stale: Counter[str] = Counter()
    for case in sorted(cases, key=lambda c: c.page_id):
        if case.labels.status not in statuses:
            continue
        match case.output:
            case ReplayFailed(error=error):
                details.append(_detail(case, error, None, ()))
            case PageOutput() as output:
                capture = None if case.document is None else Capture(case.document)
                judgments, unmatched_stale = _judge_case(
                    case.schema_def, case.labels, output, row_counts, rows, capture
                )
                stale[case.schema_def.name] += unmatched_stale
                zero_touch = _zero_touch(case.schema_def, judgments, frozenset(case.labels.lists))
                scored.append((case, output, judgments, zero_touch))
                details.append(_detail(case, None, zero_touch, tuple(judgments), output.llm_unanswered))
    return scored, details, row_counts, +stale


def _judge_case(
    schema: SchemaFields,
    labels: Labels,
    output: PageOutput,
    row_counts: defaultdict[str, _RowCount],
    rows: RowScope = "all",
    capture: Capture | None = None,
) -> tuple[list[Judgment], int]:
    """A page's judgments, its row-mapped fields' included, and how many stale label rows no engine row matched;
    the row-mapped fields' row counts are added to `row_counts`."""
    judgments, stale = _judge_page(schema, labels, output, rows, capture)
    for name, (list_judgments, count) in _judge_lists(schema, labels, output).items():
        judgments += list_judgments
        row_counts[f"{schema.name}|{name}"] += count
    return judgments, stale


def _cell_type(schema: SchemaFields, field: str) -> str:
    """A judgment's field type cell: the field's type, or `list.<type>` for a row-mapped field's sub-field
    (SPEC-13 §4.10). A row value can be wrong in a way a page value cannot (a wrong row match), so it is measured
    apart, as the calibration buckets are (SPEC-13 §4.5)."""
    name, _, sub = field.partition(".")
    spec = schema.fields[name]
    return f"list.{sub_fields(spec)[sub].type.value}" if sub else spec.type


def _by_source(pages: Iterable[tuple[SchemaFields, Sequence[Judgment]]]) -> dict[str, SourceMetrics]:
    """Per rule type and source kind, the fields the kind offered a value for, scored against their labels. A list is
    measured as its item type, whose precedence order ranks it (SPEC-05 §4.7)."""
    cells: defaultdict[tuple[FieldType, SourceKind], list[SourceCell]] = defaultdict(list)
    labeled: Counter[FieldType] = Counter()  # per rule type, the judged fields whose label holds a value
    for schema, judgments in pages:
        # Row sub-fields fit no precedence: a row value is measured apart (SPEC-13 §4.10).
        for j in (j for j in judgments if not _is_sub_field(j.field)):
            type_ = rule_type(schema.fields[j.field])
            labeled[type_] += _labeled(j)
            for kind, cell in j.sources.items():
                cells[type_, kind].append(cell)
    return {f"{type_.value}|{kind}": _source_metrics(v, labeled[type_]) for (type_, kind), v in sorted(cells.items())}


def _is_sub_field(field: str) -> bool:
    # A row-mapped field's sub-field is judged as `<field>.<sub>`; schema field names have no dot (SPEC-04 §4.2).
    return "." in field


def _labeled(judgment: Judgment) -> bool:
    # An engine row that matched no label row has no label (`extra[j]`, §4.6).
    return not judgment.on_absent and not judgment.entity.startswith("extra[")


def _source_metrics(cells: Sequence[SourceCell], labeled: int) -> SourceMetrics:
    tp = cells.count("TP")
    return SourceMetrics(precision=_ratio(tp, len(cells)), coverage=_ratio(tp, labeled), n=len(cells))


def _config_status(case: EvalCase, judgment: Judgment) -> FieldStatus | None:
    # Fields published from a config are measured per the field's status in the page's config snapshot (§4.5).
    if judgment.evidence not in CONFIG_EVIDENCE:
        return None
    return case.config_status.get(judgment.field)


def _detail(
    case: EvalCase,
    error: str | None,
    zero_touch: bool | None,
    judgments: tuple[Judgment, ...],
    llm_unanswered: int = 0,
) -> PageDetail:
    return PageDetail(
        page_id=case.page_id,
        category=case.category,
        schema_name=case.schema_def.name,
        error=error,
        zero_touch=zero_touch,
        judgments=judgments,
        llm_unanswered=llm_unanswered,
        label_status=case.labels.status,
    )


def _judge_page(
    schema: SchemaFields, labels: Labels, output: PageOutput, rows: RowScope = "all", capture: Capture | None = None
) -> tuple[list[Judgment], int]:
    """The page's judgments, and how many stale label rows no engine row matched (those are not judged)."""
    # Fields labeled at page level: on a detail page all of them, on a listing page the `scope: page` ones (D-0168
    # makes a checked page label every one).
    judgments = [
        _judge(name, "page", label, output.fields.get(name), schema.fields[name], capture)
        for name, label in sorted(labels.fields.items())
    ]
    if schema.page_kind == "detail":
        return judgments, 0
    url_field = _url_field(schema.fields)
    matches = _match_rows(labels.rows, output.rows, schema.fields, output.session_params.get(url_field, ()), url_field)
    stale = 0
    for i, row in enumerate(labels.rows):
        if i not in matches and row.stale:
            stale += 1
            continue
        out_row = output.rows[matches[i]] if i in matches else {}
        for name, label in sorted(row.fields.items()):
            spec = schema.fields[name]
            session = output.session_params.get(name, ())
            label, out = _keyed(label, session), _keyed_output(out_row.get(name), session)
            judgments.append(_judge(name, f"row[{i}]", label, out, spec, capture))
    matched = set(matches.values())
    # D-1480: with `labeled`, an unmatched engine row past the label's row count is a row of a page no label holds.
    scored = len(output.rows) if rows == "all" else len(labels.rows)
    for j, out_row in enumerate(output.rows[:scored]):
        if j not in matched:
            judgments += _unmatched_row(j, out_row, schema.fields, capture)
    return judgments, stale


def _judge_lists(
    schema: SchemaFields, labels: Labels, output: PageOutput
) -> dict[str, tuple[list[Judgment], _RowCount]]:
    """Each labeled row-mapped field's sub-field judgments and row counts (SPEC-13 §4.10). Version 1 labels have none,
    so those fields are not scored."""
    return {
        name: _judge_list(name, label, output.fields.get(name), schema.fields[name])
        for name, label in sorted(labels.lists.items())
    }


def _judge_list(
    name: str, label: ListLabel, out: FieldOutput | None, spec: FieldSpec
) -> tuple[list[Judgment], _RowCount]:
    """A matched pair's sub-fields are judged as top-level fields are (§4.6). An unmatched label row is FN for each
    sub-field it does not label absent; an unmatched engine row is FP for each published sub-field. An engine row with
    a distractor key is a wrong product, counted once on that key's sub-field."""
    subs = sub_fields(spec)
    engine = out.items if out is not None and out.status == "published" else ()
    matches = _match_keyed(label.rows, engine, spec.key or (), subs)
    wrong = _wrong_products(engine, label.distractor_keys, subs)
    judgments: list[Judgment] = []
    for i, row in enumerate(label.rows):
        j = matches.get(i)
        out_row = engine[j] if j is not None else {}
        for sub, sub_label in sorted(row.fields.items()):
            judgment = _judge(f"{name}.{sub}", f"row[{i}]", sub_label, out_row.get(sub), subs[sub])
            judgments.append(_row_judgment(judgment, j is not None and wrong.get(j) == sub))
    matched = set(matches.values())
    for j, out_row in enumerate(engine):
        if j not in matched:
            for judgment in _unmatched_row(j, out_row, subs):
                renamed = judgment.model_copy(update={"field": f"{name}.{judgment.field}"})
                judgments.append(_row_judgment(renamed, wrong.get(j) == judgment.field))
    return judgments, _RowCount(engine=len(engine), label=len(label.rows), matched=len(matches))


def _row_judgment(judgment: Judgment, wrong_product: bool) -> Judgment:
    # Row sub-fields fit no precedence (`_by_source`), so they carry no source cells.
    return judgment.model_copy(update={"sources": {}, "wrong_product": judgment.wrong_product or wrong_product})


def _match_keyed(
    label_rows: Sequence[LabelRow],
    engine: Sequence[Mapping[str, FieldOutput]],
    key: Sequence[str],
    subs: Mapping[str, FieldSpec],
) -> dict[int, int]:
    """Label row index → engine row index (SPEC-13 §4.10, the §4.4 rule): the two share a key value and differ on none.
    A row that matches several rows on the other side counts as unmatched."""
    pairs = [
        (i, j) for i, lr in enumerate(label_rows) for j, er in enumerate(engine) if _same_variant(lr, er, key, subs)
    ]
    by_label, by_engine = Counter(i for i, _ in pairs), Counter(j for _, j in pairs)
    return {i: j for i, j in pairs if by_label[i] == 1 and by_engine[j] == 1}


def _same_variant(
    label_row: LabelRow, engine_row: Mapping[str, FieldOutput], key: Sequence[str], subs: Mapping[str, FieldSpec]
) -> bool:
    agree = [
        equal(label.value, out.value, subs[sub])
        for sub in key
        if (label := label_row.fields.get(sub)) is not None
        and not label.absent
        and (out := engine_row.get(sub)) is not None
        and out.status == "published"
    ]
    return bool(agree) and all(agree)


def _wrong_products(
    engine: Sequence[Mapping[str, FieldOutput]], keys: Sequence[DistractorKey], subs: Mapping[str, FieldSpec]
) -> dict[int, str]:
    """Engine row index → the sub-field whose published value is a distractor key (SPEC-13 §4.10)."""
    wrong: dict[int, str] = {}
    for j, row in enumerate(engine):
        hit = next(
            (key.field for key in keys if _published_equal(row.get(key.field), key.value, subs[key.field])), None
        )
        if hit is not None:
            wrong[j] = hit
    return wrong


def _published_equal(out: FieldOutput | None, value: JsonValue, spec: FieldSpec) -> bool:
    return out is not None and out.status == "published" and equal(out.value, value, spec)


def _unmatched_row(
    j: int, row: Mapping[str, FieldOutput], specs: Mapping[str, FieldSpec], capture: Capture | None = None
) -> Iterator[Judgment]:
    # §4.6: an engine row that matches no label row is FP for every published field.
    for name, out in sorted(row.items()):
        if out.status == "published" and name in specs:
            yield Judgment(
                field=name,
                entity=f"extra[{j}]",
                cell="FP",
                on_absent=False,
                wrong_product=False,
                evidence=out.evidence,
                label_value=None,
                output_value=out.value,
                sources=dict.fromkeys(out.offered, "FP"),
                present=None if capture is None else capture.shows(out.value, specs[name]),
            )


def _keyed(label: FieldLabel, session: Collection[str]) -> FieldLabel:
    """A row item URL label rid of the session parameters the engine dropped from that field's values (`session`, empty
    for every other field), as row matching reads it (extraction spec, "Row item URLs without session parameters")."""
    if not session or not isinstance(label.value, str):
        return label
    return label.model_copy(update={"value": without_parameters(label.value, session)})


def _keyed_output(out: FieldOutput | None, session: Collection[str]) -> FieldOutput | None:
    """The engine's output for a row item URL field with the values each source kind offered rid of the same
    parameters: the published value already is, and each kind is scored against the keyed label."""
    if out is None or not session:
        return out
    offered = {
        kind: tuple(without_parameters(v, session) if isinstance(v, str) else v for v in values)
        for kind, values in out.offered.items()
    }
    return out.model_copy(update={"offered": offered})


_RowMatch = Callable[[LabelRow, Mapping[str, FieldOutput]], bool]


def _url_field(specs: Mapping[str, FieldSpec]) -> str:
    """The row field holding the item URL, as the engine reads it (`is_item_url`); `url` when the schema has none."""
    return next((name for name, spec in specs.items() if is_item_url(spec)), "url")


def _match_rows(
    label_rows: Sequence[LabelRow],
    rows: Sequence[Mapping[str, FieldOutput]],
    specs: Mapping[str, FieldSpec],
    session: Collection[str] = (),
    url_field: str = "url",
) -> dict[int, int]:
    """Label row index → engine row index, one to one, in page order: by canonical `url` with the page's session
    parameters dropped from the label's as the engine dropped them from its rows (evaluation spec, "Row matching");
    then, for the rows left, by URL path with equal text fields; then, for a label row without a URL, by equal text
    fields alone."""
    passes: tuple[_RowMatch, ...] = (
        lambda label, row: _same_url(label, row, session, url_field),
        lambda label, row: _same_path(label, row, url_field) and _same_texts(label, row, specs),
        lambda label, row: _url_of(label, url_field) is None and _same_texts(label, row, specs),
    )
    matches: dict[int, int] = {}
    for matching in passes:
        _match_pass(label_rows, rows, matching, matches)
    return matches


def _match_pass(
    label_rows: Sequence[LabelRow],
    rows: Sequence[Mapping[str, FieldOutput]],
    matching: _RowMatch,
    matches: dict[int, int],
) -> None:
    """Add to `matches` each label row left that `matching` pairs with the first engine row left."""
    taken = set(matches.values())
    for i, label_row in enumerate(label_rows):
        if i in matches:
            continue
        j = next((j for j, row in enumerate(rows) if j not in taken and matching(label_row, row)), None)
        if j is not None:
            matches[i] = j
            taken.add(j)


def _url_of(label_row: LabelRow, field: str) -> str | None:
    label = label_row.fields.get(field)
    return label.value if label is not None and not label.absent and isinstance(label.value, str) else None


def _engine_url(row: Mapping[str, FieldOutput], field: str) -> str | None:
    out = row.get(field)
    return out.value if out is not None and out.status == "published" and isinstance(out.value, str) else None


def _same_url(label_row: LabelRow, row: Mapping[str, FieldOutput], session: Collection[str], field: str) -> bool:
    label, engine = _url_of(label_row, field), _engine_url(row, field)
    return label is not None and engine is not None and equal(without_parameters(label, session), engine, _URL)


def _same_path(label_row: LabelRow, row: Mapping[str, FieldOutput], field: str) -> bool:
    label, engine = _url_of(label_row, field), _engine_url(row, field)
    return label is not None and engine is not None and _host_path(label) == _host_path(engine)


def _host_path(url: str) -> tuple[str, str]:
    # RFC 3986 §6.2.2.1: the host is case-insensitive; the path is not.
    head = url.partition("?")[0].partition("#")[0]
    rest = head.partition("://")[2]
    host, slash, path = rest.partition("/")
    return host.lower(), slash + path


def _same_texts(label_row: LabelRow, row: Mapping[str, FieldOutput], specs: Mapping[str, FieldSpec]) -> bool:
    """Every text field the label row gives a value is published equal, and there is at least one."""
    texts = [
        (name, label)
        for name, label in label_row.fields.items()
        if not label.absent and label.value is not None and specs[name].type is FieldType.TEXT
    ]
    return bool(texts) and all(
        (out := row.get(name)) is not None and out.status == "published" and same(out.value, label.value, specs[name])
        for name, label in texts
    )


def _judge(
    name: str, entity: str, label: FieldLabel, out: FieldOutput | None, spec: FieldSpec, capture: Capture | None = None
) -> Judgment:
    published = out if out is not None and out.status == "published" else None
    value = published.value if published else None
    if published:
        cell: Cell = "FP" if label.absent or not same(value, label.value, spec) else "TP"
    else:
        cell = "TN" if label.absent else "FN"
    return Judgment(
        field=name,
        entity=entity,
        cell=cell,
        on_absent=label.absent,
        wrong_product=published is not None and any(equal(value, d, spec) for d in label.distractors),
        evidence=published.evidence if published else None,
        label_value=label.value,
        output_value=value,
        reason=None if out is None or published else out.reason,
        sources={} if out is None else _source_cells(out, label, spec),
        present=None if capture is None or label.absent else capture.shows(label.value, spec),
    )


def _source_cells(out: FieldOutput, label: FieldLabel, spec: FieldSpec) -> dict[SourceKind, SourceCell]:
    return {
        kind: "TP" if not label.absent and all(same(v, label.value, spec) for v in values) else "FP"
        for kind, values in out.offered.items()
    }


def _zero_touch(schema: SchemaFields, judgments: Sequence[Judgment], labeled_lists: frozenset[str]) -> bool:
    """Every required field is TP, and every required group has a TP member and no FP member (§4.6), on each entity
    the page has; and the engine published no row that the labels don't have. A row-mapped field's rows count only
    when it is required and labeled (`labeled_lists`; version 1 labels leave it unscored, SPEC-13 §4.10)."""
    if any(j.entity.startswith("extra[") and not _is_sub_field(j.field) for j in judgments):
        return False
    if any(j.field in schema.required and j.cell != "TP" for j in judgments):
        return False
    required_rows = sorted(name for name in schema.required & labeled_lists if schema.fields[name].row_mapped)
    if not all(_rows_met(name, judgments) for name in required_rows):
        return False
    return all(_group_met(group, judgments) for group in schema.required_groups)


def _rows_met(name: str, judgments: Sequence[Judgment]) -> bool:
    """A required row-mapped field holds as a required field does: a value, and no wrong one. Some sub-field is TP,
    and every other is TP or labeled absent and not published (TN), so every label row is matched and no row the
    labels don't have was published."""
    cells = [j.cell for j in judgments if j.field.startswith(f"{name}.")]
    return "TP" in cells and all(cell in ("TP", "TN") for cell in cells)


def _group_met(group: frozenset[str], judgments: Sequence[Judgment]) -> bool:
    """Whether a required group has a TP member and no FP member on each entity (§4.6)."""
    cells: defaultdict[str, set[Cell]] = defaultdict(set)
    for j in judgments:
        if j.field in group:
            cells[j.entity].add(j.cell)
    return not any("TP" not in c or "FP" in c for c in cells.values())


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _ratio_float(num: float, den: int) -> float | None:
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
