/** `GET`/`PATCH /v1/project/settings`: the project's settings, such as its LLM call cap (null: no cap). */
import type { ApiClient } from "./client";
import { apiResult, type ApiResult } from "./result";
import type { components } from "./schema";

export type ProjectSettings = components["schemas"]["ProjectSettings"];

export function getProjectSettings(client: ApiClient): Promise<ApiResult<ProjectSettings>> {
  return apiResult(() => client.GET("/v1/project/settings"), "Loading the project settings");
}

export function saveProjectSettings(
  client: ApiClient,
  body: ProjectSettings,
): Promise<ApiResult<ProjectSettings>> {
  return apiResult(
    () => client.PATCH("/v1/project/settings", { body }),
    "Saving the project settings",
  );
}
