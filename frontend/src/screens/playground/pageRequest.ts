import type { PageKind, ScrapeFormat } from "../../api/scrape";
import type { SchemaPageKind } from "../../api/schemas";
import { orderedFormats } from "../../components/FormatChoices";
import { NO_RECORDS_PAGE_KINDS } from "../../components/PageKindChoices";
import type { PageFormat } from "./FormatSelect";

/** What the toolbar's Format and Schema hold, and the Metadata in JSON view option, in every mode that takes them
 * (Scrape, Batch, Crawl; SPEC-14 §4.2). `schemaId` is a stored schema's id, or "" for none; `schemaPageKind` is that
 * schema's page kind. */
export interface FormatForm {
  formats: readonly PageFormat[];
  schemaId: string;
  schemaPageKind: SchemaPageKind | null;
  options: { metadataInJson: boolean };
}

/** A mode whose request names one page kind for every page (Scrape, Batch). */
export interface PageKindForm extends FormatForm {
  options: { metadataInJson: boolean; pageKind: PageKind | null };
}

/** `form` with the stored schema `schemaId`, for `schemaPageKind` pages. */
export function withSchema<F extends FormatForm>(
  form: F,
  schemaId: string,
  schemaPageKind: SchemaPageKind | null,
): F {
  return { ...form, schemaId, schemaPageKind };
}

/** The request's formats: the page formats chosen, `metadata` for Metadata in JSON, and `records` with a schema. */
export function requestFormats(form: FormatForm): ScrapeFormat[] {
  return orderedFormats([
    ...form.formats,
    ...(form.options.metadataInJson ? ["metadata"] : []),
    ...(form.schemaId === "" ? [] : ["records"]),
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
  return kind === null || NO_RECORDS_PAGE_KINDS.includes(kind) ? null : kind;
}

/** Whether `form` can be sent: it asks for some format, and a schema's records are for a page kind it can ask for. */
export function canSend(form: PageKindForm): boolean {
  return !asksForNothing(form) && (form.schemaId === "" || requestPageKind(form) !== null);
}

const NO_ERRORS: Readonly<Record<string, string>> = {};
const NO_FORMAT = { formats: "Choose a format, Metadata in JSON or a schema." };
const NO_SCHEMA_PAGE_KIND = { page_kind: "The schema names no page kind, which its records need." };
const NO_LISTING_RECORDS = { page_kind: "Records of listing pages are not available yet." };

/** Why `form` can't be sent, by field: it asks for no format, or its schema's records are for no page kind it can ask
 * for (its page kind is none, or one the server refuses records of). Derived from the current form, so a change
 * anywhere that fixes it clears it; each answer is one constant, so the errors change only when the reason does. */
export function pageKindErrors(form: PageKindForm): Readonly<Record<string, string>> {
  if (asksForNothing(form)) return NO_FORMAT;
  if (form.schemaId === "" || requestPageKind(form) !== null) return NO_ERRORS;
  return form.schemaPageKind === null ? NO_SCHEMA_PAGE_KIND : NO_LISTING_RECORDS;
}

/** Whether any setting differs from its default. SameValue (ECMA-262), so an empty limit (NaN) equals the default. */
export function optionsChanged<O extends object>(options: O, defaults: O): boolean {
  return (Object.keys(defaults) as (keyof O)[]).some(
    (key) => !Object.is(options[key], defaults[key]),
  );
}
