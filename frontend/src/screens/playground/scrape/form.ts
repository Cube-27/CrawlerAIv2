import { orderedFormats } from "../../../components/FormatChoices";
import { NO_RECORDS_PAGE_KINDS } from "../../../components/PageKindChoices";
import type { MethodHint, PageKind, ScrapeFormat, ScrapeRequest } from "../../../api/scrape";
import type { SchemaPageKind } from "../../../api/schemas";
import type { PageFormat } from "../FormatSelect";

/** The settings in the options panel (SPEC-14 §4.2): each is a `ScrapeRequest` member, except `metadataInJson`, a view
 * option that asks for the `metadata` format. */
export interface ScrapeOptions {
  pageKind: PageKind | null;
  metadataInJson: boolean;
  methodHint: MethodHint;
  /** NaN while empty: the request then leaves the limit to the server. */
  maxAge: number;
  timeoutS: number;
  llmCalls: number;
}

export const DEFAULT_OPTIONS: ScrapeOptions = {
  pageKind: null,
  metadataInJson: false,
  // FetchPolicy's own default (SPEC-02 §4.2).
  methodHint: "auto",
  maxAge: Number.NaN,
  timeoutS: Number.NaN,
  llmCalls: Number.NaN,
};

/** What the command bar and the options panel hold. `schemaId` is a stored schema's id, or "" for none. */
export interface ScrapeFormState {
  url: string;
  formats: readonly PageFormat[];
  schemaId: string;
  options: ScrapeOptions;
}

export const INITIAL_FORM: ScrapeFormState = {
  url: "",
  formats: ["markdown"],
  schemaId: "",
  options: DEFAULT_OPTIONS,
};

/** Whether any setting differs from its default. SameValue (ECMA-262), so an empty limit (NaN) equals the default. */
export function optionsChanged(options: ScrapeOptions): boolean {
  return (Object.keys(DEFAULT_OPTIONS) as (keyof ScrapeOptions)[]).some(
    (key) => !Object.is(options[key], DEFAULT_OPTIONS[key]),
  );
}

/** `form` with the stored schema `schemaId`. A schema's records need the page kind it is for (SPEC-07 §4.4), so a
 * chosen schema sets it, unless the server refuses that kind's records. */
export function withSchema(
  form: ScrapeFormState,
  schemaId: string,
  schemaPageKind: SchemaPageKind | null,
): ScrapeFormState {
  if (schemaPageKind === null || NO_RECORDS_PAGE_KINDS.includes(schemaPageKind)) {
    return { ...form, schemaId };
  }
  return { ...form, schemaId, options: { ...form.options, pageKind: schemaPageKind } };
}

/** The request's formats: the page formats chosen, `metadata` for Metadata in JSON, and `records` with a schema. */
function requestFormats(form: ScrapeFormState): ScrapeFormat[] {
  return orderedFormats([
    ...form.formats,
    ...(form.options.metadataInJson ? ["metadata"] : []),
    ...(form.schemaId === "" ? [] : ["records"]),
  ]);
}

/** The request for `form`, or null when it has a schema but no page kind, which records need (SPEC-07 §4.4). Empty
 * limits are left out, so the server's defaults apply. */
export function buildRequest(form: ScrapeFormState): ScrapeRequest | null {
  const { options } = form;
  if (form.schemaId !== "" && options.pageKind === null) return null;
  return {
    url: form.url.trim(),
    formats: requestFormats(form),
    schema: form.schemaId === "" ? null : { id: form.schemaId },
    page_kind: options.pageKind,
    fetch: { method_hint: options.methodHint },
    ...(Number.isNaN(options.maxAge) ? {} : { max_age: options.maxAge }),
    ...(Number.isNaN(options.timeoutS) ? {} : { timeout_s: options.timeoutS }),
    ...(Number.isNaN(options.llmCalls) ? {} : { budget: { llm_calls: options.llmCalls } }),
  };
}
