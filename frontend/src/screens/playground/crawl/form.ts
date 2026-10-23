import type { CrawlRequest, CrawlStrategy } from "../../../api/jobs";
import { isJsonObject } from "../../../api/json";
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
import {
  DEFAULT_FORMAT_SETTINGS,
  formatMembers,
  storedFormatSettings,
  type FormatSettings,
} from "../formatOptions";
import {
  asksForNothing,
  fieldsPageKindErrors,
  jobFormats,
  NO_ERRORS,
  NO_FORMAT,
  optionalNumber,
  requestSchema,
  SCHEMA_AND_FIELDS,
  schemaPageKindErrors,
  screenshotArea,
  webhook,
  NO_WEBHOOK,
  withWebhookErrors,
  type WebhookSettings,
  minConfidence,
} from "../pageRequest";
import {
  count,
  flag,
  maxRows,
  methodHint,
  pageFormats,
  pageKind,
  schemaFields,
  schemaId,
  text,
  texts,
  webhookSettings,
  type StoredRequest,
  minConfidencePercent,
} from "../run/storedRequest";

/** One page-kind rule as edited: `key` keeps a row's inputs when another row is removed. */
export interface RuleRow {
  key: string;
  pattern: string;
  pageKind: PageKind;
}

/** Crawl's options panel: each is a `CrawlRequest` member, except `metadataInJson`, a view option.
 * `fields` are the names `schema.fields` drafts a schema from. An empty limit (NaN) is left out, so the
 * server's default applies. */
export interface CrawlOptions extends FormatSettings {
  include: readonly string[];
  exclude: readonly string[];
  rules: readonly RuleRow[];
  metadataInJson: boolean;
  fields: readonly string[];
  maxDepth: number;
  limit: number;
  /**
   * How the frontier is ordered; `query` and `keywords` order a
   * best-first crawl only.
   */
  strategy: CrawlStrategy;
  query: string;
  keywords: readonly string[];
  allowSubdomains: boolean;
  allowExternal: boolean;
  methodHint: MethodHint;
  /** `fetch.max_rows`: NaN while empty. */
  maxRows: number;
  /** `min_confidence` as a percent; NaN (empty) leaves it out: every value publishes with its confidence. */
  minConfidence: number;
  /** The Advanced settings: request context, page actions and cache. */
  advanced: AdvancedFetch;
  /** An empty URL: no webhook. */
  webhook: WebhookSettings;
}

export const DEFAULT_CRAWL_OPTIONS: CrawlOptions = {
  include: [],
  exclude: [],
  rules: [],
  metadataInJson: false,
  fields: [],
  maxDepth: Number.NaN,
  limit: Number.NaN,
  // CrawlRequest's own defaults.
  strategy: "bfs",
  query: "",
  keywords: [],
  allowSubdomains: false,
  allowExternal: false,
  // FetchPolicy's own default.
  methodHint: "auto",
  maxRows: Number.NaN,
  minConfidence: Number.NaN,
  advanced: DEFAULT_ADVANCED,
  webhook: NO_WEBHOOK,
  ...DEFAULT_FORMAT_SETTINGS,
};

export interface CrawlFormState {
  url: string;
  formats: readonly PageFormat[];
  schemaId: string;
  schemaPageKind: SchemaPageKind | null;
  options: CrawlOptions;
}

export const INITIAL_CRAWL: CrawlFormState = {
  url: "",
  formats: ["markdown"],
  schemaId: "",
  schemaPageKind: null,
  options: DEFAULT_CRAWL_OPTIONS,
};

/** The rules that are sent: those with a pattern. */
function setRules(rules: readonly RuleRow[]): RuleRow[] {
  return rules.filter(({ pattern }) => pattern.trim() !== "");
}

const NO_RULES = {
  page_kind_rules:
    "A schema's records need a page-kind rule: a page no rule matches is not extracted.",
};
const MIXED_RULES = {
  page_kind_rules: "Fields are drafted for one page kind: give every rule the same page kind.",
};

/** Why field names can't be sent: they need rules, all of one page kind. */
function fieldsErrors(rules: readonly RuleRow[]): Readonly<Record<string, string>> {
  const kinds = new Set(setRules(rules).map((rule) => rule.pageKind));
  if (kinds.size === 0) return NO_RULES;
  const [kind] = kinds;
  return kinds.size > 1 ? MIXED_RULES : (fieldsPageKindErrors(kind ?? null) ?? NO_ERRORS);
}

/** Why `form` can't be sent, by field. A crawl's results are records or page outputs: with a schema
 * or field names it asks for `records` alone, which needs a rule; every rule is for the schema's page kind, and field
 * names take rules of one page kind. Without either it asks for at least one format. */
