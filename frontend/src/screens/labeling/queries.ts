import { useQuery } from "@tanstack/react-query";
import type { ApiClient } from "../../api/client";
import { ApiProblem } from "../../api/hooks/query";
import { failed } from "../../api/result";
import type { components } from "../../api/schema";
import { useApiClient } from "../../app/auth";

export type PageSummary = components["schemas"]["PageSummary"];
export type PageDetail = components["schemas"]["PageDetail"];

/** Every labeling query key starts with this, so a saved pass reads its page and the list again. */
export const EVAL_PAGES = ["eval", "pages"] as const;

// The eval routes are mounted only with `CRAWLERAI_EVAL_UI=true` (SPEC-03 §4.10). Unmounted, a route is FastAPI's
// plain 404; a missing page is an RFC 9457 problem.
function isProblem(response: Response): boolean {
  return response.headers.get("content-type") === "application/problem+json";
}

export type ListData = { kind: "pages"; pages: PageSummary[] } | { kind: "off" };

async function listPages(client: ApiClient): Promise<ListData> {
  const { data, error, response } = await client.GET("/v1/eval/pages");
  if (data !== undefined) return { kind: "pages", pages: data };
  if (response.status === 404) return { kind: "off" };
  throw new ApiProblem(failed(response, error, "Listing the eval pages").problem);
}

export type PageData =
  | { kind: "page"; page: PageDetail; etag: string | null }
  | { kind: "missing" }
  | { kind: "off" };

async function getPage(client: ApiClient, pageId: string): Promise<PageData> {
  const { data, error, response } = await client.GET("/v1/eval/pages/{page_id}", {
    params: { path: { page_id: pageId } },
  });
  if (data !== undefined) return { kind: "page", page: data, etag: response.headers.get("ETag") };
  if (response.status === 404) {
    return isProblem(response) ? { kind: "missing" } : { kind: "off" };
  }
  throw new ApiProblem(failed(response, error, "Loading the eval page").problem);
}

/** The dev eval pages, read with the connected API key (SPEC-03 §4.10: the same auth as everything else). */
export function useEvalPages() {
  const client = useApiClient();
  return useQuery({ queryKey: EVAL_PAGES, queryFn: () => listPages(client) });
}

export function useEvalPage(pageId: string) {
  const client = useApiClient();
  return useQuery({ queryKey: [...EVAL_PAGES, pageId], queryFn: () => getPage(client, pageId) });
}
