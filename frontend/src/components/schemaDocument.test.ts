import { describe, expect, it } from "vite-plus/test";
import {
  contentOf,
  EMPTY_FORM,
  formOf,
  inputErrors,
  jsonOf,
  newSchemaOf,
  parseForm,
  withType,
  type SchemaFormState,
} from "./schemaDocument";

const form: SchemaFormState = {
  name: " item_detail ",
  pageKind: "detail",
  requiredGroups: "title, price\n\n  sku ,  \n",
  fields: [
    { key: "a", name: " title ", spec: { type: "text", required: true, scope: "row" } },
    { key: "b", name: "price", spec: { type: "money", required: false, scope: "row" } },
    {
      key: "c",
      name: "tags",
      spec: {
        type: "list",
        required: false,
        scope: "row",
        item: { type: "text", required: false, scope: "row" },
      },
    },
  ],
};

describe("schema document: the request body", () => {
  it("is the document with trimmed names and one required group per non-empty line", () => {
    expect(newSchemaOf(form)).toEqual({
      name: "item_detail",
      page_kind: "detail",
      required_groups: [["title", "price"], ["sku"]],
      fields: {
        title: { type: "text", required: true, scope: "row" },
        price: { type: "money", required: false, scope: "row" },
        tags: {
          type: "list",
          required: false,
          scope: "row",
          item: { type: "text", required: false, scope: "row" },
        },
      },
    });
  });

  it("is not built until a page kind is chosen", () => {
    expect(newSchemaOf({ ...form, pageKind: null })).toBeNull();
    expect(contentOf({ ...form, pageKind: null })).toBeNull();
  });

  it("leaves the name out of an edit, which keeps it", () => {
    expect(contentOf(form)).toEqual({
      page_kind: "detail",
      required_groups: [["title", "price"], ["sku"]],
      fields: newSchemaOf(form)?.fields,
    });
    expect(contentOf(form)).not.toHaveProperty("name");
  });

  it("reads a stored schema back into the same document", () => {
    const stored = {
      name: "item_detail",
      page_kind: "listing" as const,
      required_groups: [["title"]],
      fields: { title: { type: "text" as const, required: true, scope: "page" as const } },
    };

    expect(newSchemaOf(formOf(stored))).toEqual(stored);
  });
});

describe("schema document: the JSON tab", () => {
  it("round-trips the form through its JSON", () => {
    const parsed = parseForm(jsonOf(form, "create"), "create", EMPTY_FORM);

    expect(parsed.kind === "ok" ? newSchemaOf(parsed.form) : parsed).toEqual(newSchemaOf(form));
  });

  it("keeps a page kind that was not chosen yet as null", () => {
    const parsed = parseForm(jsonOf({ ...form, pageKind: null }, "create"), "create", EMPTY_FORM);

    expect(parsed.kind === "ok" ? parsed.form.pageKind : parsed).toBeNull();
  });

  it("has no name when editing, and keeps the current one", () => {
    const text = jsonOf(form, "edit");
    const withName = JSON.stringify({ ...JSON.parse(text), name: "renamed" });

    expect(JSON.parse(text)).not.toHaveProperty("name");
    const parsed = parseForm(withName, "edit", form);
    expect(parsed.kind === "ok" ? parsed.form.name : parsed).toBe(" item_detail ");
  });

  it.each([
    ["not JSON", "{", "Enter the schema as a JSON object."],
    ["an array", "[]", "Enter the schema as a JSON object."],
    ["no name", '{"page_kind":"detail","fields":{}}', "`name` must be a string."],
    [
      "an unknown page kind",
      '{"name":"x","page_kind":"grid","fields":{}}',
      "`page_kind` must be detail or listing.",
    ],
    [
      "groups that are not lists",
      '{"name":"x","required_groups":["a"],"fields":{}}',
      "`required_groups` must be lists of field names.",
    ],
    [
      "an unknown field type",
      '{"name":"x","fields":{"a":{"type":"colour"}}}',
      "`fields` must map names to field specs with a known type.",
    ],
    [
      "a nested unknown type",
      '{"name":"x","fields":{"a":{"type":"list","item":{"type":"colour"}}}}',
      "`fields` must map names to field specs with a known type.",
    ],
    [
      "an unknown scheme",
      '{"name":"x","fields":{"a":{"type":"identifier","scheme":"ean"}}}',
      "`fields` must map names to field specs with a known type.",
    ],
  ])("refuses %s with the reason", (_, text, reason) => {
    expect(parseForm(text, "create", EMPTY_FORM)).toEqual({ kind: "invalid", reason });
  });
});

describe("schema document: changing a field's type", () => {
  it("keeps the common members and drops the old type's parameters", () => {
    expect(
      withType(
        { type: "enum", vocab: "colors-v1", required: true, scope: "page", description: "Shade" },
        "text",
      ),
    ).toEqual({ type: "text", required: true, scope: "page", description: "Shade" });
  });
});

describe("schema document: server errors", () => {
  it("puts each error under the field row or input its path names", () => {
    const problem = {
      title: "The schema document is invalid",
      detail: null,
      retryAfter: null,
      errors: [
        { field: "fields.price.type", reason: "Input should be a valid type." },
        { field: "fields.price", reason: "money needs a currency." },
        { field: "name", reason: "String should match pattern." },
      ],
    };

    expect(inputErrors(problem)).toEqual({
      "fields.price": "Input should be a valid type. money needs a currency.",
      name: "String should match pattern.",
    });
    expect(inputErrors(null)).toEqual({});
  });
});
