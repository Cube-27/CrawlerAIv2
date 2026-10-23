import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { routes } from "../../app/router";
import type { CallDetail, CallList, CaptureResult, Endpoint } from "../../api/captures";
import type { ConfigSummary } from "../../api/configs";
import type { SchemaDef } from "../../api/schemas";
import { stubApi } from "../../test/api";
import { catchDownloads } from "../../test/downloads";
import { recordField } from "../../test/records";
import { fieldSpec } from "../../test/schemas";

const HOST = "shop.example.test";
const SCHEMA_ID = "0192a000-0000-7000-8000-000000000101";
const RECIPE_ID = "0192a000-0000-7000-8000-000000000501";
const REPAIR_ID = "0192a000-0000-7000-8000-000000000502";
const LEARNED_ID = "0192a000-0000-7000-8000-000000000503";
const CAPTURE_1 = "0192a000-0000-7000-8000-000000000701";
const CAPTURE_2 = "0192a000-0000-7000-8000-000000000702";

const schema: SchemaDef = {
  id: SCHEMA_ID,
  name: "item_detail",
  origin: "user",
  status: "active",
  page_kind: "detail",
  required_groups: [["title"]],
  field_order: ["title", "price"],
  labels: null,
  fields: {
    title: fieldSpec({ type: "text", required: true, scope: "row" }),
    price: fieldSpec({ type: "money", required: false, scope: "row" }),
  },
};

function summary(overrides: Partial<ConfigSummary>): ConfigSummary {
  return {
    id: RECIPE_ID,
    site: HOST,
    schema_id: SCHEMA_ID,
    page_kind: "detail",
    version: 3,
    status: "active",
    origin: "operator",
    field_status: { title: "operator" },
    validation_report: null,
    patterns: [`https://${HOST}/item/{id}`],
    custom: true,
    renders: [],
    sent_by: "http",
    drifting: ["price"],
    pending_repair: REPAIR_ID,
    ...overrides,
  };
}

function captured(captureId: string | null, url: string): CaptureResult {
  return {
    capture_id: captureId,
    url,
    outcome: captureId === null ? "blocked" : "extracted",
    reason: captureId === null ? "The site answered with a challenge." : null,
    attempts: [],
    records:
      captureId === null
        ? []
        : [
            {
              id: captureId,
              complete: true,
              confidence: 0.9,
              mode: "adhoc",
              fields: { title: recordField({ value: "Lamp" }) },
            },
          ],
  };
}

function endpoint(overrides: Partial<Endpoint>): Endpoint {
  return {
    method: "GET",
    origin: `https://${HOST}`,
    has_path: true,
    segments: 2,
    query: [],
    body_shape: null,
    rows: null,
    samples: [CAPTURE_1, CAPTURE_2],
    calls: [],
    fields: [],
    ...overrides,
  };
}

const call = (captureId: string, index: number, sameSite: boolean) => ({
  capture_id: captureId,
  index,
  status: 200,
  content_type: "application/json",
  size: 2048,
  resource_type: "fetch",
  same_site: sameSite,
  step: 0,
});

// The server's order is first called first; the screen puts the page's own site first.
const merged: CallList = {
  schema_id: SCHEMA_ID,
  samples: [CAPTURE_1, CAPTURE_2],
  endpoints: [
    endpoint({
      origin: "https://cdn.example.net",
      query: ["v"],
      samples: [CAPTURE_1],
      calls: [call(CAPTURE_1, 0, false)],
    }),
    endpoint({
      query: ["id"],
      calls: [call(CAPTURE_1, 1, true), call(CAPTURE_2, 0, true)],
      fields: [
        {
          field: "price",
          published: true,
          in_text: 0,
          paths: [{ path: "$.data.price", samples: 2 }],
        },
      ],
    }),
  ],
};

const detail: CallDetail = {
  index: 1,
  url: `https://${HOST}/api/item?id=1`,
  method: "GET",
  status: 200,
  content_type: "application/json",
  size: 2048,
  resource_type: "fetch",
  same_site: true,
  step: 0,
  guard_prefix: null,
  request_headers: [["accept", "application/json"]],
  request_body: null,
  response_headers: [["content-type", "application/json"]],
  answer: '{"data":{"price":12.5}}',
};

const json = (body: unknown) => () => Response.json(body);

async function open(path: string, heading: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
  await screen.findByRole("heading", { level: 1, name: heading });
}

