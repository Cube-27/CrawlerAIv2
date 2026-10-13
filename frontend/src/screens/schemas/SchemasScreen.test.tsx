import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vite-plus/test";
import { routes } from "../../app/router";
import type { SchemaDef } from "../../api/schemas";
import { problem, stubApi } from "../../test/api";

// The forms type into several fields with user-event, which is slow in jsdom.
vi.setConfig({ testTimeout: 20_000 });

const V1_ID = "0192a000-0000-7000-8000-000000000101";
const V2_ID = "0192a000-0000-7000-8000-000000000102";
const V3_ID = "0192a000-0000-7000-8000-000000000103";
const PRESET_ID = "0192a000-0000-7000-8000-000000000201";
const DRAFT_ID = "0192a000-0000-7000-8000-000000000301";
const ADOPTED_ID = "0192a000-0000-7000-8000-000000000401";

function schemaDef(overrides: Partial<SchemaDef> = {}): SchemaDef {
  return {
    id: V2_ID,
    name: "item_detail",
    version: 2,
    origin: "user",
    status: "active",
    page_kind: "detail",
    required_groups: [["title"]],
    fields: {
      title: { type: "text", required: true, scope: "row", description: "The item's name" },
      price: { type: "money", required: false, scope: "row" },
    },
    ...overrides,
  };
}

const v1 = schemaDef({ id: V1_ID, version: 1, status: "retired" });
const v2 = schemaDef();
const preset = schemaDef({ id: PRESET_ID, name: "product", version: 1, origin: "preset" });
const draft = schemaDef({
  id: DRAFT_ID,
  name: "draft_9f2c",
  version: 1,
  origin: "prompt_draft",
  page_kind: "listing",
  required_groups: [],
  fields: { headline: { type: "text", required: false, scope: "row" } },
});

const list =
  (...items: SchemaDef[]) =>
  () =>
    Response.json({ items });
const one = (schema: SchemaDef) => () => Response.json(schema);

async function open(path: string, heading: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
  await userEvent.type(screen.getByLabelText(/API key/), "ck_first");
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
  await screen.findByRole("heading", { level: 1, name: heading });
}

async function openTab(name: string) {
  await userEvent.click(await screen.findByRole("tab", { name }));
  return within(screen.getByRole("tabpanel", { name }));
}

async function save() {
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
}

describe("schemas screen: the list", () => {
  it("is in the main navigation", async () => {
    stubApi({ "GET /v1/schemas": list() });
    await open("/schemas", "Schemas");

    expect(
      within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", {
        name: "Schemas",
      }),
    ).toHaveAttribute("href", "/schemas");
  });

  it("shows every version's name, version, origin, status and page kind, and opens one by its row", async () => {
    const calls = stubApi({ "GET /v1/schemas": list(v1, v2, preset, draft) });
    await open("/schemas", "Schemas");

    const table = await screen.findByRole("grid", { name: "Schemas" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "item_detail1userretireddetail",
      "item_detail2useractivedetail",
      "product1presetactivedetail",
      "draft_9f2c1prompt_draftactivelisting",
    ]);
    expect(rows[1]).toHaveAttribute("data-href", `/schemas/${V2_ID}`);
    expect(calls[0]).toMatchObject({
      path: "/v1/schemas",
      query: "",
      authorization: "Bearer ck_first",
    });
  });

  it("says how to add one when there are none", async () => {
    stubApi({ "GET /v1/schemas": list() });
    await open("/schemas", "Schemas");

    expect(await screen.findByText("No schemas yet")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New schema" })).not.toHaveLength(0);
  });

  it("shows the problem when the list can't be read", async () => {
    stubApi({
      "GET /v1/schemas": () =>
        problem(429, { title: "Too many requests", detail: "Slow down." }, { "Retry-After": "30" }),
    });
    await open("/schemas", "Schemas");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Too many requests");
    expect(alert).toHaveTextContent("Retry after 30 seconds.");
  });
});

