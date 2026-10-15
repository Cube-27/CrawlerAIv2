import { describe, expect, it } from "vite-plus/test";
import { buildExtract, INITIAL_EXTRACT } from "./form";

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