async function captureSample(url: string) {
  const field = screen.getByRole("textbox", { name: /Sample URL/ });
  await userEvent.clear(field);
  await userEvent.type(field, url);
  await userEvent.click(screen.getByRole("button", { name: "Capture" }));
}

describe("recipes screen", () => {
  it("lists the site's serving recipes with their patterns, drift and pending repair", async () => {
    stubApi({
      [`GET /v1/sites/${HOST}/configs`]: json({
        items: [
          summary({}),
          summary({ id: REPAIR_ID, version: 4, status: "pending_approval" }),
          summary({ id: LEARNED_ID, custom: false, origin: "induced", patterns: [] }),
        ],
      }),
      "GET /v1/schemas": json({ items: [schema] }),
    });
    await open(`/sites/${HOST}`, HOST);
    await userEvent.click(screen.getByRole("link", { name: "Recipes" }));
    await screen.findByRole("heading", { level: 1, name: `Recipes of ${HOST}` });

    const table = screen.getByRole("grid", { name: "Recipes" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    const [row] = rows;
    expect(row).toHaveTextContent(`https://${HOST}/item/{id}`);
    expect(row).toHaveTextContent("price");
    expect(await within(table).findByText("item_detail")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Review the repair" })).toHaveAttribute(
      "href",
      `/configs/${REPAIR_ID}`,
    );
  });

  it("builds from samples: captures each, lists their calls by endpoint, opens one, picks the main call", async () => {
    let captures = 0;
    const replies = [
      captured(null, `https://${HOST}/item/1`),
      captured(CAPTURE_1, `https://${HOST}/item/1`),
      captured(CAPTURE_2, `https://${HOST}/item/2`),
    ];
    const calls = stubApi({
      "GET /v1/schemas": json({ items: [schema] }),
      "POST /v1/captures": () => Response.json(replies[captures++]),
      [`GET /v1/captures/${CAPTURE_1}/calls`]: json({
        ...merged,
        samples: [CAPTURE_1],
        endpoints: [],
      }),
      "POST /v1/recipes/calls": json(merged),
      [`GET /v1/captures/${CAPTURE_1}/calls/1`]: json(detail),
      [`GET /v1/captures/${CAPTURE_1}/calls.har`]: json({ log: { version: "1.2" } }),
    });
    const saved = catchDownloads();
    await open(`/sites/${HOST}/recipes/new`, `New recipe for ${HOST}`);

    await userEvent.click(screen.getByRole("button", { name: /Schema/ }));
    await userEvent.click(await screen.findByRole("option", { name: "item_detail" }));

    // A capture that stored nothing says why and is not a sample.
    await captureSample(`https://${HOST}/item/1`);
    expect(await screen.findByText("The site answered with a challenge.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Capture" }));
    expect(await screen.findByText("No calls")).toBeInTheDocument();
    await captureSample(`https://${HOST}/item/2`);

    const samples = await screen.findByRole("list", { name: "Samples" });
    await within(samples).findByText(`2. https://${HOST}/item/2`);
    expect(calls.filter(({ method }) => method === "POST")).toMatchObject([
      { path: "/v1/captures", body: { url: `https://${HOST}/item/1`, page_kind: "detail" } },
      { path: "/v1/captures", body: { url: `https://${HOST}/item/1`, schema_id: SCHEMA_ID } },
      { path: "/v1/captures", body: { url: `https://${HOST}/item/2` } },
      { path: "/v1/recipes/calls", body: { capture_ids: [CAPTURE_1, CAPTURE_2] } },
    ]);

    // The page's own site first, each group with where it carries the fields.
    const pick = await screen.findAllByRole("button", { name: /as the main call/ });
    expect(pick.map((button) => button.getAttribute("aria-label"))).toEqual([
      `Use GET https://${HOST}/{2 segments}?id as the main call`,
      "Use GET https://cdn.example.net/{2 segments}?v as the main call",
    ]);
    expect(screen.getByText("price at $.data.price on 2 of 2")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Open call 1" }));
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText("accept")).toBeInTheDocument();
    expect(within(drawer).getByText(`GET https://${HOST}/api/item?id=1`)).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Download HAR" }));
    await expect.poll(() => saved.map(({ name }) => name)).toEqual([`capture-${CAPTURE_1}.har`]);
    await userEvent.keyboard("{Escape}");

    const [own] = pick;
    if (own === undefined) throw new Error("no endpoint group");
    await userEvent.click(own);
    const main = screen.getByRole("list", { name: "Main call fields" });
    expect(main).toHaveTextContent("price at $.data.price on 2 of 2");
  });
});
