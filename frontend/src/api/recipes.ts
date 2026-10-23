import type { CallList } from "./captures";
import type { ApiClient } from "./client";
import type { ConfigDetail } from "./configs";
import { LIMITS } from "./limits";
import { apiResult, type ApiResult } from "./result";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** A custom recipe as it is saved and edited (`POST /v1/sites/{host}/configs`, `PUT /v1/configs/{id}/recipe`). */
export type CustomRecipe = Schemas["CustomRecipe-Input"];
/** A recipe as the server writes it (a proposal, a stored recipe); it is read back as written. */
export type WrittenRecipe = Schemas["CustomRecipe-Output"];
/** One call of a recipe: its request, its answer's kind and its field map. */
export type RecipeCall = Schemas["ApiRecipe-Input"];
export type PageField = Schemas["PageField-Input"];
export type RecipeHeader = NonNullable<RecipeCall["headers"]>[number];
export type Pagination = NonNullable<RecipeCall["pagination"]>;
/** The draft `POST /v1/recipes/propose` makes of the samples' calls of one endpoint. */
export type Proposal = Schemas["Proposal"];
export type EndpointRef = Schemas["EndpointRef"];
/** What a draft is made of: the sample captures, the endpoint whose calls make the request, and the schema. */
export interface ProposeBody {
  capture_ids: string[];
  main: EndpointRef;
  schema_id: string;
}
export type RecipeTestResult = Schemas["RecipeTestResult"];
export type UrlTest = Schemas["UrlTest"];
export type TestRun = Schemas["Run"];

/** The most sample pages a recipe's call list merges (`POST /v1/recipes/calls`). */
export const MAX_SAMPLES = LIMITS.CallsRequest.capture_ids.maxItems;
/** The most URLs one test tries (`POST /v1/recipes/test`). */
export const MAX_TEST_URLS = LIMITS.RecipeTestRequest.urls.maxItems;

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

/** A recipe's draft from the samples' calls of the `main` endpoint, for the schema; nothing is sent or stored. */
export function proposeRecipe(client: ApiClient, body: ProposeBody): Promise<ApiResult<Proposal>> {
  return apiResult(() => client.POST("/v1/recipes/propose", { body }), "Drafting the recipe");
}

/** The recipe tried on URLs of its patterns, beside the normal extraction; nothing is stored. */
export function testRecipe(
  client: ApiClient,
  body: { recipe: CustomRecipe; urls: string[] },
): Promise<ApiResult<RecipeTestResult>> {
  return apiResult(() => client.POST("/v1/recipes/test", { body }), "Testing the recipe");
}

/** Saves a new recipe for the site, or, with `replaces`, the next version of that active recipe. */
export function saveRecipe(
  client: ApiClient,
  host: string,
  recipe: CustomRecipe,
  replaces: string | null,
): Promise<ApiResult<ConfigDetail>> {
  return replaces === null
    ? apiResult(
        () => client.POST("/v1/sites/{host}/configs", { params: { path: { host } }, body: recipe }),
        "Saving the recipe",
      )
    : apiResult(
        () =>
          client.PUT("/v1/configs/{config_id}/recipe", {
            params: { path: { config_id: replaces } },
            body: recipe,
          }),
        "Saving the recipe",
      );
}
