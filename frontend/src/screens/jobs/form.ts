import type { ExtractRequest } from "../../api/jobs";
import type { MethodHint, PageKind, SchemaRef } from "../../api/scrape";
import { parseJsonObject } from "../../api/json";
import { lines, webhook } from "../playground/pageRequest";

/** The job forms' state and the requests they send (SPEC-10 §4.3–4.6). The server validates every request; a form
 * checks only what it must hold to be sent. An empty limit (NaN) or text is left out, so the server's default
 * applies. */

/** Where a job's schema comes from: none, a stored one, inline JSON, or a draft from a prompt. */
export type SchemaSource = "none" | "id" | "inline" | "prompt";

/** A job's schema as edited. A batch or crawl offers none, a stored one or inline JSON; an extract needs one, and may
 * have it drafted from a prompt. */
export interface JobSchemaState {
  source: SchemaSource;
  id: string;
  json: string;
  prompt: string;
}

export interface ExtractFormState {
  /** One URL or URL glob per line. */
  urls: string;
  schema: JobSchemaState;
  pageKind: PageKind | null;
  limit: number;
  llmCalls: number;
  methodHint: MethodHint;
  webhookUrl: string;
}

const NO_SCHEMA: JobSchemaState = { source: "none", id: "", json: "", prompt: "" };

export const INITIAL_EXTRACT: ExtractFormState = {
  urls: "",
  schema: { ...NO_SCHEMA, source: "id" },
  pageKind: null,
  limit: Number.NaN,
  llmCalls: Number.NaN,
  methodHint: "auto",
  webhookUrl: "",
};

type SchemaChoice<T> = { kind: "ok"; schema: T } | { kind: "invalid" };

/** The schema of `state`; invalid for inline text that is not a JSON object. */
function schemaChoice({
  source,
  id,
  json,
  prompt,
}: JobSchemaState): SchemaChoice<SchemaRef | null> {
  switch (source) {
    case "none":
      return { kind: "ok", schema: null };
    case "id":
      return { kind: "ok", schema: { id } };
    case "prompt":
      return { kind: "ok", schema: { prompt } };
    case "inline": {
      const inline = parseJsonObject(json);
      return inline === null ? { kind: "invalid" } : { kind: "ok", schema: { inline } };
    }
    default: {
      const exhaustive: never = source;
      return exhaustive;
    }
  }
}

/** The extract request for `form`, or null when it has no schema, or an inline schema that is not a JSON object. */
export function buildExtract(form: ExtractFormState): ExtractRequest | null {
  const choice = schemaChoice(form.schema);
  if (choice.kind === "invalid" || choice.schema === null || form.pageKind === null) return null;
  return {
    urls: lines(form.urls),
    schema: choice.schema,
    page_kind: form.pageKind,
    fetch: { method_hint: form.methodHint },
    ...(Number.isNaN(form.limit) ? {} : { limit: form.limit }),
    ...(Number.isNaN(form.llmCalls) ? {} : { budget: { llm_calls: form.llmCalls } }),
    ...webhook(form.webhookUrl),
  };
}
