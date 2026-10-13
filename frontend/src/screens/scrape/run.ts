import type { ApiClient } from "../../api/client";
import { parseFieldTypes, type FieldTypeSpec } from "../../api/field";
import { isProblemJson, parseProblem, type Problem } from "../../api/problem";
import type { ScrapeRequest, ScrapeResponse } from "../../api/scrape";

export type FieldTypes = Readonly<Record<string, FieldTypeSpec>>;

export type ScrapeRun =
  | { kind: "done"; response: ScrapeResponse; fieldTypes: FieldTypes }
  | { kind: "failed"; problem: Problem; retryAfter: string | null };

function failure(response: Response, body: unknown): ScrapeRun {
  const problem = isProblemJson(response) ? parseProblem(body) : null;
  return {
    kind: "failed",
    problem: problem ?? {
      title: `The scrape failed (HTTP ${String(response.status)}).`,
      detail: null,
      errors: [],
    },
    // RFC 9110 §10.2.3: sent with 429 (SPEC-07 §4.2), as seconds or an HTTP date; shown as sent.
    retryAfter: response.headers.get("Retry-After"),
  };
}

async function storedSchemaTypes(client: ApiClient, schemaId: string): Promise<FieldTypes> {
  const { data } = await client.GET("/v1/schemas/{schema_id}", {
    params: { path: { schema_id: schemaId } },
  });
  return data?.fields ?? {};
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
  try {
    const { data, error, response } = await client.POST("/v1/scrape", { body: request });
    if (data === undefined) return failure(response, error);
    return { kind: "done", response: data, fieldTypes: await fieldTypes(client, request, data) };
  } catch (thrown) {
    return {
      kind: "failed",
      problem: {
        title: "The API could not be reached.",
        detail: thrown instanceof Error ? thrown.message : null,
        errors: [],
      },
      retryAfter: null,
    };
  }
}
