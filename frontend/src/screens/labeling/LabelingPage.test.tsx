import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vite-plus/test";
import { routes } from "../../app/router";
import type { components } from "../../api/schema";

// These tests type into many fields with user-event, which is slow in jsdom; the default 5 s is too tight on a
// loaded machine.
vi.setConfig({ testTimeout: 20_000 });

type PageDetail = components["schemas"]["PageDetail"];
type Labels = components["schemas"]["Labels"];

const PAGE_ID = "0192a000-0000-7000-8000-000000000001";
const ETAG = '"etag-1"';

function detailPage(overrides: Partial<PageDetail> = {}): PageDetail {
  return {
    id: PAGE_ID,
    capture_id: "0192a000-0000-7000-8000-0000000000c1",
    split: "dev",
    schema_name: "item_detail",
    page_kind: "detail",
    category: "custom_store",
    status: null,
    labeler: null,
    checker: null,
    labels: null,
    fields: { title: { type: "text", scope: "row" }, price: { type: "money", scope: "row" } },
    url: "https://store.test/items/1",
    final_url: "https://store.test/items/1",
    bundle_html: "<html><head></head><body><h1>Blue mug</h1><p>EUR 19.90</p></body></html>",
    text: null,
    ...overrides,
  };
}

const labeled: Labels = {
  label_version: 1,
  status: "labeled",
  labeler: "ana",
  checker: null,
  prefill_source: null,
  fields: {
    title: { value: "Blue mug", absent: false, locator: "xpath://h1", distractors: [] },
    price: { value: null, absent: true, locator: null, distractors: [] },
  },
  rows: [],
  notes: "",
};

interface Call {
  method: string;
  path: string;
  ifMatch: string | null;
  body: unknown;
}

type Reply = Response | (() => Response);

/** Stubs `fetch` with one reply per `METHOD /path`, the last reply repeating; records every request. */
function stubApi(replies: Record<string, Reply[]>): Call[] {
  const calls: Call[] = [];
  const served: Record<string, number> = {};
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    const key = `${request.method} ${path}`;
    const text = await request.text();
    calls.push({
      method: request.method,
      path,
      ifMatch: request.headers.get("If-Match"),
      body: text === "" ? null : (JSON.parse(text) as unknown),
    });
    const list = replies[key];
    if (list === undefined) throw new Error(`unexpected ${key}`);
    const n = served[key] ?? 0;
    served[key] = n + 1;
    const reply = list[Math.min(n, list.length - 1)];
    if (reply === undefined) throw new Error(`unexpected ${key}`);
    return typeof reply === "function" ? reply() : reply.clone();
  });
  return calls;
}

function json(body: unknown, init: ResponseInit = {}): Response {
  return Response.json(body, init);
}

function problem(status: number, type: string, errors: { field: string; reason: string }[] = []) {
  return new Response(JSON.stringify({ type, title: type, status, detail: type, errors }), {
    status,
    headers: { "content-type": "application/problem+json" },
  });
}

function pageReply(page: PageDetail, etag = ETAG): Response {
  return json(page, { headers: { ETag: etag } });
}

