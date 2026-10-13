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
    });
  });

  it("accepts media type parameters and a body without detail", async () => {
    const response = problemResponse(
      { type: "unauthorized", title: "Unauthorized", status: 401 },
      "application/problem+json; charset=utf-8",
    );

    expect(await readProblem(response)).toEqual({ title: "Unauthorized", detail: null });
  });

  it("returns null for a body that is not a problem", async () => {
    expect(await readProblem(problemResponse({ detail: "x" }, "application/json"))).toBeNull();
    expect(await readProblem(problemResponse({ detail: "no title" }))).toBeNull();
    expect(await readProblem(new Response("not json", { status: 401 }))).toBeNull();
  });
});
