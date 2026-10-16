import type { PageKind, SchemaRef, ScrapeFormat } from "../../api/scrape";
import type { SchemaPageKind } from "../../api/schemas";
import { orderedFormats } from "../../components/formats";
import type { PageFormat } from "./FormatSelect";

/** The page kinds whose records the server refuses, for a scrape and a batch scrape alike: SPEC-07 §4.4 and D-0502
 * leave listing records out (`check_records`). */
const NO_RECORDS_PAGE_KINDS: ReadonlySet<PageKind> = new Set(["listing"]);

/** The non-blank lines of `text`, trimmed: a list entered one entry per line. */
export function lines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** The optional `webhook_url` member (SPEC-10 §4.2): left out when empty. */
export function webhook(url: string): { webhook_url?: string } {
  const trimmed = url.trim();
  return trimmed === "" ? {} : { webhook_url: trimmed };
}

/** An optional number member: left out while its field is empty (NaN), so the server's default applies. */
export function optionalNumber<K extends string>(
  key: K,
  value: number,
): Partial<Record<K, number>> {
  const member: Partial<Record<K, number>> = {};
  if (!Number.isNaN(value)) member[key] = value;
  return member;
}

/** The optional `budget.llm_calls` member (SPEC-06 §4.8), left out while empty. */
export function llmBudget(llmCalls: number): { budget?: { llm_calls: number } } {
  return Number.isNaN(llmCalls) ? {} : { budget: { llm_calls: llmCalls } };
}

/** What the toolbar's Format and Schema hold, the Metadata in JSON view option and the field names, in every mode
 * that takes them (Scrape, Batch, Crawl; SPEC-14 §4.2, §4.10). `schemaId` is a stored schema's id, or "" for none;
 * `schemaPageKind` is that schema's page kind. */
export interface FormatForm {
  formats: readonly PageFormat[];
  schemaId: string;
  schemaPageKind: SchemaPageKind | null;
  options: { metadataInJson: boolean; fields: readonly string[] };
}

/** A mode whose request names one page kind for every page (Scrape, Batch). */
export interface PageKindForm extends FormatForm {
  options: { metadataInJson: boolean; fields: readonly string[]; pageKind: PageKind | null };
}

/** The request's schema: the stored one, else the field names the server drafts one from (SPEC-14 §4.10), else
 * none. */
export function requestSchema(
  form: FormatForm,
): Extract<SchemaRef, { id: string } | { fields: string[] }> | null {
  if (form.schemaId !== "") return { id: form.schemaId };
  const { fields } = form.options;
  return fields.length === 0 ? null : { fields: [...fields] };
}

/** Whether the request names a schema: a stored one or field names. */
export function hasSchema(form: FormatForm): boolean {
  return form.schemaId !== "" || form.options.fields.length > 0;
}

/** `form` with the stored schema `schemaId`, for `schemaPageKind` pages. */
export function withSchema<F extends Pick<FormatForm, "schemaId" | "schemaPageKind">>(
  form: F,
  schemaId: string,
  schemaPageKind: SchemaPageKind | null,
): F {
  return { ...form, schemaId, schemaPageKind };
}

/** The request's formats: the page formats chosen, `metadata` for Metadata in JSON, and `records` with a schema or
 * field names. */
export function requestFormats(form: FormatForm): ScrapeFormat[] {
  return orderedFormats([
    ...form.formats,
    ...(form.options.metadataInJson ? ["metadata"] : []),
    ...(hasSchema(form) ? ["records"] : []),
  ]);
}

/** Whether `form` asks for no format at all, which the server refuses (SPEC-07 §4.4). */
export function asksForNothing(form: FormatForm): boolean {
  return requestFormats(form).length === 0;
}

/** The page kind the request names. A stored schema's records are for its own page kind only, and not for one the
 * server refuses records of (SPEC-07 §4.4), so with a schema it is that kind, or null when there is none. */
export function requestPageKind(form: PageKindForm): PageKind | null {
  if (form.schemaId === "") return form.options.pageKind;
  const kind = form.schemaPageKind;
  return kind === null || NO_RECORDS_PAGE_KINDS.has(kind) ? null : kind;
}

export const NO_ERRORS: Readonly<Record<string, string>> = {};
export const NO_FORMAT = { formats: "Choose a format, Metadata in JSON, a schema or fields." };
const NO_SCHEMA_PAGE_KIND = { page_kind: "The schema names no page kind, which its records need." };
const NO_LISTING_RECORDS = { page_kind: "Records of listing pages are not available yet." };
export const SCHEMA_AND_FIELDS = { fields: "Use the stored schema or fields, not both." };
const NO_FIELDS_PAGE_KIND = { page_kind: "Choose the page kind the fields are read from." };

/** Why a stored schema's records can't be asked for: it names no page kind, or one the server refuses records of;
 * null when they can. */
export function schemaPageKindErrors(
  schemaPageKind: SchemaPageKind | null,
): Readonly<Record<string, string>> | null {
  if (schemaPageKind === null) return NO_SCHEMA_PAGE_KIND;
  return NO_RECORDS_PAGE_KINDS.has(schemaPageKind) ? NO_LISTING_RECORDS : null;
}

/** Why field names can't be drafted for pages of `pageKind`: none is chosen, or the server refuses its records; null
 * when they can. */
export function fieldsPageKindErrors(
  pageKind: PageKind | null,
): Readonly<Record<string, string>> | null {
  return pageKind === null ? NO_FIELDS_PAGE_KIND : schemaPageKindErrors(pageKind);
}

/** Why `form` can't be sent, by field: it asks for no format; it names a stored schema and fields; its schema's
 * records are for no page kind it can ask for (its page kind is none, or one the server refuses records of); or its
 * fields have no such page kind. Derived from the current form, so a change anywhere that fixes it clears it; each
 * answer is one constant, so the errors change only when the reason does. */
export function pageKindErrors(form: PageKindForm): Readonly<Record<string, string>> {
  if (asksForNothing(form)) return NO_FORMAT;
  const hasFields = form.options.fields.length > 0;
  if (form.schemaId !== "" && hasFields) return SCHEMA_AND_FIELDS;
  if (hasFields) return fieldsPageKindErrors(form.options.pageKind) ?? NO_ERRORS;
  if (form.schemaId === "") return NO_ERRORS;
  return schemaPageKindErrors(form.schemaPageKind) ?? NO_ERRORS;
}

/** Whether `form` can be sent: `pageKindErrors` finds nothing. */
export function canSend(form: PageKindForm): boolean {
  return pageKindErrors(form) === NO_ERRORS;
}

/** SameValue (ECMA-262), so an empty limit (NaN) equals the default; a list equals one with the same entries. */
function sameSetting(value: unknown, other: unknown): boolean {
  if (Array.isArray(value) && Array.isArray(other))
    return value.length === other.length && value.every((entry, i) => sameSetting(entry, other[i]));
  return Object.is(value, other);
}

/** Whether any setting differs from its default. */
export function optionsChanged<O extends object>(options: O, defaults: O): boolean {
  return (Object.keys(defaults) as (keyof O)[]).some(
    (key) => !sameSetting(options[key], defaults[key]),
  );
}