function renderAt(path: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

async function field(group: string) {
  return within(await screen.findByRole("group", { name: group }));
}

function puts(calls: Call[]): Call[] {
  return calls.filter((call) => call.method === "PUT");
}

describe("labeling list", () => {
  it("lists the dev pages with their status and links each to its labeling view", async () => {
    stubApi({
      "GET /v1/eval/pages": [
        json([
          {
            id: PAGE_ID,
            capture_id: "0192a000-0000-7000-8000-0000000000c1",
            split: "dev",
            schema_name: "item_detail",
            page_kind: "detail",
            category: "custom_store",
            status: "labeled",
            labeler: "ana",
            checker: null,
          },
        ]),
      ],
    });
    renderAt("/labeling");

    const row = await screen.findByRole("row", { name: new RegExp(PAGE_ID) });

    expect(within(row).getByText("labeled")).toBeInTheDocument();
    expect(within(row).getByText("ana")).toBeInTheDocument();
    expect(screen.getByText("Split: dev")).toBeInTheDocument();
  });

  it("says how to turn the labeling API on when its routes are not mounted", async () => {
    stubApi({ "GET /v1/eval/pages": [json({ detail: "Not Found" }, { status: 404 })] });
    renderAt("/labeling");

    expect(await screen.findByText(/The labeling API is off/)).toHaveTextContent(
      "CRAWLERAI_EVAL_UI=true",
    );
  });
});

describe("labeler pass", () => {
  it("stores the labels with the page's ETag and shows the stored pass", async () => {
    const calls = stubApi({
      [`GET /v1/eval/pages/${PAGE_ID}`]: [
        pageReply(detailPage()),
        pageReply(detailPage({ status: "labeled", labeler: "ana", labels: labeled }), '"etag-2"'),
      ],
      [`PUT /v1/eval/pages/${PAGE_ID}/labels`]: [json({}, { headers: { ETag: '"etag-2"' } })],
    });
    renderAt(`/labeling/${PAGE_ID}`);
    const title = await field("title");
    const price = await field("price");

    await userEvent.type(screen.getByRole("textbox", { name: "Labeler name" }), "ana");
    await userEvent.type(title.getByRole("textbox", { name: "Value (JSON)" }), '"Blue mug"');
    await userEvent.type(title.getByRole("textbox", { name: "Locator" }), "xpath://h1");
    await userEvent.click(price.getByRole("checkbox", { name: "Absent from the page" }));
    await userEvent.click(screen.getByRole("button", { name: "Mark labeled" }));

    expect(await screen.findByText("Saved as labeled by ana.")).toBeInTheDocument();
    expect(puts(calls)).toEqual([
      {
        method: "PUT",
        path: `/v1/eval/pages/${PAGE_ID}/labels`,
        ifMatch: ETAG,
        body: labeled,
      },
    ]);
    const exported = await screen.findByRole("link", { name: "Export labels (JSON)" });
    expect(screen.getByText(/· labeled by ana/)).toBeInTheDocument();
    expect(exported).toHaveAttribute("download", `labels-${PAGE_ID}.json`);
    const href = exported.getAttribute("href") ?? "";
    expect(JSON.parse(decodeURIComponent(href.slice(href.indexOf(",") + 1)))).toEqual(labeled);
  });

  it("disables the value and locator of a field marked absent", async () => {
    stubApi({ [`GET /v1/eval/pages/${PAGE_ID}`]: [pageReply(detailPage())] });
    renderAt(`/labeling/${PAGE_ID}`);
    const price = await field("price");

    await userEvent.click(price.getByRole("checkbox", { name: "Absent from the page" }));

    expect(price.getByRole("textbox", { name: "Value (JSON)" })).toBeDisabled();
    expect(price.getByRole("textbox", { name: "Locator" })).toBeDisabled();
  });

  it("fills a value from /normalize and stores what it returned", async () => {
    const money = { amount: "19.90", currency: "EUR" };
    const calls = stubApi({
      [`GET /v1/eval/pages/${PAGE_ID}`]: [pageReply(detailPage())],
      [`POST /v1/eval/pages/${PAGE_ID}/normalize`]: [json({ value: money })],
      [`PUT /v1/eval/pages/${PAGE_ID}/labels`]: [json({})],
    });
    renderAt(`/labeling/${PAGE_ID}`);
    const price = await field("price");

    await userEvent.type(price.getByRole("textbox", { name: "Raw text" }), "EUR 19.90");
    await userEvent.click(price.getByRole("button", { name: "Normalize price" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Labeler name" }), "ana");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => {
      expect(puts(calls)).toHaveLength(1);
    });
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      field: "price",
      raw_text: "EUR 19.90",
    });
    expect(price.getByRole("textbox", { name: "Value (JSON)" })).toHaveValue(JSON.stringify(money));
    expect(price.getByText(`Normalized: ${JSON.stringify(money)}`)).toBeInTheDocument();
    expect(puts(calls)[0]?.body).toEqual(
      expect.objectContaining({
        status: "draft",
        fields: { price: { value: money, absent: false, locator: null, distractors: [] } },
      }),
    );
  });

  it("shows why /normalize declined", async () => {
    stubApi({
      [`GET /v1/eval/pages/${PAGE_ID}`]: [pageReply(detailPage())],
      [`POST /v1/eval/pages/${PAGE_ID}/normalize`]: [problem(501, "not_implemented")],
    });
    renderAt(`/labeling/${PAGE_ID}`);
    const price = await field("price");

    await userEvent.type(price.getByRole("textbox", { name: "Raw text" }), "EUR 19.90");
    await userEvent.click(price.getByRole("button", { name: "Normalize price" }));

    expect(await price.findByText("Not normalized: not_implemented")).toBeInTheDocument();
    expect(price.getByRole("textbox", { name: "Value (JSON)" })).toHaveValue("");
  });

  it("shows the API's validation errors at their fields and keeps the form", async () => {
    stubApi({
      [`GET /v1/eval/pages/${PAGE_ID}`]: [pageReply(detailPage())],
      [`PUT /v1/eval/pages/${PAGE_ID}/labels`]: [
        problem(422, "validation", [
          {
            field: "fields.price",
            reason: "not labeled; mark it absent if the page does not show it",
          },
          { field: "labeler", reason: "a labeler pass names its labeler" },
        ]),
      ],
    });
    renderAt(`/labeling/${PAGE_ID}`);
    const price = await field("price");

    await userEvent.type(screen.getByRole("textbox", { name: "Labeler name" }), "ana");
    await userEvent.click(screen.getByRole("button", { name: "Mark labeled" }));

    expect(
      await price.findByText("Error: not labeled; mark it absent if the page does not show it"),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "labeler: a labeler pass names its labeler",
    );
    expect(screen.getByRole("textbox", { name: "Labeler name" })).toHaveValue("ana");
  });

  it("names a value that is not JSON without calling the API", async () => {
    const calls = stubApi({ [`GET /v1/eval/pages/${PAGE_ID}`]: [pageReply(detailPage())] });
    renderAt(`/labeling/${PAGE_ID}`);
    const title = await field("title");

    await userEvent.type(screen.getByRole("textbox", { name: "Labeler name" }), "ana");
    await userEvent.type(title.getByRole("textbox", { name: "Value (JSON)" }), "Blue mug");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await title.findByText("Error: value: not a JSON value")).toBeInTheDocument();
    expect(puts(calls)).toEqual([]);
  });

  it("offers a reload when another pass was stored since the page was read", async () => {
    stubApi({
      [`GET /v1/eval/pages/${PAGE_ID}`]: [pageReply(detailPage())],
      [`PUT /v1/eval/pages/${PAGE_ID}/labels`]: [problem(412, "labels_changed")],
    });
    renderAt(`/labeling/${PAGE_ID}`);
    await field("title");

    await userEvent.type(screen.getByRole("textbox", { name: "Labeler name" }), "ana");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Another pass was saved since this page was opened.");
    expect(within(alert).getByRole("button", { name: "Reload the page" })).toBeInTheDocument();
  });

  it("fills the focused field's raw text and locator from a click on the page", async () => {
    stubApi({ [`GET /v1/eval/pages/${PAGE_ID}`]: [pageReply(detailPage())] });
    renderAt(`/labeling/${PAGE_ID}`);
    const price = await field("price");
    const frame = screen.getByTitle<HTMLIFrameElement>("Captured page");

    // jsdom does not render `srcdoc`, so the test puts the page in the frame and fires its load.
    const doc = frame.contentDocument;
    if (doc === null) throw new Error("the frame has no document");
    doc.body.innerHTML = "<h1>Blue mug</h1><p>EUR  19.90\n</p>";
    fireEvent.load(frame);
    await userEvent.click(price.getByRole("textbox", { name: "Raw text" }));
    const paragraph = doc.querySelector("p");
    if (paragraph === null) throw new Error("no paragraph");
    const followed = !fireEvent.click(paragraph);

    expect(price.getByRole("textbox", { name: "Raw text" })).toHaveValue("EUR 19.90");
    expect(price.getByRole("textbox", { name: "Locator" })).toHaveValue("xpath:/html/body/p");
    expect(followed).toBe(true); // the click's default action (following a link) was prevented
    expect(frame).toHaveAttribute("sandbox", "allow-same-origin");
  });
});

