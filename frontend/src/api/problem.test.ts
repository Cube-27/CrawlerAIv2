import { describe, expect, it } from "vite-plus/test";
import { readProblem } from "./problem";

function problemResponse(body: unknown, contentType = "application/problem+json"): Response {
  return new Response(JSON.stringify(body), {
    status: 401,
    headers: { "content-type": contentType },
  });
}

describe("readProblem", () => {
  it("reads title and detail from an RFC 9457 body", async () => {
    const response = problemResponse({
      type: "unauthorized",
      title: "Unauthorized",
      status: 401,
      detail: "The API key is revoked.",
    });

    expect(await readProblem(response)).toEqual({
      title: "Unauthorized",
      detail: "The API key is revoked.",
      errors: [],
      retryAfter: null,
    });
  });

  it("reads the per-field errors and skips malformed entries", async () => {
    const response = problemResponse({
      type: "validation",
      title: "Invalid request",
      status: 422,
      errors: [{ field: "url", reason: "not an absolute URL" }, { field: 3 }, "page_kind"],
    });

    expect(await readProblem(response)).toEqual({
      title: "Invalid request",
      detail: null,
      errors: [{ field: "url", reason: "not an absolute URL" }],
      retryAfter: null,
    });
  });

  it("returns null for a body that is not a problem", async () => {
    expect(await readProblem(problemResponse({ detail: "x" }, "application/json"))).toBeNull();
    expect(await readProblem(problemResponse({ detail: "no title" }))).toBeNull();
    expect(await readProblem(new Response("not json", { status: 401 }))).toBeNull();
  });
});
