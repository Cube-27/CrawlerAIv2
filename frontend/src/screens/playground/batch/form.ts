import type { BatchRequest } from "../../../api/jobs";
import type { MethodHint, PageKind } from "../../../api/scrape";
import type { SchemaPageKind } from "../../../api/schemas";
import type { PageFormat } from "../FormatSelect";
import {
  canSend,
  lines,
  requestFormats,
  requestPageKind,
  requestSchema,
  webhook,
} from "../pageRequest";
import {
  methodHint,
  pageFormats,
  pageKind,
  schemaFields,
  schemaId,
  texts,
  webhookUrl,
  type StoredRequest,
} from "../run/storedRequest";

/** Batch's options panel (SPEC-14 §4.2): each is a `BatchScrapeRequest` member, except `metadataInJson`, a view
 * option that asks for the `metadata` format and the results' `include=metadata`. `fields` are the names
 * `schema.fields` drafts a schema from (§4.10). */
export interface BatchOptions {
  pageKind: PageKind | null;
  metadataInJson: boolean;
  fields: readonly string[];
  /** Empty: no webhook. */
  webhookUrl: string;
  methodHint: MethodHint;
}

export const DEFAULT_BATCH_OPTIONS: BatchOptions = {
  pageKind: null,
  metadataInJson: false,
  fields: [],
  webhookUrl: "",
  // FetchPolicy's own default (SPEC-02 §4.2).
  methodHint: "auto",
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

/** The batch request for `form`, or null when it can't be sent (`canSend`). */
export function buildBatch(form: BatchFormState): BatchRequest | null {
  if (!canSend(form)) return null;
  return {
    urls: lines(form.urls),
    formats: requestFormats(form),
    schema: requestSchema(form),
    page_kind: requestPageKind(form),
    fetch: { method_hint: form.options.methodHint },
    ...webhook(form.options.webhookUrl),
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
      webhookUrl: webhookUrl(request),
      methodHint: methodHint(request),
    },
  };
}
