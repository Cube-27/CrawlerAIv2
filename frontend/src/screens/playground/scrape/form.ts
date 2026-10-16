import type { MethodHint, PageKind, ScrapeRequest } from "../../../api/scrape";
import type { SchemaPageKind } from "../../../api/schemas";
import type { PageFormat } from "../FormatSelect";
import {
  canSend,
  llmBudget,
  optionalNumber,
  requestFormats,
  requestPageKind,
  requestSchema,
} from "../pageRequest";
import {
  count,
  llmCalls,
  methodHint,
  pageFormats,
  pageKind,
  schemaFields,
  schemaId,
  text,
  type StoredRequest,
} from "../run/storedRequest";

/** The settings in the options panel (SPEC-14 §4.2): each is a `ScrapeRequest` member, except `metadataInJson`, a view
 * option that asks for the `metadata` format. `fields` are the names `schema.fields` drafts a schema from (§4.10). */
export interface ScrapeOptions {
  pageKind: PageKind | null;
  metadataInJson: boolean;
  fields: readonly string[];
  methodHint: MethodHint;
  /** NaN while empty: the request then leaves the limit to the server. */
  maxAge: number;
  timeoutS: number;
  llmCalls: number;
}

export const DEFAULT_OPTIONS: ScrapeOptions = {
  pageKind: null,
  metadataInJson: false,
  fields: [],
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
    schema: requestSchema(form),
    page_kind: requestPageKind(form),
    fetch: { method_hint: options.methodHint },
    ...optionalNumber("max_age", options.maxAge),
    ...optionalNumber("timeout_s", options.timeoutS),
    ...llmBudget(options.llmCalls),
  };
}

/** The form that shows the stored `request` of a scrape job. A stored schema's page kind is the request's. */
export function scrapeForm(request: StoredRequest): ScrapeFormState {
  const { formats, metadataInJson } = pageFormats(request);
  const id = schemaId(request);
  const kind = pageKind(request);
  return {
    url: text(request, "url"),
    formats,
    schemaId: id,
    schemaPageKind: id === "" ? null : kind,
    options: {
      pageKind: id === "" ? kind : null,
      metadataInJson,
      fields: schemaFields(request),
      methodHint: methodHint(request),
      maxAge: count(request, "max_age"),
      timeoutS: count(request, "timeout_s"),
      llmCalls: llmCalls(request),
    },
  };
}
