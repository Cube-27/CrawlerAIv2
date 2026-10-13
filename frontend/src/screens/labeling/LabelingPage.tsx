import { Button, Input, Label, Link, Radio, RadioGroup, TextArea, TextField } from "@heroui/react";
import { useState } from "react";
import { useLoaderData, useRevalidator } from "react-router";
import { sameOriginClient } from "../../api/client";
import {
  draftFrom,
  fieldNames,
  newRow,
  samePerson,
  toLabels,
  type Draft,
  type FieldDraft,
  type FieldError,
  type LabelStatus,
  type Pass,
} from "./draft";
import { EvalUiOff } from "./EvalUiOff";
import { FieldEditor } from "./FieldEditor";
import { SplitBadge, statusText } from "./LabelingList";
import type { PageDetail, pageLoader } from "./loaders";
import { PageView, type Pick } from "./PageView";

export function LabelingPage() {
  const data = useLoaderData<typeof pageLoader>();
  // Kept here, outside the editor, so it outlives the editor's reload after a save.
  const [notice, setNotice] = useState<string | null>(null);

  switch (data.kind) {
    case "off":
      return <EvalUiOff />;
    case "missing":
      return <output className="block">No dev eval page has this id.</output>;
    case "page":
      return (
        <PageEditor
          // A new ETag is a new stored pass: start the form again from it.
          key={data.etag ?? data.page.id}
          page={data.page}
          etag={data.etag}
          notice={notice}
          onSaved={setNotice}
        />
      );
    default: {
      const _exhaustive: never = data;
      return _exhaustive;
    }
  }
}

const PASSES: [Pass, string][] = [
  ["labeler", "Labeler"],
  ["checker", "Checker"],
];

/**
 * The field errors and message of a failed save. The API answers with an RFC 9457 problem, but a proxy's HTML page
 * or FastAPI's own validation list can arrive instead, and the screen still says the save failed.
 */
function saveFailure(error: unknown, status: number): { errors: FieldError[]; detail: string } {
  const body =
    typeof error === "object" && error !== null ? (error as Record<string, unknown>) : {};
  return {
    errors: Array.isArray(body.errors) ? (body.errors as FieldError[]) : [],
    detail:
      typeof body.detail === "string" ? body.detail : `the server answered ${String(status)}.`,
  };
}

/** Where a click on the page goes: a top-level field, or a field of one listing row. */
interface Target {
  row: number | null;
  name: string;
}

function pathOf({ row, name }: Target): string {
  return row === null ? `fields.${name}` : `rows[${String(row)}].fields.${name}`;
}

/** The reasons in `errors` for the field at `path`, each prefixed with the part of the field it is about. */
function reasonsAt(errors: FieldError[], path: string): string[] {
  return errors
    .filter((e) => e.field === path || e.field.startsWith(`${path}.`))
    .map((e) => {
      const part = e.field.slice(path.length + 1);
      return part === "" ? e.reason : `${part}: ${e.reason}`;
    });
}

function isFieldPath(field: string): boolean {
  return field.startsWith("fields.") || field.startsWith("rows[");
}

/** What `/normalize` answered, as text: the normalized value, or the type's reason to decline (SPEC-04). */
function normalizeAnswer(body: unknown): { value: string | null; text: string } {
  if (typeof body === "object" && body !== null) {
    if ("value" in body) {
      const value = JSON.stringify(body.value);
      return { value, text: `Normalized: ${value}` };
    }
    if ("reason" in body && typeof body.reason === "string") {
      return { value: null, text: `Declined: ${body.reason}` };
    }
  }
  return { value: null, text: "The normalizer gave no value." };
}

function exportHref(page: PageDetail): string {
  return `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(page.labels, null, 2))}`;
}

function exportName({ id }: PageDetail): string {
  return `labels-${id}.json`;
}

