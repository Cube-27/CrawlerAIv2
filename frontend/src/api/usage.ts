/** `GET /v1/usage/llm` (SPEC-10 §4.2): the LLM cost history, an estimate for visibility, not billing. */
import type { ApiClient } from "./client";
import { apiResult, type ApiResult } from "./result";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type CostReport = Schemas["CostReport"];
/** Calls and tokens with their estimated cost in USD: null when some tokens have no price. */
export type LlmUsage = Schemas["LLMUsage"];
export type DayUsage = Schemas["DayUsage"];
export type ModelRoleUsage = Schemas["ModelRoleUsage"];
export type JobUsage = Schemas["JobUsage"];

/** The report for the UTC days from `start` (an ISO 8601 date) through today. */
export function getLlmCostReport(client: ApiClient, start: string): Promise<ApiResult<CostReport>> {
  return apiResult(
    () => client.GET("/v1/usage/llm", { params: { query: { start } } }),
    "Loading the LLM cost history",
  );
}
