import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { routes } from "../../app/router";
import type { SchemaDef } from "../../api/schemas";
import { stubApi } from "../../test/api";
import { fieldSpec } from "../../test/schemas";

const RETIRED_ID = "0192a000-0000-7000-8000-000000000101";
const SCHEMA_ID = "0192a000-0000-7000-8000-000000000102";
const PRESET_ID = "0192a000-0000-7000-8000-000000000201";
const DRAFT_ID = "0192a000-0000-7000-8000-000000000301";
const ADOPTED_ID = "0192a000-0000-7000-8000-000000000401";

function schemaDef(overrides: Partial<SchemaDef> = {}): SchemaDef {
  const fields = overrides.fields ?? {
    title: fieldSpec({
      type: "text",
      required: true,
      scope: "row",
      description: "The item's name",
    }),
    price: fieldSpec({ type: "money", required: false, scope: "row" }),
  };
  return {
    id: SCHEMA_ID,
    name: "item_detail",
    origin: "user",
    status: "active",
    page_kind: "detail",
    required_groups: [["title"]],
    fields,
    field_order: Object.keys(fields),
    labels: null,
    ...overrides,
  };
}

const retired = schemaDef({ id: RETIRED_ID, name: "event_detail", status: "retired" });
const schema = schemaDef();
const preset = schemaDef({ id: PRESET_ID, name: "product", origin: "preset" });
const draft = schemaDef({
  id: DRAFT_ID,
  name: "draft_9f2c",
  origin: "prompt_draft",
  page_kind: "listing",
  required_groups: [],
  fields: { headline: fieldSpec({ type: "text", required: false, scope: "row" }) },
});

const list =
  (...items: SchemaDef[]) =>
  () =>
    Response.json({ items });
const one = (schema: SchemaDef) => () => Response.json(schema);

async function open(path: string, heading: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
  await screen.findByRole("heading", { level: 1, name: heading });
}

async function save() {
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
}

describe("schemas screen: the list", () => {
  it("shows every schema's name, origin, status and page kind, and opens one by its row", async () => {
    const calls = stubApi({ "GET /v1/schemas": list(retired, schema, preset, draft) });
    await open("/schemas", "Schemas");

    const table = await screen.findByRole("grid", { name: "Schemas" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "event_detailuserretireddetail",
      "item_detailuseractivedetail",
      "productpresetactivedetail",
      "draft_9f2cprompt_draftactivelisting",
    ]);
    expect(rows[1]).toHaveAttribute("data-href", `/schemas/${SCHEMA_ID}`);
    expect(calls[0]).toMatchObject({
      path: "/v1/schemas",
      query: "",
      authorization: null,
    });
  });
});

describe("schemas screen: adopting a prompt draft", () => {
  it("creates a user schema from the draft under the name given", async () => {
    const adopted = schemaDef({ ...draft, id: ADOPTED_ID, name: "headlines", origin: "user" });
    const calls = stubApi({
      [`GET /v1/schemas/${DRAFT_ID}`]: one(draft),
      [`GET /v1/schemas/${ADOPTED_ID}`]: one(adopted),
      "GET /v1/schemas": () => Response.json({ items: [draft] }),
      "POST /v1/schemas": () => Response.json(adopted, { status: 201 }),
    });
    await open(`/schemas/${DRAFT_ID}`, "draft_9f2c");

    await userEvent.click(await screen.findByRole("button", { name: "Adopt as user schema" }));
    await screen.findByRole("heading", { level: 1, name: "New schema" });
    // The draft's own name is taken by the draft (UAT F32): the form starts without one.
    const name = await screen.findByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("");
    expect(name).toHaveAccessibleDescription(/A name no other schema has/);
    await userEvent.type(name, "headlines");
    await save();

    await screen.findByRole("heading", { level: 1, name: "headlines" });
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      name: "headlines",
      page_kind: "listing",
      required_groups: [],
      fields: { headline: fieldSpec({ type: "text", required: false, scope: "row" }) },
    });
  });
});

describe("schemas screen: creating and editing", () => {
  it("creates a schema from the form", async () => {
    const created = schemaDef({ id: ADOPTED_ID, name: "event" });
    const calls = stubApi({
      "POST /v1/schemas": () => Response.json(created, { status: 201 }),
      [`GET /v1/schemas/${ADOPTED_ID}`]: one(created),
      "GET /v1/schemas": list(created),
    });
    await open("/schemas/new", "New schema");

    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "event");
    await userEvent.click(
      within(screen.getByRole("radiogroup", { name: "Page kind" })).getByLabelText("Listing"),
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Required groups" }), "starts, ends");
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));
    const row = within(screen.getByRole("group", { name: "Field 1" }));
    await userEvent.type(row.getByRole("textbox", { name: "Field name" }), "starts");
    await userEvent.click(row.getByRole("button", { name: /Type/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Date and time" }));
    await userEvent.click(row.getByRole("checkbox", { name: "Required" }));
    await userEvent.click(
      within(row.getByRole("radiogroup", { name: "Scope" })).getByLabelText("Page"),
    );
    await userEvent.type(row.getByRole("textbox", { name: "Description" }), "When it starts");
    await save();

    await screen.findByRole("heading", { level: 1, name: "event" });
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      name: "event",
      page_kind: "listing",
      required_groups: [["starts", "ends"]],
      fields: {
        starts: { type: "datetime", required: true, scope: "page", description: "When it starts" },
      },
    });
  });
});
