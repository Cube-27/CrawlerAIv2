import { toast } from "@heroui/react";
import { useRef, useState } from "react";
import { useRevalidator } from "react-router";
import { sameOriginClient } from "../../api/client";
import {
  draftFrom,
  newRow,
  type Built,
  type Draft,
  type FieldDraft,
  type FieldError,
  type LabelStatus,
  type Pass,
} from "./draft";
import type { PageDetail } from "./loaders";
import type { Pick } from "./PageView";

/** Where a click on the page goes: a top-level field, or a field of one listing row. */
export interface Target {
  row: number | null;
  name: string;
}

export function pathOf({ row, name }: Target): string {
  return row === null ? `fields.${name}` : `rows[${String(row)}].fields.${name}`;
}

/**
 * A problem's `detail` (RFC 9457), or null when the error body is not a problem, such as a proxy's HTML page.
 */
function problemDetail(error: unknown): string | null {
  const detail =
    typeof error === "object" && error !== null ? (error as { detail?: unknown }).detail : null;
  return typeof detail === "string" ? detail : null;
}

/** The field errors of a failed save; a body that is not a problem has none. */
function problemErrors(error: unknown): FieldError[] {
  const errors =
    typeof error === "object" && error !== null ? (error as { errors?: unknown }).errors : null;
  return Array.isArray(errors) ? (errors as FieldError[]) : [];
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

function fieldOf(draft: Draft, at: Target): FieldDraft | undefined {
  return at.row === null ? draft.fields[at.name] : draft.rows[at.row]?.[at.name];
}

function withField(draft: Draft, at: Target, field: FieldDraft): Draft {
  if (at.row === null) return { ...draft, fields: { ...draft.fields, [at.name]: field } };
  return {
    ...draft,
    rows: draft.rows.map((row, i) => (i === at.row ? { ...row, [at.name]: field } : row)),
  };
}

/** The labels being edited, the field that page clicks fill, and the listing rows' keys. */
export function useDraft(page: PageDetail, firstName: string | undefined) {
  const [draft, setDraft] = useState<Draft>(() =>
    draftFrom(page.page_kind, page.fields, page.labels),
  );
  // Rows have no identity in the labels document, so the form numbers them, for React's keys only.
  const rowsMade = useRef(draft.rows.length);
  const [rowKeys, setRowKeys] = useState<number[]>(() => draft.rows.map((_row, i) => i));
  const [target, setTarget] = useState<Target | null>(() =>
    firstName === undefined ? null : { row: null, name: firstName },
  );

  function fieldAt(at: Target): FieldDraft | undefined {
    return fieldOf(draft, at);
  }

  function setField(at: Target, field: FieldDraft): void {
    setDraft((current) => withField(current, at, field));
  }

  function pick({ text, locator }: Pick): void {
    if (target === null) return;
    const field = fieldAt(target);
    if (field !== undefined) setField(target, { ...field, rawText: text, locator });
  }

  function addRow(): void {
    const key = rowsMade.current;
    rowsMade.current += 1;
    setDraft((current) => ({
      ...current,
      rows: [...current.rows, newRow(page.page_kind, page.fields)],
    }));
    setRowKeys((keys) => [...keys, key]);
  }

  function removeRow(index: number): void {
    setDraft((current) => ({ ...current, rows: current.rows.filter((_row, j) => j !== index) }));
    setRowKeys((keys) => keys.filter((_key, j) => j !== index));
    setTarget(null);
  }

  function setNotes(notes: string): void {
    setDraft((current) => ({ ...current, notes }));
  }

  return {
    draft,
    rowKeys,
    target,
    setTarget,
    fieldAt,
    setField,
    pick,
    addRow,
    removeRow,
    setNotes,
  };
}

/** What `/normalize` said per field path, and the action that asks it for one field. */
export function useNormalize(
  pageId: string,
  fieldAt: (at: Target) => FieldDraft | undefined,
  setField: (at: Target, field: FieldDraft) => void,
) {
  const [normalized, setNormalized] = useState<Record<string, string>>({});

  async function normalize(at: Target): Promise<void> {
    const field = fieldAt(at);
    if (field === undefined) return;
    const { data, error } = await sameOriginClient().POST("/v1/eval/pages/{page_id}/normalize", {
      params: { path: { page_id: pageId } },
      body: { field: at.name, raw_text: field.rawText },
    });
    const answer =
      error === undefined
        ? normalizeAnswer(data)
        : { value: null, text: `Not normalized: ${problemDetail(error) ?? "invalid request"}` };
    if (answer.value !== null) setField(at, { ...field, value: answer.value, absent: false });
    setNormalized((current) => ({ ...current, [pathOf(at)]: answer.text }));
  }

  return { normalized, normalize };
}

/** The names a pass is saved under: the labeler pass sets the labeler, the checker pass keeps it and adds a checker. */
export function passNames(
  pass: Pass,
  {
    labeler,
    checker,
    storedLabeler,
  }: { labeler: string; checker: string; storedLabeler: string | null },
): { labeler: string; checker: string | null } {
  if (pass === "labeler") return { labeler, checker: null };
  return { labeler: storedLabeler ?? "", checker };
}

export function savedNotice(
  status: LabelStatus,
  names: { labeler: string; checker: string },
): string {
  if (status === "checked") return `Checked by ${names.checker.trim()}.`;
  return `Saved as ${status} by ${names.labeler.trim()}.`;
}

/** Saving one pass: the save in flight, and what the last save's answer was when it failed. */
export function useSave(pageId: string, etag: string | null) {
  const revalidator = useRevalidator();
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);

  async function save(built: Built, notice: string): Promise<void> {
    setProblem(null);
    setErrors([]);
    setConflict(false);
    if (built.kind === "invalid") {
      setErrors(built.errors);
      return;
    }
    setSaving(true);
    const { error, response } = await sameOriginClient().PUT("/v1/eval/pages/{page_id}/labels", {
      params: { path: { page_id: pageId }, header: etag === null ? {} : { "if-match": etag } },
      body: built.labels,
    });
    setSaving(false);
    if (error === undefined) {
      // A toast outlives the editor, which the reload below remounts with the new ETag.
      toast.success(notice);
      await revalidator.revalidate();
      return;
    }
    if (response.status === 409 || response.status === 412) {
      setConflict(true);
      return;
    }
    setErrors(problemErrors(error));
    setProblem(problemDetail(error) ?? `the server answered ${String(response.status)}.`);
  }

  async function reload(): Promise<void> {
    await revalidator.revalidate();
  }

  return { errors, problem, conflict, saving, save, reload };
}
