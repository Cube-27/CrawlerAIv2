import type { BatchRequest } from "../../../api/jobs";
import type { FetchMember, MethodHint, PageKind, ScrapeFormat } from "../../../api/scrape";
import {
  DEFAULT_ADVANCED,
  fetchMember,
  storedAdvanced,
  withFetchErrors,
  type AdvancedFetch,
} from "../advanced";
import type { SchemaPageKind } from "../../../api/schemas";
import type { PageFormat } from "../FormatSelect";
import { badUrlLine } from "./urls";
import {
  DEFAULT_FORMAT_SETTINGS,
  formatMembers,
  storedFormatSettings,
  type FormatSettings,
} from "../formatOptions";
import {
  jobFormats,
  lines,
  llmBudget,
  NO_ERRORS,
  pageKindErrors,
  requestPageKind,
  requestSchema,
  screenshotArea,
  webhook,
  NO_WEBHOOK,
  withWebhookErrors,
  type WebhookSettings,
  minConfidence,
} from "../pageRequest";
import {
  llmCalls,
  maxRows,
  methodHint,
  pageFormats,
  pageKind,
  schemaFields,
  schemaId,
  texts,
  webhookSettings,
  type StoredRequest,
  minConfidencePercent,
} from "../run/storedRequest";

/** Batch's options panel (SPEC-14 §4.2): each is a `BatchScrapeRequest` member, except `metadataInJson`, a view
 * option that asks for the `metadata` format and the results' `include=metadata`. `fields` are the names
 * `schema.fields` drafts a schema from (§4.10). */
export interface BatchOptions extends FormatSettings {
  pageKind: PageKind | null;
  metadataInJson: boolean;
  fields: readonly string[];
  /** An empty URL: no webhook. */
  webhook: WebhookSettings;
  methodHint: MethodHint;
  /** `fetch.max_rows`: NaN while empty. */
  maxRows: number;
  /** `min_confidence` as a percent; NaN (empty) leaves it out: every value publishes with its confidence. */
  minConfidence: number;
  /** The Advanced settings: request context, page actions and cache (D-1430, D-1436). */
  advanced: AdvancedFetch;
  /** `budget.llm_calls`; NaN (empty) leaves `budget` out: the project's limit, or none (D-1121). */
  llmCalls: number;
}

export const DEFAULT_BATCH_OPTIONS: BatchOptions = {
  pageKind: null,
  metadataInJson: false,
  fields: [],
  webhook: NO_WEBHOOK,
  // FetchPolicy's own default (SPEC-02 §4.2).
  methodHint: "auto",
  maxRows: Number.NaN,
  minConfidence: Number.NaN,
  advanced: DEFAULT_ADVANCED,
  llmCalls: Number.NaN,
  ...DEFAULT_FORMAT_SETTINGS,
};

export interface BatchFormState {
  /** One URL per line. */
  urls: string;
  formats: readonly PageFormat[];
  schemaId: string;
  schemaPageKind: SchemaPageKind | null;
  options: BatchOptions;
}

const INITIAL_BATCH: BatchFormState = {
  urls: "",
  formats: ["markdown"],
  schemaId: "",
  schemaPageKind: null,
  options: DEFAULT_BATCH_OPTIONS,
};

/** A new batch's form, its list `urls` (one per line). */
export function initialBatch(urls: string): BatchFormState {
  return { ...INITIAL_BATCH, urls };
}

/** Why `form` can't be sent, by field: a line of the list that is not a web URL (checked here, so the line is named
 * before the server refuses the batch, D-0982), then what `pageKindErrors` finds. */
export function batchErrors(form: BatchFormState): Readonly<Record<string, string>> {
  const bad = badUrlLine(form.urls);
  if (bad !== null) return { urls: `Line ${String(bad.line)} is not a web address: ${bad.text}` };
  const formats = jobFormats(form);
  return withFetchErrors(
    withWebhookErrors(pageKindErrors(form), form.options.webhook),
    batchFetch(form, formats),
    formats,
  );
}

function batchFetch(form: BatchFormState, formats: readonly ScrapeFormat[]): FetchMember {
  const { options } = form;
  return fetchMember(
    options.methodHint,
    options.maxRows,
    options.advanced,
    screenshotArea(formats, options),
  );
}

/** The batch request for `form`, or null when it can't be sent (`batchErrors`). A batch's results are records or page
 * outputs (SPEC-10 §4.5), so with a schema or field names it asks for `records` alone, as a crawl does (D-0980). */
export function buildBatch(form: BatchFormState): BatchRequest | null {
  if (batchErrors(form) !== NO_ERRORS) return null;
  const formats = jobFormats(form);
  return {
    urls: lines(form.urls),
    formats,
    schema: requestSchema(form),
    page_kind: requestPageKind(form),
    fetch: batchFetch(form, formats),
    ...formatMembers(formats, form.options),
    ...llmBudget(form.options.llmCalls),
    ...minConfidence(form.options.minConfidence),
    ...webhook(form.options.webhook),
  };
}

/** The form that shows the stored `request` of a batch job. A stored schema's page kind is the request's. */
export function batchForm(request: StoredRequest): BatchFormState {
  const { formats, metadataInJson } = pageFormats(request);
  const id = schemaId(request);
  const kind = pageKind(request);
  return {
    urls: texts(request, "urls").join("\n"),
    formats,
    schemaId: id,
    schemaPageKind: id === "" ? null : kind,
    options: {
      pageKind: id === "" ? kind : null,
      metadataInJson,
      fields: schemaFields(request),
      webhook: webhookSettings(request),
      methodHint: methodHint(request),
      maxRows: maxRows(request),
      minConfidence: minConfidencePercent(request),
      advanced: storedAdvanced(request),
      llmCalls: llmCalls(request),
      ...storedFormatSettings(request),
    },
  };
}
