import { describe, expect, it } from "vite-plus/test";
import { recordField } from "../../test/records";
import { diffFields } from "./diff";

describe("diffFields", () => {
  it("marks a field unchanged when its status and value are equal, whatever the key order", () => {
    const stored = { price: recordField({ value: { amount: "19.90", currency: "EUR" } }) };
    const replayed = {
      price: recordField({ value: { currency: "EUR", amount: "19.90" }, confidence: 0.5 }),
    };

    expect(diffFields(stored, replayed).map(({ name, changed }) => [name, changed])).toEqual([
      ["price", false],
    ]);
  });

  it("lists a field present on one side only as changed, with the other side null", () => {
    const stored = { title: recordField({}) };
    const replayed = { brand: recordField({ value: "Acme" }) };

    expect(diffFields(stored, replayed)).toEqual([
      { name: "brand", stored: null, replayed: replayed.brand, changed: true },
      { name: "title", stored: stored.title, replayed: null, changed: true },
    ]);
  });
});