describe("schemas screen: one schema", () => {
  it("shows its fields, its JSON and its versions", async () => {
    const calls = stubApi({
      [`GET /v1/schemas/${V2_ID}`]: one(v2),
      "GET /v1/schemas": list(v1, v2),
    });
    await open(`/schemas/${V2_ID}`, "item_detail");

    const fields = await openTab("Fields");
    expect(
      fields
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.textContent),
    ).toEqual(["titleTextYesrowThe item's name", "priceMoneyNorow—"]);
    const json = await openTab("JSON");
    expect(JSON.parse(json.getByRole<HTMLTextAreaElement>("textbox").value)).toEqual({
      name: "item_detail",
      page_kind: "detail",
      required_groups: [["title"]],
      fields: v2.fields,
    });
    const versions = await openTab("Versions");
    const rows = versions.getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual(["1userretired", "2useractive"]);
    expect(rows[0]).toHaveAttribute("data-href", `/schemas/${V1_ID}`);
    expect(calls.find((call) => call.path === "/v1/schemas")?.query).toBe("name=item_detail");
  });

  it("offers no edit or retire for a preset", async () => {
    stubApi({ [`GET /v1/schemas/${PRESET_ID}`]: one(preset), "GET /v1/schemas": list(preset) });
    await open(`/schemas/${PRESET_ID}`, "product");

    await screen.findByRole("tab", { name: "Fields" });
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
  });

  it("offers edit only on the latest version", async () => {
    stubApi({
      [`GET /v1/schemas/${V1_ID}`]: one(schemaDef({ ...v1, status: "active" })),
      "GET /v1/schemas": list(v1, v2),
    });
    await open(`/schemas/${V1_ID}`, "item_detail");

    await screen.findByRole("tab", { name: "Fields" });
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retire" })).toBeInTheDocument();
  });

  it("retires the version after a confirmation, then shows it retired", async () => {
    let current = v2;
    const calls = stubApi({
      [`GET /v1/schemas/${V2_ID}`]: () => Response.json(current),
      "GET /v1/schemas": () => Response.json({ items: [v1, current] }),
      [`DELETE /v1/schemas/${V2_ID}`]: () => {
        current = { ...v2, status: "retired" };
        return new Response(null, { status: 204 });
      },
    });
    await open(`/schemas/${V2_ID}`, "item_detail");

    await userEvent.click(await screen.findByRole("button", { name: "Retire" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Retire" }),
    );

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    });
    expect(screen.getByText("retired")).toBeVisible();
    expect(calls.filter((call) => call.method === "DELETE")).toHaveLength(1);
  });

  it("shows a refused retire as a problem", async () => {
    stubApi({
      [`GET /v1/schemas/${V2_ID}`]: one(v2),
      "GET /v1/schemas": list(v1, v2),
      [`DELETE /v1/schemas/${V2_ID}`]: () =>
        problem(409, { title: "Conflict", detail: "schema item_detail is a preset" }),
    });
    await open(`/schemas/${V2_ID}`, "item_detail");

    await userEvent.click(await screen.findByRole("button", { name: "Retire" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Retire" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("schema item_detail is a preset");
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
    const name = await screen.findByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("draft_9f2c");
    await userEvent.clear(name);
    await userEvent.type(name, "headlines");
    await save();

    await screen.findByRole("heading", { level: 1, name: "headlines" });
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      name: "headlines",
      page_kind: "listing",
      required_groups: [],
      fields: { headline: { type: "text", required: false, scope: "row" } },
    });
  });
});

