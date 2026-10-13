import { Button, Input, Label, Link, Radio, RadioGroup, TextArea, TextField } from "@heroui/react";
import { PageHeader } from "../../components/PageHeader";
import { useState, type ReactNode } from "react";
import { useLoaderData } from "react-router";
import {
  fieldNames,
  samePerson,
  toLabels,
  type FieldError,
  type LabelStatus,
  type Pass,
} from "./draft";
import {
  passNames,
  pathOf,
  savedNotice,
  useDraft,
  useNormalize,
  useSave,
  type Target,
} from "./editorState";
import { EvalUiOff } from "./EvalUiOff";
import { FieldEditor } from "./FieldEditor";
import { SplitBadge, statusText } from "./LabelingList";
import type { PageDetail, pageLoader } from "./loaders";
import { PageView } from "./PageView";

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

function exportHref(page: PageDetail): string {
  return `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(page.labels, null, 2))}`;
}

function exportName({ id }: PageDetail): string {
  return `labels-${id}.json`;
}

/** Why the checker pass cannot be confirmed yet, or null when it can. */
function checkerBlockReason(page: PageDetail, checker: string): string | null {
  if (page.status !== "labeled" && page.status !== "checked") {
    return "Only a labeled page can be checked.";
  }
  if (checker.trim() === "") return "Enter your name to check this page.";
  if (page.labeler !== null && samePerson(checker, page.labeler)) {
    return `The checker must be someone other than the labeler (${page.labeler}).`;
  }
  return null;
}

function LabelingHeader({ page }: Readonly<{ page: PageDetail }>) {
  return (
    <>
      <PageHeader title="Labeling">
        <SplitBadge split={page.split} />
        <Link href="/labeling">All pages</Link>
      </PageHeader>
      <p className="text-sm text-muted">
        {page.schema_name} · {page.page_kind} · {page.category} · {statusText(page.status)}
        {page.labeler === null ? "" : ` · labeled by ${page.labeler}`}
        {page.checker === null ? "" : ` · checked by ${page.checker}`}
      </p>
    </>
  );
}

function ConflictAlert({ onReload }: Readonly<{ onReload: () => void }>) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3">
      <p>Another pass was saved since this page was opened.</p>
      <Button variant="secondary" onPress={onReload}>
        Reload the page
      </Button>
    </div>
  );
}

/** A failed save's problem, and the errors that belong to no one field. */
function SaveProblems({
  problem,
  errors,
}: Readonly<{ problem: string | null; errors: FieldError[] }>) {
  if (problem === null && errors.length === 0) return null;
  return (
    <div role="alert">
      {problem === null ? null : <p>Not saved: {problem}</p>}
      {errors.map((e) => (
        <p key={`${e.field}:${e.reason}`}>
          {e.field === "" ? "Labels" : e.field}: {e.reason}
        </p>
      ))}
    </div>
  );
}

function PassPicker({ pass, onChange }: Readonly<{ pass: Pass; onChange: (pass: Pass) => void }>) {
  return (
    <RadioGroup
      value={pass}
      onChange={(value) => {
        onChange(value === "checker" ? "checker" : "labeler");
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
  );
}

function NameField({
  label,
  value,
  onChange,
}: Readonly<{ label: string; value: string; onChange: (value: string) => void }>) {
  return (
    <TextField value={value} onChange={onChange}>
      <Label>{label}</Label>
      <Input />
    </TextField>
  );
}

/** A listing page's rows, each with its row-scoped fields, and the buttons that add and remove rows. */
function RowsEditor({
  rowKeys,
  rowNames,
  editor,
  onAdd,
  onRemove,
}: Readonly<{
  rowKeys: number[];
  rowNames: string[];
  editor: (at: Target, group: string) => ReactNode;
  onAdd: () => void;
  onRemove: (row: number) => void;
}>) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Rows</h2>
      {rowKeys.map((key, i) => (
        <div key={key} className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">Row {i + 1}</h3>
            <Button
              variant="secondary"
              aria-label={`Remove row ${String(i + 1)}`}
              onPress={() => {
                onRemove(i);
              }}
            >
              Remove
            </Button>
          </div>
          {rowNames.map((name) => editor({ row: i, name }, `row ${String(i + 1)} ${name}`))}
        </div>
      ))}
      <Button variant="secondary" onPress={onAdd}>
        Add row
      </Button>
    </div>
  );
}

