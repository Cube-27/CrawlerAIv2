import { isJsonObject } from "../../../api/json";
import type { MethodHint, PageKind } from "../../../api/scrape";
import { orderedFormats } from "../../../components/formats";
import { METHOD_HINTS, PAGE_KINDS } from "../../../components/requestOptions";
import type { PageFormat } from "../FormatSelect";

/** Members picked out of a job's stored request (`GET /v1/jobs/{id}/request`, the request as the server validated it), to
 * show it again in a mode's bar and options (SPEC-14 §4.8). The UI reads only what its forms hold; a member that is
 * missing or not of its type reads as the form's empty value. */
export type StoredRequest = Readonly<Record<string, unknown>>;

export function text(request: StoredRequest, key: string): string {
  const value = request[key];
  return typeof value === "string" ? value : "";
}

export function texts(request: StoredRequest, key: string): string[] {
  const value = request[key];
  return Array.isArray(value) ? value.filter((entry) => typeof entry === "string") : [];
}

/** A number member; NaN (an empty limit) when absent. */
export function count(request: StoredRequest, key: string): number {
  const value = request[key];
  return typeof value === "number" ? value : Number.NaN;
}

export function flag(request: StoredRequest, key: string, empty: boolean): boolean {
  const value = request[key];
  return typeof value === "boolean" ? value : empty;
}

export function member(request: StoredRequest, key: string): StoredRequest {
  const value = request[key];
  return isJsonObject(value) ? value : {};
}

export function pageKind(request: StoredRequest): PageKind | null {
  return PAGE_KINDS.find(([kind]) => kind === request["page_kind"])?.[0] ?? null;
}

/** `fetch.method_hint`, else FetchPolicy's own default (SPEC-02 §4.2). */
export function methodHint(request: StoredRequest): MethodHint {
  const hint = member(request, "fetch")["method_hint"];
  return METHOD_HINTS.find(([option]) => option === hint)?.[0] ?? "auto";
}

/** `budget.llm_calls`; NaN when absent. */
export function llmCalls(request: StoredRequest): number {
  return count(member(request, "budget"), "llm_calls");
}

/** The stored schema's id, or "" when the request names none by id. */
export function schemaId(request: StoredRequest): string {
  return text(member(request, "schema"), "id");
}

/** The page formats asked for, and whether `metadata` was, shown as Metadata in JSON: the request is the same either
 * way. `records` comes from the schema, not the Format select. */
export function pageFormats(request: StoredRequest): {
  formats: PageFormat[];
  metadataInJson: boolean;
} {
  const asked = orderedFormats(texts(request, "formats"));
  return {
    formats: asked.filter(
      (format): format is PageFormat => format !== "records" && format !== "metadata",
    ),
    metadataInJson: asked.includes("metadata"),
  };
}

/** `webhook_url`, or "" for none. */
export function webhookUrl(request: StoredRequest): string {
  return text(request, "webhook_url");
}
