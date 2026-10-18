import type { ApiClient } from "./client";
import { apiDone, apiResult, type ApiResult } from "./result";
import type { components } from "./schema";

/** `/v1/schemas` (rest-api spec), in the generated shapes. */
export type SchemaDef = components["schemas"]["SchemaDef"];
export type NewSchema = components["schemas"]["NewSchema"];
export type SchemaContent = components["schemas"]["SchemaContent"];
export type FieldSpecInput = components["schemas"]["FieldSpec-Input"];
export type FieldType = components["schemas"]["FieldType"];
export type FieldsDraft = components["schemas"]["FieldsDraft"];
export type SchemaPageKind = SchemaDef["page_kind"];

/** Every schema, one per name. */
export async function listSchemas(client: ApiClient): Promise<ApiResult<SchemaDef[]>> {
  const result = await apiResult(() => client.GET("/v1/schemas"), "Listing the schemas");
  return result.kind === "done" ? { kind: "done", value: result.value.items } : result;
}

export function getSchema(client: ApiClient, id: string): Promise<ApiResult<SchemaDef>> {
  return apiResult(
    () => client.GET("/v1/schemas/{schema_id}", { params: { path: { schema_id: id } } }),
    "Loading the schema",
  );
}

/** Creates a `user` schema. */
export function createSchema(client: ApiClient, body: NewSchema): Promise<ApiResult<SchemaDef>> {
  return apiResult(() => client.POST("/v1/schemas", { body }), "Creating the schema");
}

/** Replaces the document of schema `id` with `body`, in place; its site configs go back to learning. */
export function updateSchema(
  client: ApiClient,
  id: string,
  body: SchemaContent,
): Promise<ApiResult<SchemaDef>> {
  return apiResult(
    () => client.PUT("/v1/schemas/{schema_id}", { params: { path: { schema_id: id } }, body }),
    "Saving the schema",
  );
}

/** The schema role S drafts from field names for one page kind (frontend spec): the stored draft when these names were
 * drafted before, else a new one, stored. */
export function draftSchema(client: ApiClient, body: FieldsDraft): Promise<ApiResult<SchemaDef>> {
  return apiResult(() => client.POST("/v1/schemas/draft", { body }), "Drafting the schema");
}

/** Retires the schema `id`; the row stays. */
export function retireSchema(client: ApiClient, id: string): Promise<ApiResult<null>> {
  return apiDone(
    () => client.DELETE("/v1/schemas/{schema_id}", { params: { path: { schema_id: id } } }),
    "Retiring the schema",
  );
}
