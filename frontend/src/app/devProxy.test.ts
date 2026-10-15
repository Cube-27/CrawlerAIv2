import { afterEach, describe, expect, it, vi } from "vite-plus/test";
import config from "../../vite.config";
import openapi from "../../openapi.json?raw";

/** The dev server config as `pnpm dev` loads it with `CRAWLERAI_UI_API_KEY` set to `apiKey`; a process variable wins
 * over the repo-root `.env` (Vite's `loadEnv`). */
async function configWith(apiKey: string) {
  vi.stubEnv("CRAWLERAI_UI_API_KEY", apiKey);
  vi.resetModules();
  const { default: loaded } = await import("../../vite.config");
  return loaded.server ?? {};
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
      { target: "http://127.0.0.1:8000", headers: { Authorization: "Bearer ui-test-key" } },
      { target: "http://127.0.0.1:8000", headers: { Authorization: "Bearer ui-test-key" } },
    ]);
  });

  it("forwards requests unchanged when CRAWLERAI_UI_API_KEY is empty", async () => {
    const { proxy = {} } = await configWith("");

    expect(Object.values(proxy)).toEqual([
      { target: "http://127.0.0.1:8000" },
      { target: "http://127.0.0.1:8000" },
    ]);
  });

  it("listens on loopback only, since anyone who reaches it acts with the key", () => {
    expect(config.server?.host).toBe("127.0.0.1");
  });
});
