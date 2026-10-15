import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vite-plus/test";
import { routes } from "../../app/router";
import type { ConfigDetail, ConfigSummary, ValidationReport } from "../../api/configs";
import type { SchemaDef } from "../../api/schemas";
import { problem, stubApi } from "../../test/api";

const HOST = "shop.example.test";
const SCHEMA_ID = "0192a000-0000-7000-8000-000000000101";
const V1_ID = "0192a000-0000-7000-8000-000000000501";
const V2_ID = "0192a000-0000-7000-8000-000000000502";
const V3_ID = "0192a000-0000-7000-8000-000000000503";
const JOB_ID = "0192a000-0000-7000-8000-000000000901";
const HELD_OUT = ["0192a000-0000-7000-8000-000000000701", "0192a000-0000-7000-8000-000000000702"];

const schema: SchemaDef = {
  id: SCHEMA_ID,
  name: "item_detail",
  version: 2,
  origin: "user",
  status: "active",
  page_kind: "detail",
  required_groups: [["title"]],
  fields: {
    title: { type: "text", required: true, scope: "row" },
    price: { type: "money", required: false, scope: "row" },
    sku: { type: "identifier", scheme: "sku", required: false, scope: "row" },
  },
};

const report: ValidationReport = {
  held_out: HELD_OUT,
  fields: {
    title: {
      pages: 2,
      matched: 2,
      valid: 2,
      published: 2,
      reproduced: 2,
      comparable: 2,
      corroborated_on: 2,
      status: "corroborated",
      yield: 1,
      validity: 1,
    },
    price: {
      pages: 2,
      matched: 1,
      valid: 0,
      published: 0,
      reproduced: 0,
      comparable: 0,
      corroborated_on: 0,
      status: null,
      dropped: "validity",
      yield: 0.5,
      validity: 0,
    },
  },
  listing: null,
};

function summary(overrides: Partial<ConfigSummary> = {}): ConfigSummary {
  return {
    id: V2_ID,
    site: HOST,
    schema_id: SCHEMA_ID,
    schema_version: 2,
    page_kind: "detail",
    version: 2,
    status: "active",
    origin: "induced",
    field_status: { title: "corroborated", price: "uncorroborated" },
    validation_report: report,
    ...overrides,
  };
}

const v1 = summary({ id: V1_ID, version: 1, status: "suspended", field_status: {} });
const v2 = summary();

const detail: ConfigDetail = {
  ...v2,
  ir: {
    ir_version: "1",
    site: HOST,
    schema: { name: "item_detail", version: 2 },
    page_kind: "detail",
    fetch: { method: "http" },
    fields: {
      title: {
        status: "corroborated",
        steps: [{ xpath: "//h1", post: [{ trim: {} }] }],
        yield: 1,
        validity: 1,
      },
      price: {
        status: "uncorroborated",
        steps: [{ jsonld: "$.offers.price", when_type: "Product", post: [{ money: {} }] }],
        yield: 0.5,
        validity: 0.25,
      },
    },
    provenance: {
      origin: "induced",
      validated_on: HELD_OUT,
      learned_at: "2026-10-01T00:00:00Z",
      engine_version: "0.1.0",
    },
  },
};

const corrected: ConfigDetail = {
  ...detail,
  id: V3_ID,
  version: 3,
  origin: "operator",
  field_status: { title: "operator", price: "operator", sku: "operator" },
};

const json = (body: unknown) => () => Response.json(body);

async function open(path: string, heading: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
  await screen.findByRole("heading", { level: 1, name: heading });
}

/** Replaces a field's text as a paste does: one input event, not one per character, so each step of a long form
 * test re-renders the form once. */
async function replaceText(field: HTMLElement, text: string) {
  await userEvent.clear(field);
  await userEvent.paste(text);
}

async function openTab(name: string) {
  await userEvent.click(await screen.findByRole("tab", { name }));
  return within(screen.getByRole("tabpanel", { name }));
}

function rowsOf(grid: HTMLElement): (string | null)[] {
  return within(grid)
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.textContent);
}