describe("schemas screen: creating and editing", () => {
  it("creates a schema from the form", async () => {
    const created = schemaDef({ id: ADOPTED_ID, name: "event", version: 1 });
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

  it("asks for the type's parameters: a vocabulary for an enum, a JSON item for a list", async () => {
    const calls = stubApi({
      "POST /v1/schemas": () => problem(409, { title: "Conflict", detail: "taken" }),
    });
    await open("/schemas/new", "New schema");

    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "palette");
    await userEvent.click(
      within(screen.getByRole("radiogroup", { name: "Page kind" })).getByLabelText("Detail"),
    );
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));
    const first = within(screen.getByRole("group", { name: "Field 1" }));
    await userEvent.type(first.getByRole("textbox", { name: "Field name" }), "shade");
    await userEvent.click(first.getByRole("button", { name: /Type/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Enum" }));
    await userEvent.type(first.getByRole("textbox", { name: "Vocabulary" }), "shades-v1");
    const second = within(screen.getByRole("group", { name: "Field 2" }));
    await userEvent.type(second.getByRole("textbox", { name: "Field name" }), "tags");
    await userEvent.click(second.getByRole("button", { name: /Type/ }));
    await userEvent.click(await screen.findByRole("option", { name: "List" }));
    await userEvent.click(second.getByRole("textbox", { name: "Item (JSON)" }));
    await userEvent.paste('{"type": "text"}');
    await save();

    expect(await screen.findByRole("alert")).toHaveTextContent("taken");
    expect(calls[0]?.body).toMatchObject({
      fields: {
        shade: { type: "enum", vocab: "shades-v1", required: false, scope: "row" },
        tags: { type: "list", item: { type: "text" }, required: false, scope: "row" },
      },
    });
  });

  it("creates a schema from the JSON tab", async () => {
    const created = schemaDef({ id: ADOPTED_ID, name: "event", version: 1 });
    const calls = stubApi({
      "POST /v1/schemas": () => Response.json(created, { status: 201 }),
      [`GET /v1/schemas/${ADOPTED_ID}`]: one(created),
      "GET /v1/schemas": list(created),
    });
    await open("/schemas/new", "New schema");
    const document = {
      name: "event",
      page_kind: "detail",
      required_groups: [],
      fields: { venue: { type: "location", required: true, scope: "row" } },
    };

    const json = await openTab("JSON");
    await userEvent.clear(json.getByRole("textbox", { name: "Schema JSON" }));
    await userEvent.paste(JSON.stringify(document));
    await save();

    await screen.findByRole("heading", { level: 1, name: "event" });
    expect(calls.find((call) => call.method === "POST")?.body).toEqual(document);
  });

  it("keeps JSON that is not a schema document in the JSON tab, with the reason", async () => {
    const calls = stubApi({});
    await open("/schemas/new", "New schema");

    const json = await openTab("JSON");
    await userEvent.clear(json.getByRole("textbox", { name: "Schema JSON" }));
    await userEvent.paste('{"name": "x", "fields": {"a": {"type": "colour"}}}');
    await userEvent.click(screen.getByRole("tab", { name: "Form" }));

    expect(screen.getByRole("tab", { name: "JSON" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("textbox", { name: "Schema JSON" })).toHaveAccessibleDescription(
      /`fields` must map names to field specs with a known type\./,
    );
    await save();
    expect(calls).toHaveLength(0);
  });

  it("shows the server's errors above the form and next to the field they name", async () => {
    stubApi({
      [`GET /v1/schemas/${DRAFT_ID}`]: one(draft),
      "POST /v1/schemas": () =>
        problem(422, {
          title: "Unprocessable content",
          detail: "the schema document is invalid",
          errors: [{ field: "fields.headline.type", reason: "Input should be text or long_text." }],
        }),
    });
    await open(`/schemas/new?from=${DRAFT_ID}`, "New schema");

    await screen.findByDisplayValue("draft_9f2c");
    await save();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("the schema document is invalid");
    expect(alert).toHaveTextContent("fields.headline.type: Input should be text or long_text.");
    expect(
      within(screen.getByRole("group", { name: "Field 1" })).getByRole("textbox", {
        name: "Field name",
      }),
    ).toHaveAccessibleDescription(/Input should be text or long_text\./);
  });

  it("refuses two fields with one name", async () => {
    const calls = stubApi({});
    await open("/schemas/new", "New schema");

    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "x");
    await userEvent.click(
      within(screen.getByRole("radiogroup", { name: "Page kind" })).getByLabelText("Detail"),
    );
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));
    for (const group of ["Field 1", "Field 2"]) {
      await userEvent.type(
        within(screen.getByRole("group", { name: group })).getByRole("textbox", {
          name: "Field name",
        }),
        "title",
      );
    }
    await save();

    expect(
      within(screen.getByRole("group", { name: "Field 2" })).getByRole("textbox", {
        name: "Field name",
      }),
    ).toHaveAccessibleDescription(/Another field has this name\./);
    expect(calls).toHaveLength(0);
  });

  it("saves an edit as the next version, with the whole document and no name", async () => {
    const v3 = schemaDef({ id: V3_ID, version: 3 });
    const calls = stubApi({
      [`GET /v1/schemas/${V2_ID}`]: one(v2),
      [`GET /v1/schemas/${V3_ID}`]: one(v3),
      "GET /v1/schemas": list(v1, v2),
      [`PUT /v1/schemas/${V2_ID}`]: () => Response.json(v3),
    });
    await open(`/schemas/${V2_ID}`, "item_detail");

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await screen.findByRole("heading", { level: 1, name: "Edit item_detail" });
    expect(screen.queryByRole("textbox", { name: "Name" })).not.toBeInTheDocument();
    const price = within(await screen.findByRole("group", { name: "Field 2" }));
    await userEvent.type(price.getByRole("textbox", { name: "Description" }), "Asking price");
    await userEvent.click(screen.getByRole("button", { name: "Remove field 1" }));
    await save();

    await screen.findByText("v3");
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({
      page_kind: "detail",
      required_groups: [["title"]],
      fields: {
        price: { type: "money", required: false, scope: "row", description: "Asking price" },
      },
    });
  });
});
