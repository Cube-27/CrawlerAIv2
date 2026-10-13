import type { ApiClient } from "../../api/client";
import { parseFieldTypes, type FieldTypeSpec } from "../../api/field";
import type { Problem } from "../../api/problem";
import { apiResult } from "../../api/result";
import type { components } from "../../api/schema";
import { getSchema } from "../../api/schemas";
import type { ScrapeRequest, ScrapeResponse } from "../../api/scrape";

type ScrapeRequestBody = components["schemas"]["ScrapeRequest"];

export type FieldTypes = Readonly<Record<string, FieldTypeSpec>>;

export type ScrapeRun =
  | { kind: "done"; response: ScrapeResponse; fieldTypes: FieldTypes }
  | { kind: "failed"; problem: Problem };

/** The stored schema's field types; empty when it can't be read, so the records still show. */
async function storedSchemaTypes(client: ApiClient, schemaId: string): Promise<FieldTypes> {
  const schema = await getSchema(client, schemaId);
  return schema.kind === "done" ? parseFieldTypes(schema.value.fields) : {};
}

/** The field types to show the records by: the schema the server drafted, the inline one sent, or the stored one.
 * Empty when the stored schema can't be read; the values are then shown as the server sent them. */
async function fieldTypes(
  client: ApiClient,
  request: ScrapeRequest,
  response: ScrapeResponse,
): Promise<FieldTypes> {
  if (response.schema !== undefined) return parseFieldTypes(response.schema.fields);
  if (response.records === undefined || request.schema === null) return {};
  if ("inline" in request.schema) return parseFieldTypes(request.schema.inline.fields);
  if ("id" in request.schema) return storedSchemaTypes(client, request.schema.id);
  return {};
}

/** Runs one `POST /v1/scrape`. A 401 drops the key through the client's middleware (`useApiClient`). */
export async function runScrape(client: ApiClient, request: ScrapeRequest): Promise<ScrapeRun> {
  const answer = await apiResult(
    () => client.POST("/v1/scrape", { body: request as ScrapeRequestBody }),
    "The scrape",
  );
  if (answer.kind === "failed") return answer;
  return {
    kind: "done",
    response: answer.value,
    fieldTypes: await fieldTypes(client, request, answer.value),
  };
}