function configApi(extra: Record<string, () => Response> = {}) {
  return stubApi({
    [`GET /v1/configs/${V2_ID}`]: json(detail),
    [`GET /v1/sites/${HOST}/configs`]: json({ items: [v1, v2] }),
    "GET /v1/schemas": json({ items: [schema] }),
    [`GET /v1/schemas/${SCHEMA_ID}`]: json(schema),
    ...extra,
  });
}

describe("sites screen", () => {
  it("is in the main navigation and opens a site by its host", async () => {
    const calls = configApi();
    await open("/sites", "Sites");

    expect(
      within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Sites" }),
    ).toHaveAttribute("href", "/sites");
    await userEvent.type(screen.getByRole("textbox", { name: "Host" }), ` ${HOST} `);
    await userEvent.click(screen.getByRole("button", { name: "Open site" }));

    await screen.findByRole("heading", { level: 1, name: HOST });
    const table = await screen.findByRole("grid", { name: "Config versions" });
    expect(rowsOf(table)).toEqual([
      "item_detail version 2detail1suspendedinducedNo fields",
      "item_detail version 2detail2activeinduced1 corroborated, 1 uncorroborated",
    ]);
    expect(within(table).getAllByRole("row")[2]).toHaveAttribute("data-href", `/configs/${V2_ID}`);
    expect(calls.find((call) => call.path.startsWith("/v1/sites"))).toMatchObject({
      method: "GET",
      path: `/v1/sites/${HOST}/configs`,
      authorization: null,
    });
  });

  it("says when a site has no configs", async () => {
    stubApi({
      [`GET /v1/sites/${HOST}/configs`]: json({ items: [] }),
      "GET /v1/schemas": json({ items: [] }),
    });
    await open(`/sites/${HOST}`, HOST);

    expect(await screen.findByText("No configs yet")).toBeInTheDocument();
  });

  it("starts learning a site that has no config yet, for the schema chosen", async () => {
    const calls = stubApi({
      [`GET /v1/sites/${HOST}/configs`]: json({ items: [] }),
      "GET /v1/schemas": json({ items: [schema] }),
      [`POST /v1/sites/${HOST}/learn`]: () => Response.json({ job_id: JOB_ID }, { status: 202 }),
    });
    await open(`/sites/${HOST}`, HOST);
    await screen.findByText("No configs yet");

    await userEvent.click(screen.getByRole("button", { name: /Schema/ }));
    await userEvent.click(await screen.findByRole("option", { name: "item_detail version 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Learn now" }));

    expect(await screen.findByText(`Learning started as job ${JOB_ID}.`)).toBeInTheDocument();
    expect(calls.filter((call) => call.method === "POST")).toMatchObject([
      { path: `/v1/sites/${HOST}/learn`, body: { schema_id: SCHEMA_ID, force: false } },
    ]);
  });

  it("asks for a schema before it starts learning a site", async () => {
    const calls = stubApi({
      [`GET /v1/sites/${HOST}/configs`]: json({ items: [] }),
      "GET /v1/schemas": json({ items: [schema] }),
    });
    await open(`/sites/${HOST}`, HOST);
    await screen.findByText("No configs yet");

    await userEvent.click(screen.getByRole("button", { name: "Learn now" }));

    expect(calls.filter((call) => call.method === "POST")).toEqual([]);
  });

  it("shows the problem for a site the API doesn't know", async () => {
    stubApi({
      [`GET /v1/sites/${HOST}/configs`]: () =>
        problem(404, { title: "Not found", detail: `no site ${HOST}` }),
      "GET /v1/schemas": json({ items: [] }),
    });
    await open(`/sites/${HOST}`, HOST);

    expect(await screen.findByRole("alert")).toHaveTextContent(`no site ${HOST}`);
  });
});

describe("config screen: reading a version", () => {
  it("shows each field's steps, status, yield and validity", async () => {
    configApi();
    await open(`/configs/${V2_ID}`, HOST);

    const fields = await openTab("Fields");
    expect(fields.getByText("Fetch method: http")).toBeInTheDocument();
    expect(rowsOf(fields.getByRole("grid", { name: "Config fields" }))).toEqual([
      "titlecorroboratedxpath: //h11.001.00",
      "priceuncorroboratedjsonld: $.offers.price0.500.25",
    ]);
  });

  it("shows the validation report, with a dropped field's reason", async () => {
    configApi();
    await open(`/configs/${V2_ID}`, HOST);

    const validation = await openTab("Validation");
    expect(validation.getByText("Validated on 2 held-out pages.")).toBeInTheDocument();
    expect(rowsOf(validation.getByRole("grid", { name: "Field validation" }))).toEqual([
      "titlecorroborated2/22/22/22/21.001.00",
      "pricedropped: validity1/20/20/00/00.500.00",
    ]);
  });
});

