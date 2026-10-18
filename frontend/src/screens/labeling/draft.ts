import type { components } from "../../api/schema";

export type Labels = components["schemas"]["Labels"];
export type FieldLabel = components["schemas"]["FieldLabel"];
export type FieldShape = components["schemas"]["PageDetail"]["fields"][string];
export type LabelStatus = Labels["status"];
export type Pass = "labeler" | "checker";

/** One field as the form edits it: JSON values are kept as the text the person typed until the pass is saved. */
export interface FieldDraft {
  rawText: string;
  value: string; // JSON text of the normalized value
  absent: boolean;
  locator: string;
  distractors: string; // one JSON value per line
}

export type FieldDrafts = Record<string, FieldDraft>;

export interface Draft {
  fields: FieldDrafts; // detail-page fields, or a listing page's page-scoped fields
  rows: FieldDrafts[]; // listing pages only, in page order
  // Row-mapped fields' labels (SPEC-13 §4.10), as stored: the form does not edit them, and a save keeps them.
  lists: Labels["lists"];
  notes: string;
}

export interface FieldError {
  field: string; // dotted path in the labels document, as the API reports it
  reason: string;
}

export const emptyField: FieldDraft = {
  rawText: "",
  value: "",
  absent: false,
  locator: "",
  distractors: "",
};

/** The fields a page's labels have at the top level, and those each listing row has (SPEC-03 §4.3). A row-mapped
 * field (one with a `key`) is labeled as rows under `lists` (SPEC-13 §4.10), which this form does not edit. */
export function fieldNames(
  pageKind: "detail" | "listing",
  shapes: Record<string, FieldShape>,
): { page: string[]; row: string[] } {
  const names = Object.keys(shapes).filter((name) => shapes[name]?.key == null);
  // On a detail page every field belongs to the one entity, whatever its scope (SPEC-04 §4.2).
  if (pageKind === "detail") return { page: names, row: [] };
  return {
    page: names.filter((name) => shapes[name]?.scope === "page"),
    row: names.filter((name) => shapes[name]?.scope === "row"),
  };
}

function fieldDraft(label: FieldLabel | undefined): FieldDraft {
  if (label === undefined) return emptyField;
  return {
    rawText: "",
    value: label.absent || label.value === undefined ? "" : JSON.stringify(label.value),
    absent: label.absent,
    locator: label.locator ?? "",
    distractors: label.distractors.map((value) => JSON.stringify(value)).join("\n"),
  };
}

function fieldDrafts(names: string[], labels: Record<string, FieldLabel>): FieldDrafts {
  return Object.fromEntries(names.map((name) => [name, fieldDraft(labels[name])]));
}

/** The form's starting state: the stored labels, or empty fields for a page not labeled yet. */
export function draftFrom(
  pageKind: "detail" | "listing",
  shapes: Record<string, FieldShape>,
  labels: Labels | null,
): Draft {
  const names = fieldNames(pageKind, shapes);
  return {
    fields: fieldDrafts(names.page, labels?.fields ?? {}),
    rows: (labels?.rows ?? []).map((row) => fieldDrafts(names.row, row.fields)),
    lists: labels?.lists ?? {},
    notes: labels?.notes ?? "",
  };
}

export function newRow(pageKind: "detail" | "listing", shapes: Record<string, FieldShape>) {
  return fieldDrafts(fieldNames(pageKind, shapes).row, {});
}

function unlabeled(field: FieldDraft): boolean {
  return (
    !field.absent &&
    field.value.trim() === "" &&
    field.locator.trim() === "" &&
    field.distractors.trim() === ""
  );
}

function parseJson(text: string): { ok: true; value: unknown } | { ok: false } {
  try {
    return { ok: true, value: JSON.parse(text) as unknown };
  } catch {
    return { ok: false };
  }
}

function fieldLabels(
  path: string,
  drafts: FieldDrafts,
  errors: FieldError[],
): Record<string, FieldLabel> {
  const labels: Record<string, FieldLabel> = {};
  for (const [name, field] of Object.entries(drafts)) {
    // A field left empty is unlabeled: a draft may keep it so, and the API names it in a labeled pass.
    if (unlabeled(field)) continue;
    const at = `${path}.${name}`;
    const distractors: unknown[] = [];
    field.distractors.split("\n").forEach((line, i) => {
      if (line.trim() === "") return;
      const parsed = parseJson(line);
      if (parsed.ok) distractors.push(parsed.value);
      else errors.push({ field: `${at}.distractors[${String(i)}]`, reason: "not a JSON value" });
    });
    let value: unknown = null;
    if (!field.absent) {
      const parsed = parseJson(field.value);
      if (parsed.ok) value = parsed.value;
      else errors.push({ field: `${at}.value`, reason: "not a JSON value" });
    }
    labels[name] = {
      value,
      absent: field.absent,
      locator: field.absent || field.locator.trim() === "" ? null : field.locator.trim(),
      distractors,
    };
  }
  return labels;
}

export type Built = { kind: "labels"; labels: Labels } | { kind: "invalid"; errors: FieldError[] };

/** The labels document for one pass (SPEC-03 §4.3), or the fields whose JSON does not parse. Everything else is
 * the API's to check (§4.10): the screen holds no normalization or schema rules of its own. */
export function toLabels({
  draft,
  status,
  labeler,
  checker,
  prefillSource,
}: {
  draft: Draft;
  status: LabelStatus;
  labeler: string;
  checker: string | null;
  prefillSource: string | null;
}): Built {
  const errors: FieldError[] = [];
  const labels: Labels = {
    // Version 2 only when the page has row labels, so a version 1 document saves as it was read.
    label_version: Object.keys(draft.lists).length > 0 ? 2 : 1,
    status,
    labeler: labeler.trim() === "" ? null : labeler.trim(),
    checker: checker === null ? null : checker.trim(),
    prefill_source: prefillSource,
    fields: fieldLabels("fields", draft.fields, errors),
    // A row a person labels from the capture is one the capture shows: no labeled row is stale (`eval re-key`).
    rows: draft.rows.map((row, i) => ({
      fields: fieldLabels(`rows[${String(i)}].fields`, row, errors),
      stale: false,
    })),
    lists: draft.lists,
    notes: draft.notes,
  };
  return errors.length > 0 ? { kind: "invalid", errors } : { kind: "labels", labels };
}

// Unicode full case folding, as the API's `str.casefold`, is close to upper- then lower-casing ("ß" -> "ss").
function folded(name: string): string {
  return name.trim().toUpperCase().toLowerCase();
}

/** Whether two names are the same person's, compared as the API compares them. The API decides; this only lets
 * the screen say so before a save. */
export function samePerson(a: string, b: string): boolean {
  return folded(a) === folded(b);
}
