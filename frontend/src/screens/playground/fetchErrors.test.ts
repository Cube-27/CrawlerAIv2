import { describe, expect, it } from "vite-plus/test";
import { DEFAULT_ADVANCED, newAction, type AdvancedFetch } from "./advanced";
import { batchErrors, initialBatch, DEFAULT_BATCH_OPTIONS } from "./batch/form";
import { crawlErrors, INITIAL_CRAWL } from "./crawl/form";
import { extractErrors, INITIAL_EXTRACT } from "./extract/form";
import { INITIAL_FORM, scrapeErrors } from "./scrape/form";
import type { MethodHint } from "../../api/scrape";

// The combinations of `fetch` members the server always refuses (FetchOptions._coherent, check_formats) are named on
// their field before sending, in every form that has the fetch options.

const HEADERS: AdvancedFetch = { ...DEFAULT_ADVANCED, headers: "Authorization: Bearer t" };
const STEP: AdvancedFetch = {
  ...DEFAULT_ADVANCED,
  actions: [{ ...newAction("press"), value: "Enter" }],
};

function batch(
  methodHint: MethodHint,
  advanced: AdvancedFetch,
  formats: ("markdown" | "screenshot" | "pdf")[],
) {
  return batchErrors({
    ...initialBatch("https://a.example.test/"),
    formats,
    options: { ...DEFAULT_BATCH_OPTIONS, methodHint, advanced },
  });
}

describe("fetch option errors", () => {
  it("a screenshot or a PDF over HTTP is refused on the fetch method", () => {
    expect(Object.keys(batch("http", DEFAULT_ADVANCED, ["screenshot"]))).toEqual([
      "fetch.method_hint",
    ]);
    expect(Object.keys(batch("http", DEFAULT_ADVANCED, ["pdf"]))).toEqual(["fetch.method_hint"]);
    expect(batch("auto", DEFAULT_ADVANCED, ["screenshot"])).toEqual({});
    expect(batch("http", DEFAULT_ADVANCED, ["markdown"])).toEqual({});
  });

  it("wait for or page actions over HTTP are refused on the fetch method", () => {
    expect(Object.keys(batch("http", STEP, ["markdown"]))).toEqual(["fetch.method_hint"]);
    expect(
      Object.keys(batch("http", { ...DEFAULT_ADVANCED, waitFor: "500" }, ["markdown"])),
    ).toEqual(["fetch.method_hint"]);
  });

  it("headers with the browser, wait for or page actions are refused on the headers", () => {
    expect(Object.keys(batch("browser", HEADERS, ["markdown"]))).toEqual(["fetch.headers"]);
    expect(Object.keys(batch("auto", { ...HEADERS, actions: STEP.actions }, ["markdown"]))).toEqual(
      ["fetch.headers"],
    );
    expect(Object.keys(batch("auto", { ...HEADERS, waitFor: ".price" }, ["markdown"]))).toEqual([
      "fetch.headers",
    ]);
    expect(batch("auto", HEADERS, ["markdown"])).toEqual({});
    expect(batch("http", HEADERS, ["markdown"])).toEqual({});
  });

  it("every form with the fetch options checks them", () => {
    const options = { methodHint: "browser" as const, advanced: HEADERS };
    expect(
      scrapeErrors({ ...INITIAL_FORM, options: { ...INITIAL_FORM.options, ...options } }),
    ).toHaveProperty("fetch.headers");
    expect(
      crawlErrors({ ...INITIAL_CRAWL, options: { ...INITIAL_CRAWL.options, ...options } }),
    ).toHaveProperty("fetch.headers");
    const extract = { ...INITIAL_EXTRACT, schemaId: "s1", schemaPageKind: "detail" as const };
    expect(
      extractErrors({ ...extract, options: { ...extract.options, ...options } }),
    ).toHaveProperty("fetch.headers");
    expect(extractErrors(extract)).toEqual({});
  });
});
