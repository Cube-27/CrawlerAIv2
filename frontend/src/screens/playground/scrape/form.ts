import type { MethodHint, PageKind, ScrapeRequest } from "../../../api/scrape";
import type { SchemaPageKind } from "../../../api/schemas";
import type { PageFormat } from "../FormatSelect";
import { canSend, requestFormats, requestPageKind } from "../pageRequest";

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

/** What the command bar and the options panel hold. */
export interface ScrapeFormState {
  url: string;
  formats: readonly PageFormat[];
  schemaId: string;
  schemaPageKind: SchemaPageKind | null;
  options: ScrapeOptions;
}

export const INITIAL_FORM: ScrapeFormState = {
  url: "",
  formats: ["markdown"],
  schemaId: "",
  schemaPageKind: null,
  options: DEFAULT_OPTIONS,
};

/** The request for `form`, or null when it can't be sent (`canSend`). Empty limits are left out, so the server's
 * defaults apply. */
export function buildRequest(form: ScrapeFormState): ScrapeRequest | null {
  const { options } = form;
  if (!canSend(form)) return null;
  return {
    url: form.url.trim(),
    formats: requestFormats(form),
    schema: form.schemaId === "" ? null : { id: form.schemaId },
    page_kind: requestPageKind(form),
    fetch: { method_hint: options.methodHint },
    ...(Number.isNaN(options.maxAge) ? {} : { max_age: options.maxAge }),
    ...(Number.isNaN(options.timeoutS) ? {} : { timeout_s: options.timeoutS }),
    ...(Number.isNaN(options.llmCalls) ? {} : { budget: { llm_calls: options.llmCalls } }),
  };
}
