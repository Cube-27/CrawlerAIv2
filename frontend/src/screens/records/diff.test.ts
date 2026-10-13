import { describe, expect, it } from "vite-plus/test";
import type { RecordField } from "../../api/scrape";
import { diffFields } from "./diff";

function field(overrides: Partial<RecordField>): RecordField {
  return {
    value: "Blue kettle",
    status: "published",
    reason: null,
    evidence: "structured",
    confidence: 0.9,
    calibrated: true,
    source_kind: "jsonld",
    locator: "jsonld:0:$.name",
    derived_by: null,
    ...overrides,
  };
}

describe("diffFields", () => {
  it("marks a field unchanged when its status and value are equal, whatever the key order", () => {
    const stored = { price: field({ value: { amount: "19.90", currency: "EUR" } }) };
    const replayed = {
      price: field({ value: { currency: "EUR", amount: "19.90" }, confidence: 0.5 }),
    };

    expect(diffFields(stored, replayed).map(({ name, changed }) => [name, changed])).toEqual([
      ["price", false],
    ]);
  });

  it("marks a field changed when its value or its status differs", () => {
    const stored = {
      title: field({}),
      price: field({ value: { amount: "19.90", currency: "EUR" } }),
    };
    const replayed = {
      title: field({ value: "Red kettle" }),
      price: field({ value: null, status: "conflict", reason: "disagree" }),
    };

    expect(diffFields(stored, replayed).map(({ name, changed }) => [name, changed])).toEqual([
      ["price", true],
      ["title", true],
    ]);
  });

  it("lists a field present on one side only as changed, with the other side null", () => {
    const stored = { title: field({}) };
    const replayed = { brand: field({ value: "Acme" }) };

    expect(diffFields(stored, replayed)).toEqual([
      { name: "brand", stored: null, replayed: replayed.brand, changed: true },
      { name: "title", stored: stored.title, replayed: null, changed: true },
    ]);
  });
});
