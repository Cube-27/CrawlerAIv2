import type { CrawlRequest } from "../../../api/jobs";
import { isJsonObject } from "../../../api/json";
import type { MethodHint, PageKind, ScrapeFormat } from "../../../api/scrape";
import type { SchemaPageKind } from "../../../api/schemas";
import type { PageFormat } from "../FormatSelect";
import {
  asksForNothing,
  fieldsPageKindErrors,
  hasSchema,
  fetchMember,
  NO_ERRORS,
  NO_FORMAT,
  optionalNumber,
  requestFormats,
  requestSchema,
  SCHEMA_AND_FIELDS,
  schemaPageKindErrors,
  webhook,
} from "../pageRequest";
import {
  count,
  maxRows,
  methodHint,
  pageFormats,
  pageKind,
  schemaFields,
  schemaId,
  text,
  texts,
  webhookUrl,
  type StoredRequest,
} from "../run/storedRequest";

/** One page-kind rule as edited: `key` keeps a row's inputs when another row is removed. */
export interface RuleRow {
  key: string;
  pattern: string;
  pageKind: PageKind;
}

/** Crawl's options panel (SPEC-14 §4.2): each is a `CrawlRequest` member, except `metadataInJson`, a view option.
 * `fields` are the names `schema.fields` drafts a schema from (§4.10). An empty limit (NaN) is left out, so the
 * server's default applies. */
export interface CrawlOptions {
  include: readonly string[];
  exclude: readonly string[];
  rules: readonly RuleRow[];
  metadataInJson: boolean;
  fields: readonly string[];
  maxDepth: number;
  limit: number;
  methodHint: MethodHint;
  /** `fetch.max_rows`: NaN while empty. */
  maxRows: number;
  /** Empty: no webhook. */
  webhookUrl: string;
}

export const DEFAULT_CRAWL_OPTIONS: CrawlOptions = {
  include: [],
  exclude: [],
  rules: [],
  metadataInJson: false,
  fields: [],
  maxDepth: Number.NaN,
  limit: Number.NaN,
  // FetchPolicy's own default (SPEC-02 §4.2).
  methodHint: "auto",
  maxRows: Number.NaN,
  webhookUrl: "",
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

/** Why `form` can't be sent, by field. A crawl's results are records or page outputs (SPEC-10 §4.5): with a schema
 * or field names it asks for `records` alone, which needs a rule; every rule is for the schema's page kind, and field
 * names take rules of one page kind. Without either it asks for at least one format. */
export function crawlErrors(form: CrawlFormState): Readonly<Record<string, string>> {
  const hasFields = form.options.fields.length > 0;
  if (form.schemaId !== "" && hasFields) return SCHEMA_AND_FIELDS;
  if (hasFields) return fieldsErrors(form.options.rules);
  if (form.schemaId === "") return asksForNothing(form) ? NO_FORMAT : NO_ERRORS;
  return (
    schemaPageKindErrors(form.schemaPageKind) ??
    (setRules(form.options.rules).length === 0 ? NO_RULES : NO_ERRORS)
  );
}

/** The crawl's formats: `records` alone with a schema or field names (SPEC-10 §4.5), else the page formats and
 * `metadata`. Metadata in JSON still asks the results for each page's metadata, which they read from its capture. */
function crawlFormats(form: CrawlFormState): ScrapeFormat[] {
  return hasSchema(form) ? ["records"] : requestFormats(form);
}

/** The crawl request for `form`, or null when it can't be sent (`crawlErrors`). With a schema, every rule is for its
 * page kind. */
export function buildCrawl(form: CrawlFormState): CrawlRequest | null {
  if (crawlErrors(form) !== NO_ERRORS) return null;
  const { options } = form;
  const schemaKind = form.schemaPageKind;
  return {
    url: form.url,
    formats: crawlFormats(form),
    schema: requestSchema(form),
    page_kind_rules: setRules(options.rules).map(({ pattern, pageKind }) => ({
      pattern: pattern.trim(),
      page_kind: schemaKind ?? pageKind,
    })),
    include: [...options.include],
    exclude: [...options.exclude],
    fetch: fetchMember(options.methodHint, options.maxRows),
    ...optionalNumber("max_depth", options.maxDepth),
    ...optionalNumber("limit", options.limit),
    ...webhook(options.webhookUrl),
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
      methodHint: methodHint(request),
      maxRows: maxRows(request),
      webhookUrl: webhookUrl(request),
    },
  };
}
