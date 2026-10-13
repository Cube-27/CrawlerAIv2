import type { ApiClient } from "./client";
import { apiResult, type ApiResult } from "./result";
import type { components } from "./schema";

/** `GET /healthz` (D-0365): the API is up, and whether it serves the labeling API (`eval_ui`). Takes no key. */
export type Health = components["schemas"]["Health"];

export function getHealth(client: ApiClient): Promise<ApiResult<Health>> {
  return apiResult(() => client.GET("/healthz"), "Checking the API");
}
