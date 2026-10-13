import type { ApiClient } from "../../api/client";
import { parseFieldTypes, type FieldTypeSpec } from "../../api/field";
import { problemOf, type Problem } from "../../api/problem";
import type { components } from "../../api/schema";
import type { ScrapeRequest, ScrapeResponse } from "../../api/scrape";

type ScrapeRequestBody = components["schemas"]["ScrapeRequest"];

export type FieldTypes = Readonly<Record<string, FieldTypeSpec>>;

export type ScrapeRun =
  | { kind: "done"; response: ScrapeResponse; fieldTypes: FieldTypes }
  | { kind: "failed"; problem: Problem };

function failed(title: string, detail: string | null, retryAfter: string | null = null): ScrapeRun {
  return { kind: "failed", problem: { title, detail, errors: [], retryAfter } };
}

/** The stored schema's field types; empty when it can't be read, so the records still show. */
async function storedSchemaTypes(client: ApiClient, schemaId: string): Promise<FieldTypes> {
  try {
    const { data } = await client.GET("/v1/schemas/{schema_id}", {
      params: { path: { schema_id: schemaId } },
    });
    return parseFieldTypes(data?.fields);
  } catch {
    return {};
  }
}

/** The field types to show the records by: the schema the server drafted, the inline one sent, or the stored one.
 * Empty when the stored schema can't be read; the values are then shown as the server sent them. */
async function fieldTypes(
  client: ApiClient,
  request: ScrapeRequest,
  response: ScrapeResponse,
): Promise<FieldTypes> {
  if (response.schema !== undefined) return response.schema.fields;
  if (response.records === undefined || request.schema === null) return {};
  if ("inline" in request.schema) return parseFieldTypes(request.schema.inline.fields);
  if ("id" in request.schema) return storedSchemaTypes(client, request.schema.id);
  return {};
}

/** Runs one `POST /v1/scrape`. A 401 drops the key through the client's middleware (`useApiClient`). */
export async function runScrape(client: ApiClient, request: ScrapeRequest): Promise<ScrapeRun> {
  let answer;
  try {
    answer = await client.POST("/v1/scrape", { body: request as ScrapeRequestBody });
  } catch (thrown) {
    return failed("The API could not be reached.", thrown instanceof Error ? thrown.message : null);
  }
  const { data, error, response } = answer;
  if (data !== undefined) {
    return { kind: "done", response: data, fieldTypes: await fieldTypes(client, request, data) };
  }
  const problem = problemOf(response, error);
  return problem === null
    ? failed(
        `The scrape failed (HTTP ${String(response.status)}).`,
        null,
        response.headers.get("Retry-After"),
      )
    : { kind: "failed", problem };
}
