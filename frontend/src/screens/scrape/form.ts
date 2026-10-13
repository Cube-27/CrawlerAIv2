import type {
  MethodHint,
  PageKind,
  SchemaRef,
  ScrapeFormat,
  ScrapeRequest,
} from "../../api/scrape";

/** The formats in the order SPEC-07 §4.4 lists them; a request sends the chosen ones in this order. */
export const FORMATS: readonly (readonly [ScrapeFormat, string])[] = [
  ["markdown", "Markdown"],
  ["html", "HTML"],
  ["raw_html", "Raw HTML"],
  ["links", "Links"],
  ["metadata", "Metadata"],
  ["records", "Records"],
];

export type SchemaSource = "none" | "id" | "inline" | "prompt";

export interface ScrapeFormState {
  url: string;
  formats: readonly ScrapeFormat[];
  schemaSource: SchemaSource;
  schemaId: string;
  schemaJson: string;
  schemaPrompt: string;
  pageKind: PageKind | null;
  methodHint: MethodHint;
  /** NaN while empty: the request then leaves the limit to the server. */
  maxAge: number;
  timeoutS: number;
  llmCalls: number;
}

export const INITIAL_FORM: ScrapeFormState = {
  url: "",
  formats: ["markdown"],
  schemaSource: "none",
  schemaId: "",
  schemaJson: "",
  schemaPrompt: "",
  pageKind: null,
  // FetchPolicy's own default (SPEC-02 §4.2).
  methodHint: "auto",
  maxAge: Number.NaN,
  timeoutS: Number.NaN,
  llmCalls: Number.NaN,
};

/** The JSON object in `text`, or null when it is not one. The server validates it as a SchemaDef. */
export function parseJsonObject(text: string): Readonly<Record<string, unknown>> | null {
  try {
    const value: unknown = JSON.parse(text);
    if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
    return Object.fromEntries(Object.entries(value));
  } catch {
    return null;
  }
}

type SchemaChoice = { kind: "ok"; schema: SchemaRef | null } | { kind: "invalid" };

function schemaChoice(form: ScrapeFormState): SchemaChoice {
  switch (form.schemaSource) {
    case "none":
      return { kind: "ok", schema: null };
    case "id":
      return { kind: "ok", schema: { id: form.schemaId.trim() } };
    case "prompt":
      return { kind: "ok", schema: { prompt: form.schemaPrompt } };
    case "inline": {
      const inline = parseJsonObject(form.schemaJson);
      return inline === null ? { kind: "invalid" } : { kind: "ok", schema: { inline } };
    }
    default: {
      const exhaustive: never = form.schemaSource;
      return exhaustive;
    }
  }
}

/** The request for `form`, or null when its inline schema is not a JSON object (the form shows why). Empty limits are
 * left out, so the server's defaults apply. */
export function buildRequest(form: ScrapeFormState): ScrapeRequest | null {
  const choice = schemaChoice(form);
  if (choice.kind === "invalid") return null;
  return {
    url: form.url.trim(),
    formats: FORMATS.map(([format]) => format).filter((format) => form.formats.includes(format)),
    schema: choice.schema,
    page_kind: form.pageKind,
    fetch: { method_hint: form.methodHint },
    ...(Number.isNaN(form.maxAge) ? {} : { max_age: form.maxAge }),
    ...(Number.isNaN(form.timeoutS) ? {} : { timeout_s: form.timeoutS }),
    ...(Number.isNaN(form.llmCalls) ? {} : { budget: { llm_calls: form.llmCalls } }),
  };
}