function PageEditor({
  page,
  etag,
  notice,
  onSaved,
}: {
  page: PageDetail;
  etag: string | null;
  notice: string | null;
  onSaved: (notice: string) => void;
}) {
  const revalidator = useRevalidator();
  const names = fieldNames(page.page_kind, page.fields);
  const [draft, setDraft] = useState<Draft>(() =>
    draftFrom(page.page_kind, page.fields, page.labels),
  );
  const [pass, setPass] = useState<Pass>("labeler");
  const [labeler, setLabeler] = useState(page.labeler ?? "");
  const [checker, setChecker] = useState("");
  const [target, setTarget] = useState<Target | null>(() => {
    const first = names.page[0];
    return first === undefined ? null : { row: null, name: first };
  });
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [normalized, setNormalized] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  function fieldAt(at: Target): FieldDraft | undefined {
    return at.row === null ? draft.fields[at.name] : draft.rows[at.row]?.[at.name];
  }

  function setField(at: Target, field: FieldDraft): void {
    setDraft((current) =>
      at.row === null
        ? { ...current, fields: { ...current.fields, [at.name]: field } }
        : {
            ...current,
            rows: current.rows.map((row, i) => (i === at.row ? { ...row, [at.name]: field } : row)),
          },
    );
  }

  function pick({ text, locator }: Pick): void {
    if (target === null) return;
    const field = fieldAt(target);
    if (field !== undefined) setField(target, { ...field, rawText: text, locator });
  }

  async function normalize(at: Target): Promise<void> {
    const field = fieldAt(at);
    if (field === undefined) return;
    const { data, error } = await sameOriginClient().POST("/v1/eval/pages/{page_id}/normalize", {
      params: { path: { page_id: page.id } },
      body: { field: at.name, raw_text: field.rawText },
    });
    const answer =
      error === undefined
        ? normalizeAnswer(data)
        : {
            value: null,
            // A problem's detail; FastAPI's own validation errors carry a list instead.
            text: `Not normalized: ${typeof error.detail === "string" ? error.detail : "invalid request"}`,
          };
    if (answer.value !== null) setField(at, { ...field, value: answer.value, absent: false });
    setNormalized((current) => ({ ...current, [pathOf(at)]: answer.text }));
  }

  async function save(status: LabelStatus): Promise<void> {
    setProblem(null);
    setErrors([]);
    setConflict(false);
    const built = toLabels({
      draft,
      status,
      labeler: pass === "labeler" ? labeler : (page.labeler ?? ""),
      checker: pass === "checker" ? checker : null,
      prefillSource: page.labels?.prefill_source ?? null,
    });
    if (built.kind === "invalid") {
      setErrors(built.errors);
      return;
    }
    setSaving(true);
    const { error, response } = await sameOriginClient().PUT("/v1/eval/pages/{page_id}/labels", {
      params: { path: { page_id: page.id }, header: etag === null ? {} : { "if-match": etag } },
      body: built.labels,
    });
    setSaving(false);
    if (error === undefined) {
      onSaved(
        status === "checked"
          ? `Checked by ${checker.trim()}.`
          : `Saved as ${status} by ${labeler.trim()}.`,
      );
      await revalidator.revalidate();
      return;
    }
    if (response.status === 409 || response.status === 412) {
      setConflict(true);
      return;
    }
    const failure = saveFailure(error, response.status);
    setErrors(failure.errors);
    setProblem(failure.detail);
  }

  const checkable = page.status === "labeled" || page.status === "checked";
  const checkerBlocked = !checkable
    ? "Only a labeled page can be checked."
    : checker.trim() === ""
      ? "Enter your name to check this page."
      : page.labeler !== null && samePerson(checker, page.labeler)
        ? `The checker must be someone other than the labeler (${page.labeler}).`
        : null;
  const labelerBlocked = labeler.trim() === "";
  const documentErrors = errors.filter((e) => !isFieldPath(e.field));

  function editor(at: Target, group: string) {
    const field = fieldAt(at);
    const shape = page.fields[at.name];
    if (field === undefined || shape === undefined) return null;
    const path = pathOf(at);
    return (
      <FieldEditor
        key={path}
        name={at.name}
        group={group}
        shape={shape}
        field={field}
        picking={target !== null && pathOf(target) === path}
        errors={reasonsAt(errors, path)}
        normalized={normalized[path] ?? null}
        onChange={(next) => {
          setField(at, next);
        }}
        onFocus={() => {
          setTarget(at);
        }}
        onNormalize={() => void normalize(at)}
      />
    );
  }

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Labeling</h1>
        <SplitBadge split={page.split} />
        <Link href="/labeling">All pages</Link>
      </div>
      <p className="text-sm text-muted">
        {page.schema_name} · {page.page_kind} · {page.category} · {statusText(page.status)}
        {page.labeler === null ? "" : ` · labeled by ${page.labeler}`}
        {page.checker === null ? "" : ` · checked by ${page.checker}`}
      </p>
      {notice === null ? null : <output className="block">{notice}</output>}
      {conflict ? (
        <div role="alert" className="flex flex-wrap items-center gap-3">
          <p>Another pass was saved since this page was opened.</p>
          <Button variant="secondary" onPress={() => void revalidator.revalidate()}>
            Reload the page
          </Button>
        </div>
      ) : null}
      {problem === null && documentErrors.length === 0 ? null : (
        <div role="alert">
          {problem === null ? null : <p>Not saved: {problem}</p>}
          {documentErrors.map((e) => (
            <p key={`${e.field}:${e.reason}`}>
              {e.field === "" ? "Labels" : e.field}: {e.reason}
            </p>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 lg:w-1/2">
          <PageView html={page.bundle_html} onPick={pick} />
        </div>
        <form
          aria-label="Labels"
          className="flex min-w-0 flex-col gap-3 lg:w-1/2"
          onSubmit={(event) => {
            event.preventDefault();
          }}
        >
          <RadioGroup
            value={pass}
            onChange={(value) => {
              setPass(value === "checker" ? "checker" : "labeler");
            }}
            orientation="horizontal"
          >
            <Label>Pass</Label>
            {PASSES.map(([value, label]) => (
              <Radio key={value} value={value}>
                <Radio.Content>
                  <Radio.Control>
                    <Radio.Indicator />
                  </Radio.Control>
                  <Label>{label}</Label>
                </Radio.Content>
              </Radio>
            ))}
          </RadioGroup>
          {pass === "labeler" ? (
            <TextField value={labeler} onChange={setLabeler}>
              <Label>Labeler name</Label>
              <Input />
            </TextField>
          ) : (
            <TextField value={checker} onChange={setChecker}>
              <Label>Checker name</Label>
              <Input />
            </TextField>
          )}
          {names.page.map((name) => editor({ row: null, name }, name))}
          {page.page_kind === "listing" ? (
            <div className="flex flex-col gap-3">
              <h2 className="text-lg font-semibold">Rows</h2>
              {draft.rows.map((_, i) => (
                <div key={i} className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <h3 className="font-medium">Row {i + 1}</h3>
                    <Button
                      variant="secondary"
                      aria-label={`Remove row ${String(i + 1)}`}
                      onPress={() => {
                        setDraft((current) => ({
                          ...current,
                          rows: current.rows.filter((_row, j) => j !== i),
                        }));
                        setTarget(null);
                      }}
                    >
                      Remove
                    </Button>
                  </div>
                  {names.row.map((name) =>
                    editor({ row: i, name }, `row ${String(i + 1)} ${name}`),
                  )}
                </div>
              ))}
              <Button
                variant="secondary"
                onPress={() => {
                  setDraft((current) => ({
                    ...current,
                    rows: [...current.rows, newRow(page.page_kind, page.fields)],
                  }));
                }}
              >
                Add row
              </Button>
            </div>
          ) : null}
          <TextField
            value={draft.notes}
            onChange={(notes) => {
              setDraft((current) => ({ ...current, notes }));
            }}
          >
            <Label>Notes (never a hostname)</Label>
            <TextArea rows={2} />
          </TextField>
          {pass === "labeler" ? (
            <>
              {page.status === "checked" ? (
                <p className="text-sm text-muted">A labeler pass clears the check.</p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  isDisabled={saving || labelerBlocked}
                  onPress={() => void save("draft")}
                >
                  Save draft
                </Button>
                <Button isDisabled={saving || labelerBlocked} onPress={() => void save("labeled")}>
                  Mark labeled
                </Button>
              </div>
            </>
          ) : (
            <>
              {checkerBlocked === null ? null : <p className="text-sm">{checkerBlocked}</p>}
              <div>
                <Button
                  isDisabled={saving || checkerBlocked !== null}
                  onPress={() => void save("checked")}
                >
                  Confirm check
                </Button>
              </div>
            </>
          )}
          {page.labels === null ? null : (
            <Link href={exportHref(page)} download={exportName(page)}>
              Export labels (JSON)
            </Link>
          )}
        </form>
      </div>
    </section>
  );
}
