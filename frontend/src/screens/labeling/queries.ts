import type { LoaderFunctionArgs } from "react-router";
import { sameOriginClient } from "../../api/client";
import type { components } from "../../api/schema";

export type PageSummary = components["schemas"]["PageSummary"];
export type PageDetail = components["schemas"]["PageDetail"];

// The eval routes are mounted only with `CRAWLERAI_EVAL_UI=true` (SPEC-03 §4.10). Unmounted, a route is FastAPI's
// plain 404; a missing page is an RFC 9457 problem.
function isProblem(response: Response): boolean {
  return response.headers.get("content-type") === "application/problem+json";
}

export type ListData = { kind: "pages"; pages: PageSummary[] } | { kind: "off" };

export async function listLoader(): Promise<ListData> {
  const { data, response } = await sameOriginClient().GET("/v1/eval/pages");
  if (data !== undefined) return { kind: "pages", pages: data };
  if (response.status === 404) return { kind: "off" };
  throw new Error(`listing the eval pages failed: HTTP ${String(response.status)}`);
}

export type PageData =
  | { kind: "page"; page: PageDetail; etag: string | null }
  | { kind: "missing" }
  | { kind: "off" };

export async function pageLoader({ params }: LoaderFunctionArgs): Promise<PageData> {
  const pageId = params["pageId"] ?? "";
  const { data, response } = await sameOriginClient().GET("/v1/eval/pages/{page_id}", {
    params: { path: { page_id: pageId } },
  });
  if (data !== undefined) return { kind: "page", page: data, etag: response.headers.get("ETag") };
  if (response.status === 404) {
    return isProblem(response) ? { kind: "missing" } : { kind: "off" };
  }
  throw new Error(`loading eval page ${pageId} failed: HTTP ${String(response.status)}`);
}
