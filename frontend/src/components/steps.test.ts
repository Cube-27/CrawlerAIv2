import { describe, expect, it } from "vite-plus/test";
import type { IrStep } from "../api/configs";
import { draftOf, emptyStep, sameSteps, stepText, toCorrectedStep } from "./steps";

// One stored step of each kind, as `GET /v1/configs/{id}` returns them.
const STORED: IrStep[] = [
  { xpath: "//h1", post: [{ trim: {} }] },
  { css: "h1.title", xpath: "descendant-or-self::h1[@class]", post: [] },
  { jsonld: "$.offers.price", when_type: "Product", post: [{ money: {} }] },
  { jsonpath: "$.product.title", source: "js_state", post: [] },
  { regex: "SKU: (\\w+)", post: [{ regex_replace: { pattern: "-", repl: "" } }] },
  { attr: "href", post: [{ absolutize_url: {} }] },
];

describe("steps: from a stored config to a correction", () => {
  it("sends each kind with only its own members, letting the server translate CSS", () => {
    expect(STORED.map((step) => toCorrectedStep(draftOf(step)))).toEqual([
      { xpath: "//h1", post: [{ trim: {} }] },
      { css: "h1.title", post: [] },
      { jsonld: "$.offers.price", when_type: "Product", post: [{ money: {} }] },
      { jsonpath: "$.product.title", source: "js_state", post: [] },
      { regex: "SKU: (\\w+)", post: [{ regex_replace: { pattern: "-", repl: "" } }] },
      { attr: "href", post: [{ absolutize_url: {} }] },
    ]);
  });

  it("sends no schema.org type for a JSON-LD step left without one", () => {
    expect(toCorrectedStep({ ...emptyStep("jsonld"), expression: "$.name" })).toEqual({
      jsonld: "$.name",
      when_type: null,
      post: [],
    });
  });

  it("keeps a step's typed members when its kind changes, and sends the new kind's", () => {
    const step = { ...draftOf({ xpath: "//h1", post: [{ trim: {} }] }), kind: "css" as const };
    expect(toCorrectedStep(step)).toEqual({ css: "//h1", post: [{ trim: {} }] });
  });

  it("tells changed step lists from unchanged ones", () => {
    const stored = STORED.map(draftOf);
    expect(sameSteps(stored, STORED.map(draftOf))).toBe(true);
    expect(sameSteps(stored, stored.slice(1))).toBe(false);
    const edited = stored.map((step, index) =>
      index === 0 ? { ...step, expression: "//h2" } : step,
    );
    expect(sameSteps(stored, edited)).toBe(false);
  });

  it("lists a step as its kind and expression", () => {
    expect(STORED.map(stepText)).toEqual([
      "xpath: //h1",
      "css: h1.title",
      "jsonld: $.offers.price",
      "jsonpath: $.product.title",
      "regex: SKU: (\\w+)",
      "attr: href",
    ]);
  });
});
