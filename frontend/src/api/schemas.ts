import type { ApiClient } from "./client";
import { apiDone, apiResult, type ApiResult } from "./result";
import type { components } from "./schema";

/** `/v1/schemas` (SPEC-07 §4.6), in the generated shapes. */
export type SchemaDef = components["schemas"]["SchemaDef"];
export type NewSchema = components["schemas"]["NewSchema"];
export type SchemaContent = components["schemas"]["SchemaContent"];
export type FieldSpecInput = components["schemas"]["FieldSpec-Input"];
export type FieldType = components["schemas"]["FieldType"];
export type SchemaPageKind = SchemaDef["page_kind"];

/** A schema version as people name it: "<name> version <n>". */
export function schemaVersionLabel({ name, version }: Pick<SchemaDef, "name" | "version">): string {
  return `${name} version ${String(version)}`;
}

/** Every version of every schema; with `name`, every version of that one. */
export async function listSchemas(
  client: ApiClient,
  name?: string,
): Promise<ApiResult<SchemaDef[]>> {
  const result = await apiResult(
    () => client.GET("/v1/schemas", { params: { query: name === undefined ? {} : { name } } }),
    "Listing the schemas",
  );
  return result.kind === "done" ? { kind: "done", value: result.value.items } : result;
}

export function getSchema(client: ApiClient, id: string): Promise<ApiResult<SchemaDef>> {
  return apiResult(
    () => client.GET("/v1/schemas/{schema_id}", { params: { path: { schema_id: id } } }),
    "Loading the schema",
  );
}

/** Creates a `user` schema at version 1. */
export function createSchema(client: ApiClient, body: NewSchema): Promise<ApiResult<SchemaDef>> {
  return apiResult(() => client.POST("/v1/schemas", { body }), "Creating the schema");
}

/** Adds the version after `id`, with `body` as its whole document. */
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

/** Retires the version `id`; the row stays. */
export function retireSchema(client: ApiClient, id: string): Promise<ApiResult<null>> {
  return apiDone(
    () => client.DELETE("/v1/schemas/{schema_id}", { params: { path: { schema_id: id } } }),
    "Retiring the schema",
  );
}