describe("checker pass", () => {
  it("cannot be confirmed by the labeler, under any casing", async () => {
    stubApi({
      [`GET /v1/eval/pages/${PAGE_ID}`]: [
        pageReply(detailPage({ status: "labeled", labeler: "ana", labels: labeled })),
      ],
    });
    renderAt(`/labeling/${PAGE_ID}`);
    await field("title");

    await userEvent.click(screen.getByRole("radio", { name: "Checker" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Checker name" }), "ANA");

    expect(screen.getByRole("button", { name: "Confirm check" })).toBeDisabled();
    expect(
      screen.getByText("The checker must be someone other than the labeler (ana)."),
    ).toBeInTheDocument();
  });

  it("cannot check a page that is not labeled yet", async () => {
    stubApi({ [`GET /v1/eval/pages/${PAGE_ID}`]: [pageReply(detailPage())] });
    renderAt(`/labeling/${PAGE_ID}`);
    await field("title");

    await userEvent.click(screen.getByRole("radio", { name: "Checker" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Checker name" }), "ben");

    expect(screen.getByRole("button", { name: "Confirm check" })).toBeDisabled();
    expect(screen.getByText("Only a labeled page can be checked.")).toBeInTheDocument();
  });

  it("confirms the labeler's values under a different name", async () => {
    const calls = stubApi({
      [`GET /v1/eval/pages/${PAGE_ID}`]: [
        pageReply(detailPage({ status: "labeled", labeler: "ana", labels: labeled })),
      ],
      [`PUT /v1/eval/pages/${PAGE_ID}/labels`]: [json({})],
    });
    renderAt(`/labeling/${PAGE_ID}`);
    const title = await field("title");

    expect(title.getByRole("textbox", { name: "Value (JSON)" })).toHaveValue('"Blue mug"');
    await userEvent.click(screen.getByRole("radio", { name: "Checker" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Checker name" }), "ben");
    await userEvent.click(screen.getByRole("button", { name: "Confirm check" }));

    expect(await screen.findByText("Checked by ben.")).toBeInTheDocument();
    expect(puts(calls).map((call) => call.body)).toEqual([
      { ...labeled, status: "checked", checker: "ben" },
    ]);
  });
});

describe("listing pages", () => {
  it("label page fields once and row fields per row, with rows added and removed", async () => {
    const calls = stubApi({
      [`GET /v1/eval/pages/${PAGE_ID}`]: [
        pageReply(
          detailPage({
            page_kind: "listing",
            fields: {
              title: { type: "text", scope: "row" },
              total: { type: "text", scope: "page" },
            },
          }),
        ),
      ],
      [`PUT /v1/eval/pages/${PAGE_ID}/labels`]: [json({})],
    });
    renderAt(`/labeling/${PAGE_ID}`);
    const total = await field("total");

    await userEvent.click(total.getByRole("checkbox", { name: "Absent from the page" }));
    await userEvent.click(screen.getByRole("button", { name: "Add row" }));
    await userEvent.click(screen.getByRole("button", { name: "Add row" }));
    await userEvent.type(
      (await field("row 2 title")).getByRole("textbox", { name: "Value (JSON)" }),
      '"Cup"',
    );
    await userEvent.click(screen.getByRole("button", { name: "Remove row 1" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Labeler name" }), "ana");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => {
      expect(puts(calls)).toHaveLength(1);
    });
    expect(screen.queryByRole("group", { name: "title" })).not.toBeInTheDocument();
    expect(puts(calls)[0]?.body).toEqual(
      expect.objectContaining({
        fields: { total: { value: null, absent: true, locator: null, distractors: [] } },
        rows: [
          { fields: { title: { value: "Cup", absent: false, locator: null, distractors: [] } } },
        ],
      }),
    );
  });
});
