import { describe, expect, it } from "vite-plus/test";
import config from "../../vite.config";
import openapi from "../../openapi.json?raw";

describe("pnpm dev proxy", () => {
  it("forwards every path of the API to the backend, so the app can call its own origin", () => {
    const prefixes = Object.keys(config.server?.proxy ?? {});
    const paths = Object.keys((JSON.parse(openapi) as { paths: Record<string, unknown> }).paths);

    const unproxied = paths.filter(
      (path) => !prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`)),
    );

    expect(unproxied).toEqual([]);
  });
});
