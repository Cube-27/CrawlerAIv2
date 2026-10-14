import { describe, expect, it } from "vite-plus/test";
import {
  buildBatch,
  buildCrawl,
  buildExtract,
  buildMap,
  INITIAL_BATCH,
  INITIAL_CRAWL,
  INITIAL_EXTRACT,
  INITIAL_MAP,
  lines,
} from "./form";

describe("lines", () => {
  it("takes one entry per line, trimmed, without blank lines", () => {
    expect(lines(" https://a.example.test/1 \r\n\nhttps://a.example.test/2\n  ")).toEqual([
      "https://a.example.test/1",
      "https://a.example.test/2",
    ]);
  });
});

describe("buildBatch", () => {
  it("sends the URLs, the formats in request order, the stored schema and the page kind", () => {
    const request = buildBatch({
      ...INITIAL_BATCH,
      urls: "https://a.example.test/1\nhttps://a.example.test/2",
      formats: ["records", "markdown"],
      schema: { source: "id", id: "s-1", json: "", prompt: "" },
      pageKind: "detail",
    });

    expect(request).toEqual({
      urls: ["https://a.example.test/1", "https://a.example.test/2"],
      formats: ["markdown", "records"],
      schema: { id: "s-1" },
      page_kind: "detail",
      fetch: { method_hint: "auto" },
    });
  });

  it("sends an inline schema and a webhook when given", () => {
    const request = buildBatch({
      ...INITIAL_BATCH,
      urls: "https://a.example.test/1",
      schema: { source: "inline", id: "", json: '{"name":"x"}', prompt: "" },
      webhookUrl: " https://hooks.example.test/done ",
    });

    expect(request).toMatchObject({
      schema: { inline: { name: "x" } },
      webhook_url: "https://hooks.example.test/done",
    });
  });

  it("declines an inline schema that is not a JSON object", () => {
    expect(
      buildBatch({
        ...INITIAL_BATCH,
        schema: { source: "inline", id: "", json: "[1]", prompt: "" },
      }),
    ).toBeNull();
  });
});

describe("buildCrawl", () => {
  it("sends the rules, scope globs and limits that are set, leaving the others to the server", () => {
    const request = buildCrawl({
      ...INITIAL_CRAWL,
      url: "https://a.example.test/",
      rules: [
        { key: "r1", pattern: "/item/*", pageKind: "detail" },
        { key: "r2", pattern: "  ", pageKind: "listing" },
      ],
      include: "/item/*\n/list/*",
      maxDepth: 2,
    });

    expect(request).toEqual({
      url: "https://a.example.test/",
      formats: ["markdown"],
      schema: null,
      page_kind_rules: [{ pattern: "/item/*", page_kind: "detail" }],
      include: ["/item/*", "/list/*"],
      exclude: [],
      max_depth: 2,
      fetch: { method_hint: "auto" },
    });
  });
});

describe("buildExtract", () => {
  it("sends the URLs and globs, the prompt, the page kind, and the limits that are set", () => {
    const request = buildExtract({
      ...INITIAL_EXTRACT,
      urls: "https://a.example.test/item/*\nhttps://a.example.test/item/1",
      schema: { source: "prompt", id: "", json: "", prompt: "title and price" },
      pageKind: "detail",
      llmCalls: 3,
    });

    expect(request).toEqual({
      urls: ["https://a.example.test/item/*", "https://a.example.test/item/1"],
      schema: { prompt: "title and price" },
      page_kind: "detail",
      budget: { llm_calls: 3 },
      fetch: { method_hint: "auto" },
    });
  });

  it("declines a request without a page kind", () => {
    expect(
      buildExtract({ ...INITIAL_EXTRACT, schema: { ...INITIAL_EXTRACT.schema, id: "s-1" } }),
    ).toBeNull();
  });
});

describe("buildMap", () => {
  it("sends the switches and leaves an empty limit to the server", () => {
    expect(buildMap({ ...INITIAL_MAP, url: "https://a.example.test/", useLinks: false })).toEqual({
      url: "https://a.example.test/",
      include: [],
      exclude: [],
      use_sitemaps: true,
      use_links: false,
    });
  });
});
