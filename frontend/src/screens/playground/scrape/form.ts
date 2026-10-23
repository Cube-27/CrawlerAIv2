import type {
  FetchMember,
  MethodHint,
  PageKind,
  PagingHint,
  ScrapeFormat,
  ScrapeRequest,
} from "../../../api/scrape";
import {
  DEFAULT_ADVANCED,
  fetchMember,
  storedAdvanced,
  withFetchErrors,
  type AdvancedFetch,
} from "../advanced";
import type { SchemaPageKind } from "../../../api/schemas";
import type { PageFormat } from "../FormatSelect";
import {
  DEFAULT_FORMAT_SETTINGS,
  formatMembers,
  storedFormatSettings,
  type FormatSettings,
} from "../formatOptions";
import {
  llmBudget,
  NO_ERRORS,
  pageKindErrors,
  optionalNumber,
  requestFormats,
  requestPageKind,
  requestSchema,
  screenshotArea,
  minConfidence,
} from "../pageRequest";
import {
  count,
  llmCalls,
  maxRows,
  member,
  methodHint,
  pageFormats,
  pageKind,
  schemaFields,
  schemaId,
  text,
  type StoredRequest,
  minConfidencePercent,
} from "../run/storedRequest";

/** The settings in the options panel: each is a `ScrapeRequest` member, except `metadataInJson`, a view
 * option that asks for the `metadata` format. `fields` are the names `schema.fields` drafts a schema from. */
export interface ScrapeOptions extends FormatSettings {
  pageKind: PageKind | null;
  metadataInJson: boolean;
  fields: readonly string[];
  methodHint: MethodHint;
  /** NaN while empty: the request then leaves the limit to the server. */
  maxAge: number;
  timeoutS: number;
  llmCalls: number;
  /** `fetch.max_rows`: NaN while empty (every page, up to the server's cap). */
  maxRows: number;
  /** `min_confidence` as a percent; NaN (empty) leaves it out: every value publishes with its confidence. */
  minConfidence: number;
  /** The Advanced settings: request context, page actions and cache. */
  advanced: AdvancedFetch;
  /** Browser actions: sent only for listing pages. `records` is NaN while empty (the server's 100), and a
   * null `pagingHint` lets the server detect the mechanism. */
  browserActions: boolean;
  records: number;
  pagingHint: PagingHint | null;
}

export const DEFAULT_OPTIONS: ScrapeOptions = {
  pageKind: null,
  metadataInJson: false,
  fields: [],
  // FetchPolicy's own default.
  methodHint: "auto",
  maxAge: Number.NaN,
  timeoutS: Number.NaN,
  llmCalls: Number.NaN,
  maxRows: Number.NaN,
  minConfidence: Number.NaN,
  advanced: DEFAULT_ADVANCED,
  browserActions: false,
  records: Number.NaN,
  pagingHint: null,
  ...DEFAULT_FORMAT_SETTINGS,
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

/** Why `form` can't be sent, by field: what `pageKindErrors` finds, then the `fetch` member's (`withFetchErrors`). */
export function scrapeErrors(form: ScrapeFormState): Readonly<Record<string, string>> {
  const formats = requestFormats(form);
  return withFetchErrors(pageKindErrors(form), scrapeFetch(form, formats), formats);
}

function scrapeFetch(form: ScrapeFormState, formats: readonly ScrapeFormat[]): FetchMember {
  const { options } = form;
  return fetchMember(
    options.methodHint,
    options.maxRows,
    options.advanced,
    screenshotArea(formats, options),
  );
}

/** The request for `form`, or null when it can't be sent (`scrapeErrors`). Empty limits are left out, so the
 * server's defaults apply. */
export function buildRequest(form: ScrapeFormState): ScrapeRequest | null {
  const { options } = form;
  if (scrapeErrors(form) !== NO_ERRORS) return null;
  const formats = requestFormats(form);
  return {
    url: form.url.trim(),
    formats,
    schema: requestSchema(form),
    page_kind: requestPageKind(form),
    fetch: scrapeFetch(form, formats),
    ...formatMembers(formats, options),
    ...optionalNumber("max_age", options.maxAge),
    ...optionalNumber("timeout_s", options.timeoutS),
    ...llmBudget(options.llmCalls),
    ...minConfidence(options.minConfidence),
    ...browserActions(options, requestPageKind(form)),
  };
}

/** Whether browser actions apply: a listing fetched now in a browser, so not with the HTTP method or a
 * positive max age, which the server refuses with them. */
export function browserActionsApply(options: ScrapeOptions, kind: PageKind | null): boolean {
  return kind === "listing" && options.methodHint !== "http" && !(options.maxAge > 0);
}

/** `browser_actions`, only where they apply, with the members that are set. */
function browserActions(
  options: ScrapeOptions,
  kind: PageKind | null,
): { browser_actions?: { records?: number; hint?: PagingHint } } {
  if (!options.browserActions || !browserActionsApply(options, kind)) return {};
  return {
    browser_actions: {
      ...optionalNumber("records", options.records),
      ...(options.pagingHint === null ? {} : { hint: options.pagingHint }),
    },
  };
}

const PAGING_HINTS: readonly PagingHint[] = [
  "load_more",
  "show_more",
  "pagination",
  "next",
  "scroll",
];

/** The stored request's `browser_actions` as the options show them. */
function storedBrowserActions(
  request: StoredRequest,
): Pick<ScrapeOptions, "browserActions" | "records" | "pagingHint"> {
  const actions = request["browser_actions"];
  const stored = member(request, "browser_actions");
  const hint = PAGING_HINTS.find((option) => option === stored["hint"]) ?? null;
  return {
    browserActions: actions !== undefined && actions !== null,
    records: count(stored, "records"),
    pagingHint: hint,
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
      maxRows: maxRows(request),
      minConfidence: minConfidencePercent(request),
      advanced: storedAdvanced(request),
      ...storedBrowserActions(request),
      ...storedFormatSettings(request),
    },
  };
}
