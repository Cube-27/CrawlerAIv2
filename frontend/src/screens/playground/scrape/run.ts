import type { ApiClient } from "../../../api/client";
import { parseFieldTypes, type FieldTypes } from "../../../api/field";
import type { Problem } from "../../../api/problem";
import { apiResult } from "../../../api/result";
import type { components } from "../../../api/schema";
import { getSchema } from "../../../api/schemas";
import type { ScrapeRequest, ScrapeResponse } from "../../../api/scrape";

type ScrapeRequestBody = components["schemas"]["ScrapeRequest"];

export type ScrapeRun =
  | { kind: "done"; response: ScrapeResponse; fieldTypes: FieldTypes }
  | { kind: "failed"; problem: Problem };

/** The field types to show the records by: the stored schema's, the only kind Scrape sends (D-0818). Empty when there
 * are no records or the schema can't be read; the values are then shown as the server sent them. */
async function fieldTypes(
  client: ApiClient,
  request: ScrapeRequest,
  response: ScrapeResponse,
): Promise<FieldTypes> {
  if (response.records === undefined || request.schema === null || !("id" in request.schema)) {
    return {};
  }
  const schema = await getSchema(client, request.schema.id);
  return schema.kind === "done" ? parseFieldTypes(schema.value.fields) : {};
}

/** Runs one `POST /v1/scrape`. */
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