function LabelerActions({
  clearsCheck,
  disabled,
  onSave,
}: Readonly<{ clearsCheck: boolean; disabled: boolean; onSave: (status: LabelStatus) => void }>) {
  return (
    <>
      {clearsCheck ? <p className="text-sm text-muted">A labeler pass clears the check.</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          isDisabled={disabled}
          onPress={() => {
            onSave("draft");
          }}
        >
          Save draft
        </Button>
        <Button
          isDisabled={disabled}
          onPress={() => {
            onSave("labeled");
          }}
        >
          Mark labeled
        </Button>
      </div>
    </>
  );
}

function CheckerActions({
  blocked,
  disabled,
  onSave,
}: Readonly<{ blocked: string | null; disabled: boolean; onSave: (status: LabelStatus) => void }>) {
  return (
    <>
      {blocked === null ? null : <p className="text-sm">{blocked}</p>}
      <div>
        <Button
          isDisabled={disabled}
          onPress={() => {
            onSave("checked");
          }}
        >
          Confirm check
        </Button>
      </div>
    </>
  );
}

function PageEditor({
  page,
  etag,
  notice,
  onSaved,
}: Readonly<{
  page: PageDetail;
  etag: string | null;
  notice: string | null;
  onSaved: (notice: string) => void;
}>) {
  const names = fieldNames(page.page_kind, page.fields);
  const edit = useDraft(page, names.page[0]);
  const { normalized, normalize } = useNormalize(page.id, edit.fieldAt, edit.setField);
  const saver = useSave(page.id, etag, onSaved);
  const [pass, setPass] = useState<Pass>("labeler");
  const [labeler, setLabeler] = useState(page.labeler ?? "");
  const [checker, setChecker] = useState("");
  const checkerBlocked = checkerBlockReason(page, checker);

  function save(status: LabelStatus): void {
    const built = toLabels({
      draft: edit.draft,
      status,
      ...passNames(pass, { labeler, checker, storedLabeler: page.labeler }),
      prefillSource: page.labels?.prefill_source ?? null,
    });
    void saver.save(built, savedNotice(status, { labeler, checker }));
  }

  function editor(at: Target, group: string) {
    const field = edit.fieldAt(at);
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
        picking={edit.target !== null && pathOf(edit.target) === path}
        errors={reasonsAt(saver.errors, path)}
        normalized={normalized[path] ?? null}
        onChange={(next) => {
          edit.setField(at, next);
        }}
        onFocus={() => {
          edit.setTarget(at);
        }}
        onNormalize={() => void normalize(at)}
      />
    );
  }

  return (
    <section className="flex flex-col gap-4">
      <LabelingHeader page={page} />
      {notice === null ? null : <output className="block">{notice}</output>}
      {saver.conflict ? <ConflictAlert onReload={() => void saver.reload()} /> : null}
      <SaveProblems
        problem={saver.problem}
        errors={saver.errors.filter((e) => !isFieldPath(e.field))}
      />
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 lg:w-1/2">
          <PageView html={page.bundle_html} onPick={edit.pick} />
        </div>
        <form
          aria-label="Labels"
          className="flex min-w-0 flex-col gap-3 lg:w-1/2"
          onSubmit={(event) => {
            event.preventDefault();
          }}
        >
          <PassPicker pass={pass} onChange={setPass} />
          {pass === "labeler" ? (
            <NameField label="Labeler name" value={labeler} onChange={setLabeler} />
          ) : (
            <NameField label="Checker name" value={checker} onChange={setChecker} />
          )}
          {names.page.map((name) => editor({ row: null, name }, name))}
          {page.page_kind === "listing" ? (
            <RowsEditor
              rowKeys={edit.rowKeys}
              rowNames={names.row}
              editor={editor}
              onAdd={edit.addRow}
              onRemove={edit.removeRow}
            />
          ) : null}
          <TextField value={edit.draft.notes} onChange={edit.setNotes}>
            <Label>Notes (never a hostname)</Label>
            <TextArea rows={2} />
          </TextField>
          {pass === "labeler" ? (
            <LabelerActions
              clearsCheck={page.status === "checked"}
              disabled={saver.saving || labeler.trim() === ""}
              onSave={save}
            />
          ) : (
            <CheckerActions
              blocked={checkerBlocked}
              disabled={saver.saving || checkerBlocked !== null}
              onSave={save}
            />
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
