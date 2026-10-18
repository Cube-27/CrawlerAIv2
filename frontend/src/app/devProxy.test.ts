import { afterEach, describe, expect, it, vi } from "vite-plus/test";
import config, { refuseCrossSite } from "../../vite.config";
import openapi from "../../openapi.json?raw";

/** The dev server config as `pnpm dev` loads it with `CRAWLERAI_UI_API_KEY` set to `apiKey`; a process variable wins
 * over the repo-root `.env` (Vite's `loadEnv`). */
async function configWith(apiKey: string) {
  vi.stubEnv("CRAWLERAI_UI_API_KEY", apiKey);
  vi.resetModules();
  const { default: loaded } = await import("../../vite.config");
  return loaded.server ?? {};
}

/** What the proxies' bypass answers for a request with `headers`: `false` refuses it (Vite answers 404). */
function bypassFor(headers: Record<string, string>): unknown {
  return refuseCrossSite({ headers });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("pnpm dev proxy", () => {
  it("forwards every path of the API to the backend, so the app can call its own origin", () => {
    const prefixes = Object.keys(config.server?.proxy ?? {});
    const paths = Object.keys((JSON.parse(openapi) as { paths: Record<string, unknown> }).paths);

    const unproxied = paths.filter(
      (path) => !prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`)),
    );

    expect(unproxied).toEqual([]);
  });

  it("attaches CRAWLERAI_UI_API_KEY as a bearer token to every proxied request", async () => {
    const { proxy = {} } = await configWith("ui-test-key");

    expect(Object.values(proxy)).toEqual([
      expect.objectContaining({
        target: "http://127.0.0.1:8000",
        headers: { Authorization: "Bearer ui-test-key" },
      }),
      expect.objectContaining({
        target: "http://127.0.0.1:8000",
        headers: { Authorization: "Bearer ui-test-key" },
      }),
    ]);
  });

  it("listens on loopback only, and lets no other origin read responses", () => {
    expect(config.server?.host).toBe("127.0.0.1");
    expect(config.server?.cors).toBe(false);
  });

  it("refuses requests another site's page made, so they never get the key", () => {
    expect(bypassFor({ "sec-fetch-site": "cross-site" })).toBe(false);
    expect(bypassFor({ "sec-fetch-site": "same-site" })).toBe(false);
  });

  it("proxies the app's own requests, typed URLs and requests from tools without Fetch Metadata", () => {
    expect(bypassFor({ "sec-fetch-site": "same-origin" })).toBeUndefined();
    expect(bypassFor({ "sec-fetch-site": "none" })).toBeUndefined();
    expect(bypassFor({})).toBeUndefined();
  });
});