export function crawlErrors(form: CrawlFormState): Readonly<Record<string, string>> {
  const formats = jobFormats(form);
  return withFetchErrors(
    withWebhookErrors(requestErrors(form), form.options.webhook),
    crawlFetch(form, formats),
    formats,
  );
}

function crawlFetch(form: CrawlFormState, formats: readonly ScrapeFormat[]): FetchMember {
  const { options } = form;
  return fetchMember(
    options.methodHint,
    options.maxRows,
    options.advanced,
    screenshotArea(formats, options),
  );
}

function requestErrors(form: CrawlFormState): Readonly<Record<string, string>> {
  const hasFields = form.options.fields.length > 0;
  if (form.schemaId !== "" && hasFields) return SCHEMA_AND_FIELDS;
  if (hasFields) return fieldsErrors(form.options.rules);
  if (form.schemaId === "") return asksForNothing(form) ? NO_FORMAT : NO_ERRORS;
  return (
    schemaPageKindErrors(form.schemaPageKind) ??
    (setRules(form.options.rules).length === 0 ? NO_RULES : NO_ERRORS)
  );
}

/** The crawl request for `form`, or null when it can't be sent (`crawlErrors`). With a schema, every rule is for its
 * page kind. */
export function buildCrawl(form: CrawlFormState): CrawlRequest | null {
  if (crawlErrors(form) !== NO_ERRORS) return null;
  const { options } = form;
  const schemaKind = form.schemaPageKind;
  const formats = jobFormats(form);
  return {
    url: form.url,
    formats,
    schema: requestSchema(form),
    page_kind_rules: setRules(options.rules).map(({ pattern, pageKind }) => ({
      pattern: pattern.trim(),
      page_kind: schemaKind ?? pageKind,
    })),
    include: [...options.include],
    exclude: [...options.exclude],
    fetch: crawlFetch(form, formats),
    ...formatMembers(formats, options),
    ...optionalNumber("max_depth", options.maxDepth),
    ...optionalNumber("limit", options.limit),
    ...minConfidence(options.minConfidence),
    ...crawlStrategy(options),
    ...(options.allowSubdomains ? { allow_subdomains: true } : {}),
    ...(options.allowExternal ? { allow_external: true } : {}),
    ...webhook(options.webhook),
  };
}

/** The request's `strategy` when it is not the default, and the `query` and `keywords` that order a best-first
 * crawl: on another strategy they are not sent, which the server refuses. */
function crawlStrategy(options: CrawlOptions): {
  strategy?: CrawlStrategy;
  query?: string;
  keywords?: string[];
} {
  if (options.strategy === "bfs") return {};
  if (options.strategy !== "best_first") return { strategy: options.strategy };
  const query = options.query.trim();
  return {
    strategy: options.strategy,
    ...(query === "" ? {} : { query }),
    ...(options.keywords.length === 0 ? {} : { keywords: [...options.keywords] }),
  };
}

/** The stored rules, as rows; a rule without a pattern or a page kind is not one the server took. */
function storedRules(request: StoredRequest): RuleRow[] {
  const rules = request["page_kind_rules"];
  if (!Array.isArray(rules)) return [];
  return rules.flatMap((rule: unknown, index) => {
    if (!isJsonObject(rule)) return [];
    const kind = pageKind(rule);
    const pattern = text(rule, "pattern");
    return kind === null || pattern === ""
      ? []
      : [{ key: `stored-${String(index)}`, pattern, pageKind: kind }];
  });
}

function strategyOf(request: StoredRequest): CrawlStrategy {
  const strategy = text(request, "strategy");
  return strategy === "dfs" || strategy === "best_first" ? strategy : "bfs";
}

/** The form that shows the stored `request` of a crawl job. A stored schema's page kind is its rules'. */
export function crawlForm(request: StoredRequest): CrawlFormState {
  const { formats, metadataInJson } = pageFormats(request);
  const id = schemaId(request);
  const rules = storedRules(request);
  return {
    url: text(request, "url"),
    formats,
    schemaId: id,
    schemaPageKind: id === "" ? null : (rules[0]?.pageKind ?? null),
    options: {
      include: texts(request, "include"),
      exclude: texts(request, "exclude"),
      rules,
      metadataInJson,
      fields: schemaFields(request),
      maxDepth: count(request, "max_depth"),
      limit: count(request, "limit"),
      strategy: strategyOf(request),
      query: text(request, "query"),
      keywords: texts(request, "keywords"),
      allowSubdomains: flag(request, "allow_subdomains", false),
      allowExternal: flag(request, "allow_external", false),
      methodHint: methodHint(request),
      maxRows: maxRows(request),
      minConfidence: minConfidencePercent(request),
      advanced: storedAdvanced(request),
      webhook: webhookSettings(request),
      ...storedFormatSettings(request),
    },
  };
}
