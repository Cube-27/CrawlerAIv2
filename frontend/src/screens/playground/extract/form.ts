import type { ExtractRequest } from "../../../api/jobs";
import { parseJsonObject } from "../../../api/json";
import type { FetchMember, MethodHint, PageKind, SchemaRef } from "../../../api/scrape";
import {
  DEFAULT_ADVANCED,
  fetchMember,
  storedAdvanced,
  withFetchErrors,
  type AdvancedFetch,
} from "../advanced";
import type { SchemaPageKind } from "../../../api/schemas";
import {
  llmBudget,
  NO_ERRORS,
  optionalNumber,
  schemaPageKindErrors,
  webhook,
  NO_WEBHOOK,
  withWebhookErrors,
  type WebhookSettings,
  minConfidence,
} from "../pageRequest";
import {
  count,
  llmCalls,
  maxRows,
  member,
  methodHint,
  pageKind,
  schemaFields,
  schemaId,
  text,
  texts,
  webhookSettings,
  type StoredRequest,
  minConfidencePercent,
} from "../run/storedRequest";

/** Where an extract's schema comes from, chosen in the toolbar's Schema: a stored one, inline JSON, or
 * a draft from a prompt or from field names. */
export type SchemaSource = "id" | "inline" | "prompt" | "fields";

/** Extract's options panel: each is an `ExtractRequest` member. An empty limit (NaN) or text is left
 * out, so the server's default applies. */
export interface ExtractOptions {
  /** The URLs and globs after the bar's. */
  urls: readonly string[];
  /** A SchemaDef as JSON text, for `inline`. */
  inlineSchema: string;
  prompt: string;
  /** The names a `fields` schema is drafted from. */
  fields: readonly string[];
  /** The page kind of an inline, prompt or fields schema; a stored schema's is its own. */
  pageKind: PageKind | null;
  limit: number;
  methodHint: MethodHint;
  /** `fetch.max_rows`: NaN while empty. */
  maxRows: number;
  /** `min_confidence` as a percent; NaN (empty) leaves it out: every value publishes with its confidence. */
  minConfidence: number;
  /** The Advanced settings: request context, page actions and cache. */
  advanced: AdvancedFetch;
  llmCalls: number;
  /** An empty URL: no webhook. */
  webhook: WebhookSettings;
}

export const DEFAULT_EXTRACT_OPTIONS: ExtractOptions = {
  urls: [],
  inlineSchema: "",
  prompt: "",
  fields: [],
  pageKind: null,
  limit: Number.NaN,
  // FetchPolicy's own default.
  methodHint: "auto",
  maxRows: Number.NaN,
  minConfidence: Number.NaN,
  advanced: DEFAULT_ADVANCED,
  llmCalls: Number.NaN,
  webhook: NO_WEBHOOK,
};

/** `schemaSource` and the stored `schemaId` are the toolbar's Schema; the source's JSON, prompt or names are
 * options. */
export interface ExtractFormState {
  url: string;
  schemaSource: SchemaSource;
  schemaId: string;
  schemaPageKind: SchemaPageKind | null;
  options: ExtractOptions;
}

export const INITIAL_EXTRACT: ExtractFormState = {
  url: "",
  schemaSource: "id",
  schemaId: "",
  schemaPageKind: null,
  options: DEFAULT_EXTRACT_OPTIONS,
};

const NO_SCHEMA = { schema: "Choose a schema." };
const NOT_JSON = { inline_schema: "Enter a SchemaDef as a JSON object." };
const NO_PROMPT = { prompt: "Describe the fields to extract." };
const NO_FIELDS = { fields: "Add the names of the fields to extract." };
const NO_PAGE_KIND = { page_kind: "Choose the page kind of the records." };

/** The page kind the request names: the stored schema's, else the one chosen. */
function extractPageKind(form: ExtractFormState): PageKind | null {
  return form.schemaSource === "id" ? form.schemaPageKind : form.options.pageKind;
}

/** The request's schema, or null while it is incomplete. */
function extractSchema(form: ExtractFormState): SchemaRef | null {
  const { options } = form;
  switch (form.schemaSource) {
    case "id":
      return form.schemaId === "" ? null : { id: form.schemaId };
    case "prompt":
      return options.prompt.trim() === "" ? null : { prompt: options.prompt.trim() };
    case "fields":
      return options.fields.length === 0 ? null : { fields: [...options.fields] };
    case "inline": {
      const inline = parseJsonObject(options.inlineSchema);
      return inline === null ? null : { inline };
    }
    default: {
      const exhaustive: never = form.schemaSource;
      return exhaustive;
    }
  }
}

const SOURCE_ERRORS: Readonly<Record<SchemaSource, Readonly<Record<string, string>>>> = {
  id: NO_SCHEMA,
  inline: NOT_JSON,
  prompt: NO_PROMPT,
  fields: NO_FIELDS,
};

/** Why `form` can't be sent, by field: an extract needs a schema, and records of one page kind. */
export function extractErrors(form: ExtractFormState): Readonly<Record<string, string>> {
  return withFetchErrors(
    withWebhookErrors(requestErrors(form), form.options.webhook),
    extractFetch(form),
    [],
  );
}

function extractFetch(form: ExtractFormState): FetchMember {
  const { options } = form;
  return fetchMember(options.methodHint, options.maxRows, options.advanced);
}

function requestErrors(form: ExtractFormState): Readonly<Record<string, string>> {
  if (extractSchema(form) === null) return SOURCE_ERRORS[form.schemaSource];
  const kind = extractPageKind(form);
  if (form.schemaSource !== "id" && kind === null) return NO_PAGE_KIND;
  return schemaPageKindErrors(kind) ?? NO_ERRORS;
}

/** The extract request for `form`, or null when it can't be sent (`extractErrors`). The bar's URL comes first. */
export function buildExtract(form: ExtractFormState): ExtractRequest | null {
  const schema = extractSchema(form);
  const kind = extractPageKind(form);
  if (schema === null || kind === null || extractErrors(form) !== NO_ERRORS) return null;
  const { options } = form;
  return {
    urls: [form.url, ...options.urls],
    schema,
    page_kind: kind,
    fetch: extractFetch(form),
    ...optionalNumber("limit", options.limit),
    ...llmBudget(options.llmCalls),
    ...minConfidence(options.minConfidence),
    ...webhook(options.webhook),
  };
}

/** The form that shows the stored `request` of an extract job. */
export function extractForm(request: StoredRequest): ExtractFormState {
  const [url = "", ...urls] = texts(request, "urls");
  const schema = member(request, "schema");
  const id = schemaId(request);
  let schemaSource: SchemaSource = "id";
  if ("inline" in schema) schemaSource = "inline";
  else if ("prompt" in schema) schemaSource = "prompt";
  else if ("fields" in schema) schemaSource = "fields";
  const kind = pageKind(request);
  return {
    url,
    schemaSource,
    schemaId: id,
    schemaPageKind: id === "" ? null : kind,
    options: {
      urls,
      inlineSchema:
        schemaSource === "inline" ? JSON.stringify(member(schema, "inline"), null, 2) : "",
      prompt: text(schema, "prompt"),
      fields: schemaFields(request),
      pageKind: schemaSource === "id" ? null : kind,
      limit: count(request, "limit"),
      methodHint: methodHint(request),
      maxRows: maxRows(request),
      minConfidence: minConfidencePercent(request),
      advanced: storedAdvanced(request),
      llmCalls: llmCalls(request),
      webhook: webhookSettings(request),
    },
  };
}