describe("config screen: correction", () => {
  it("sends the changed steps and confirmations, then shows the new version and its report", async () => {
    const calls = configApi({ [`PUT /v1/configs/${V2_ID}`]: json(corrected) });
    await open(`/configs/${V2_ID}`, HOST);
    const form = await openTab("Correct");

    // title: a different XPath. price: confirmed as it is. sku: a first step, with a post operation.
    const title = form.getByRole("group", { name: "title" });
    const xpath = within(title).getByRole("textbox", { name: "XPath" });
    await replaceText(xpath, "//main//h1");
    await userEvent.click(
      within(form.getByRole("group", { name: "price" })).getByRole("checkbox", {
        name: "Confirm the steps of price",
      }),
    );
    const sku = form.getByRole("group", { name: "sku" });
    await userEvent.click(within(sku).getByRole("button", { name: "Add step" }));
    await replaceText(within(sku).getByRole("textbox", { name: "XPath" }), "//span[@itemprop]");
    await userEvent.click(within(sku).getByRole("button", { name: "Add operation" }));
    await userEvent.click(form.getByRole("button", { name: "Submit correction" }));

    const result = await screen.findByRole("region", { name: "Correction result" });
    expect(calls.find((call) => call.method === "PUT")).toMatchObject({
      path: `/v1/configs/${V2_ID}`,
      body: {
        fields: {
          title: { steps: [{ xpath: "//main//h1", post: [{ trim: {} }] }] },
          sku: { steps: [{ xpath: "//span[@itemprop]", post: [{ trim: {} }] }] },
        },
        confirm: ["price"],
      },
    });
    expect(within(result).getByText("Saved as version 3, active.")).toBeInTheDocument();
    expect(within(result).getByRole("link", { name: "Open version 3" })).toHaveAttribute(
      "href",
      `/configs/${V3_ID}`,
    );
    expect(within(result).getByRole("grid", { name: "Field validation" })).toBeInTheDocument();
  });

  it("lists the new version beside the others after a correction", async () => {
    let versions = [v1, v2];
    configApi({
      [`GET /v1/sites/${HOST}/configs`]: () => Response.json({ items: versions }),
      [`PUT /v1/configs/${V2_ID}`]: () => {
        versions = [v1, { ...v2, status: "suspended" }, corrected];
        return Response.json(corrected);
      },
    });
    await open(`/configs/${V2_ID}`, HOST);
    const form = await openTab("Correct");

    await userEvent.click(
      within(form.getByRole("group", { name: "price" })).getByRole("checkbox", {
        name: "Confirm the steps of price",
      }),
    );
    await userEvent.click(form.getByRole("button", { name: "Submit correction" }));
    await screen.findByRole("region", { name: "Correction result" });

    const list = await openTab("Versions");
    expect(rowsOf(list.getByRole("grid", { name: "Versions" }))).toEqual([
      "item_detail version 2detail1suspendedinducedNo fields",
      "item_detail version 2detail2suspendedinduced1 corroborated, 1 uncorroborated",
      "item_detail version 2detail3activeoperator3 operator",
    ]);
  });

  it("sends a stored normalize operation in the form the server reads: keyed by its field type", async () => {
    const calls = configApi({ [`PUT /v1/configs/${V2_ID}`]: json(corrected) });
    await open(`/configs/${V2_ID}`, HOST);
    const form = await openTab("Correct");

    const path = within(form.getByRole("group", { name: "price" })).getByRole("textbox", {
      name: "JSON-LD path",
    });
    await replaceText(path, "$.offers.lowPrice");
    await userEvent.click(form.getByRole("button", { name: "Submit correction" }));

    await screen.findByRole("region", { name: "Correction result" });
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({
      fields: {
        price: {
          steps: [{ jsonld: "$.offers.lowPrice", when_type: "Product", post: [{ money: {} }] }],
        },
      },
      confirm: [],
    });
  });

  it("removes a field whose steps were all removed", async () => {
    const calls = configApi({ [`PUT /v1/configs/${V2_ID}`]: json(corrected) });
    await open(`/configs/${V2_ID}`, HOST);
    const form = await openTab("Correct");

    const price = form.getByRole("group", { name: "price" });
    await userEvent.click(within(price).getByRole("button", { name: "Remove step 1" }));
    await userEvent.click(form.getByRole("button", { name: "Submit correction" }));

    await screen.findByRole("region", { name: "Correction result" });
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({
      fields: { price: null },
      confirm: [],
    });
  });

  it("shows the server's reasons next to the field they name", async () => {
    configApi({
      [`PUT /v1/configs/${V2_ID}`]: () =>
        problem(422, {
          title: "Unprocessable",
          detail: "the correction does not fit the config",
          errors: [{ field: "fields.title.steps.0.xpath", reason: "not an XPath 1.0 expression" }],
        }),
    });
    await open(`/configs/${V2_ID}`, HOST);
    const form = await openTab("Correct");

    const xpath = within(form.getByRole("group", { name: "title" })).getByRole("textbox", {
      name: "XPath",
    });
    // `[[` types one "[" (user-event key descriptors).
    await userEvent.type(xpath, "[[");
    await userEvent.click(form.getByRole("button", { name: "Submit correction" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "the correction does not fit the config",
    );
    expect(
      within(form.getByRole("group", { name: "title" })).getByText(
        "fields.title.steps.0.xpath: not an XPath 1.0 expression",
      ),
    ).toBeInTheDocument();
    expect(
      within(form.getByRole("group", { name: "price" })).queryByText(/not an XPath/),
    ).not.toBeInTheDocument();
  });
});

describe("config screen: learn and export", () => {
  it("starts learning for the config's schema version, and forces it after a refusal", async () => {
    let refused = true;
    const calls = configApi({
      [`POST /v1/sites/${HOST}/learn`]: () => {
        if (!refused) return Response.json({ job_id: JOB_ID }, { status: 202 });
        refused = false;
        return problem(409, { title: "Conflict", detail: "the site has an active config" });
      },
    });
    await open(`/configs/${V2_ID}`, HOST);

    await userEvent.click(screen.getByRole("button", { name: "Learn now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("the site has an active config");
    await userEvent.click(screen.getByRole("button", { name: "Learn anyway" }));

    expect(await screen.findByText(`Learning started as job ${JOB_ID}.`)).toBeInTheDocument();
    expect(calls.filter((call) => call.method === "POST").map((call) => call.body)).toEqual([
      { schema_id: SCHEMA_ID, force: false },
      { schema_id: SCHEMA_ID, force: true },
    ]);
  });

  it("saves the export as a file and shows the release report with manual fields marked", async () => {
    const saved: Blob[] = [];
    // jsdom has no object URLs; the file's content is what was handed to one.
    Object.assign(URL, {
      createObjectURL: (blob: Blob) => {
        saved.push(blob);
        return "blob:export";
      },
      revokeObjectURL: () => undefined,
    });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const draft = { site: HOST, fields: {}, listing: null };
    const calls = configApi({
      [`POST /v1/configs/${V2_ID}/export`]: json({
        format: "platform_draft",
        export: draft,
        release: {
          held_out: HELD_OUT,
          fields: {
            title: { published: 2, reproduced: 2, manual: false },
            price: { published: 2, reproduced: 1, manual: true },
          },
          listing: null,
        },
      }),
    });
    await open(`/configs/${V2_ID}`, HOST);
    const panel = await openTab("Export");

    await userEvent.click(panel.getByRole("radio", { name: "Platform draft" }));
    await userEvent.click(panel.getByRole("button", { name: "Export" }));

    const release = await panel.findByRole("grid", { name: "Release report" });
    expect(rowsOf(release)).toEqual(["titlereproduced2/2", "pricemanual1/2"]);
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      format: "platform_draft",
    });
    expect(click.mock.contexts[0]).toHaveProperty("download", `${HOST}-v2-platform_draft.json`);
    expect(JSON.parse((await saved[0]?.text()) ?? "null")).toEqual(draft);
  });
});
