import { describe, expect, it, vi } from "vite-plus/test";
import { createApiClient } from "./client";

describe("createApiClient", () => {
  it("calls the base URL without credentials and returns the typed body", async () => {
    const fetchMock = vi.fn<(request: Request) => Promise<Response>>(() =>
      Promise.resolve(Response.json({ status: "ok" })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = createApiClient({ baseUrl: "http://api.test" });

    const { data } = await client.GET("/healthz");

    expect(data).toEqual({ status: "ok" });
    const request = fetchMock.mock.calls[0]?.[0];
    expect(request?.url).toBe("http://api.test/healthz");
    expect(request?.headers.has("Authorization")).toBe(false);
  });
});
