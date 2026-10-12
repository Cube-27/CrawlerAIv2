import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "./client";

function stubFetch(body: unknown) {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>(() =>
    Promise.resolve(Response.json(body)),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("createApiClient", () => {
  it("calls the base URL with the API key as a bearer header and returns the typed body", async () => {
    const fetchMock = stubFetch({ status: "ok" });
    const client = createApiClient({
      baseUrl: "http://api.test",
      apiKey: "ck_test",
    });

    const { data } = await client.GET("/healthz");

    expect(data).toEqual({ status: "ok" });
    const request = fetchMock.mock.calls[0]?.[0];
    expect(request?.url).toBe("http://api.test/healthz");
    expect(request?.headers.get("Authorization")).toBe("Bearer ck_test");
  });

  it("sends no Authorization header when no API key is held", async () => {
    const fetchMock = stubFetch({ status: "ok" });
    const client = createApiClient({ baseUrl: "http://api.test" });

    await client.GET("/healthz");

    const request = fetchMock.mock.calls[0]?.[0];
    expect(request?.url).toBe("http://api.test/healthz");
    expect(request?.headers.has("Authorization")).toBe(false);
  });
});
