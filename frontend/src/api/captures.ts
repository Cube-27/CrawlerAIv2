import type { ApiClient } from "./client";
import { apiResult, type ApiResult } from "./result";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** `POST /v1/captures`: an engineer capture of a sample page, in the generated shapes. */
export type CaptureRequest = Schemas["CaptureRequest"];
export type CaptureResult = Schemas["CaptureResult"];
/** A capture's calls by endpoint, each with where it carries the schema's fields. */
export type CallList = Schemas["CallList"];
export type Endpoint = Schemas["Endpoint"];
export type FieldMatch = Schemas["FieldMatch"];
export type CallSummary = Schemas["CallSummary"];
/** Header field lines as `[name, value]`; openapi-fetch reads the generated pair (a JSON Schema `prefixItems` tuple) as
 * a plain array. */
export type HeaderLines = string[][];
/** One call as sent and answered: headers, body and the answer's text. */
export type CallDetail = Omit<Schemas["CallDetail"], "request_headers" | "response_headers"> & {
  request_headers: HeaderLines | null;
  response_headers: HeaderLines | null;
};

/** Renders the sample page in the browser after its page steps and stores it with its records. */
export function captureSample(
  client: ApiClient,
  body: CaptureRequest,
): Promise<ApiResult<CaptureResult>> {
  return apiResult(() => client.POST("/v1/captures", { body }), "Capturing the page");
}

/** One capture's calls by endpoint. */
export function captureCalls(client: ApiClient, captureId: string): Promise<ApiResult<CallList>> {
  return apiResult(
    () =>
      client.GET("/v1/captures/{capture_id}/calls", {
        params: { path: { capture_id: captureId } },
      }),
    "Listing the page's calls",
  );
}

export function getCall(
  client: ApiClient,
  captureId: string,
  index: number,
): Promise<ApiResult<CallDetail>> {
  return apiResult(
    () =>
      client.GET("/v1/captures/{capture_id}/calls/{index}", {
        params: { path: { capture_id: captureId, index } },
      }),
    "Loading the call",
  );
}

/** The capture as an HTTP Archive (HAR 1.2), a JSON document. */
export function getHar(client: ApiClient, captureId: string): Promise<ApiResult<unknown>> {
  return apiResult(
    () =>
      client.GET("/v1/captures/{capture_id}/calls.har", {
        params: { path: { capture_id: captureId } },
      }),
    "Exporting the HAR",
  );
}
