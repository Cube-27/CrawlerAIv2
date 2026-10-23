import type { CallList } from "./captures";
import type { ApiClient } from "./client";
import { LIMITS } from "./limits";
import { apiResult, type ApiResult } from "./result";

/** The most sample pages a recipe's call list merges (`POST /v1/recipes/calls`). */
export const MAX_SAMPLES = LIMITS.CallsRequest.capture_ids.maxItems;

/** The calls of two to five sample captures, merged by endpoint. */
export function recipeCalls(
  client: ApiClient,
  captureIds: readonly string[],
): Promise<ApiResult<CallList>> {
  return apiResult(
    () => client.POST("/v1/recipes/calls", { body: { capture_ids: [...captureIds] } }),
    "Listing the samples' calls",
  );
}
