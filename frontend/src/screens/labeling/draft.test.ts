import { describe, expect, it } from "vite-plus/test";
import { draftFrom, emptyField, newRow, samePerson, toLabels, type FieldShape } from "./draft";

const detailShapes: Record<string, FieldShape> = {
  title: { type: "text", scope: "row", required: false },
  price: { type: "money", scope: "row", required: false },
};
const listingShapes: Record<string, FieldShape> = {
  title: { type: "text", scope: "row", required: false },
  total: { type: "text", scope: "page", required: false },
};

describe("draftFrom and toLabels", () => {
  it("round-trips stored labels through the form unchanged", () => {
    const stored = {
      label_version: 1 as const,
      status: "labeled" as const,
      labeler: "ana",
      checker: null,
      prefill_source: null,
      fields: {
        title: { value: "Blue mug", absent: false, locator: "xpath://h1", distractors: [] },
        price: {
          value: null,
          absent: true,
          locator: null,
          distractors: [{ amount: "24.90", currency: "EUR" }],
        },
      },
      rows: [],
      notes: "two prices shown",
    };

    const draft = draftFrom("detail", detailShapes, stored);
    const built = toLabels({
      draft,
      status: "labeled",
      labeler: "ana",
      checker: null,
      prefillSource: null,
    });

    expect(built).toEqual({ kind: "labels", labels: stored });
  });

  it("starts an unlabeled page with every field empty and leaves empty fields out", () => {
    const draft = draftFrom("detail", detailShapes, null);

    expect(draft).toEqual({
      fields: { title: emptyField, price: emptyField },
      rows: [],
      notes: "",
    });
    expect(
      toLabels({ draft, status: "draft", labeler: " ana ", checker: null, prefillSource: null }),
    ).toEqual({
      kind: "labels",
      labels: {
        label_version: 1,
        status: "draft",
        labeler: "ana",
        checker: null,
        prefill_source: null,
        fields: {},
        rows: [],
        notes: "",
      },
    });
  });

  it("puts page fields at the top of a listing and row fields in each row", () => {
    const draft = draftFrom("listing", listingShapes, null);
    draft.rows.push({
      ...newRow("listing", listingShapes),
      title: { ...emptyField, value: '"Cup"' },
    });

    const built = toLabels({
      draft,
      status: "draft",
      labeler: "ana",
      checker: null,
      prefillSource: null,
    });

    expect(draft.fields).toEqual({ total: emptyField });
    expect(newRow("listing", listingShapes)).toEqual({ title: emptyField });
    expect(built.kind === "labels" && built.labels.rows).toEqual([
      { fields: { title: { value: "Cup", absent: false, locator: null, distractors: [] } } },
    ]);
  });

  it("drops the value and locator of an absent field", () => {
    const draft = draftFrom("detail", detailShapes, null);
    draft.fields["price"] = { ...emptyField, absent: true, value: "oops", locator: "xpath://p" };

    const built = toLabels({
      draft,
      status: "draft",
      labeler: "ana",
      checker: null,
      prefillSource: null,
    });

    expect(built.kind === "labels" && built.labels.fields).toEqual({
      price: { value: null, absent: true, locator: null, distractors: [] },
    });
  });

  it("names each value and distractor that is not JSON, at the API's paths", () => {
    const draft = draftFrom("listing", listingShapes, null);
    draft.fields["total"] = { ...emptyField, value: "3 items" };
    draft.rows.push({ title: { ...emptyField, value: '"Cup"', distractors: '"Mug"\n\nbowl' } });

    const built = toLabels({
      draft,
      status: "draft",
      labeler: "ana",
      checker: null,
      prefillSource: null,
    });

    expect(built).toEqual({
      kind: "invalid",
      errors: [
        { field: "fields.total.value", reason: "not a JSON value" },
        { field: "rows[0].fields.title.distractors[2]", reason: "not a JSON value" },
      ],
    });
  });
});

describe("samePerson", () => {
  it.each([
    ["ana", "ANA", true],
    [" Ana ", "ana", true],
    ["straße", "STRASSE", true],
    ["ana", "ben", false],
  ])("%s and %s are the same person: %s", (a, b, same) => {
    expect(samePerson(a, b)).toBe(same);
  });
});
