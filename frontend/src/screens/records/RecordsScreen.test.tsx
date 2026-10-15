import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { routes } from "../../app/router";
import type { ExtractedRecord, RecordPage, ReplayResult, StoredRecord } from "../../api/records";
import type { SchemaDef } from "../../api/schemas";
import { problem, stubApi } from "../../test/api";
import { recordField } from "../../test/records";

const SCHEMA_ID = "0192a000-0000-7000-8000-000000000101";
const OTHER_SCHEMA_ID = "0192a000-0000-7000-8000-000000000102";
const CAPTURE_ID = "0192a000-0000-7000-8000-000000000501";
const RECORD_ID = "0192a000-0000-7000-8000-000000000601";
const SECOND_ID = "0192a000-0000-7000-8000-000000000602";
const RECORDS_PATH = `/records?schema_id=${SCHEMA_ID}`;
const REPLAY = `POST /v1/captures/${CAPTURE_ID}/replay`;

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
  },
};

const otherSchema: SchemaDef = { ...schema, id: OTHER_SCHEMA_ID, name: "event_detail", version: 1 };

const conflictPrice = recordField({
  value: null,
  status: "conflict",
  reason: "disagree",
  evidence: null,
  confidence: 0.41,
  calibrated: false,
  source_kind: null,
  locator: null,
});

function storedRecord(overrides: Partial<StoredRecord> = {}): StoredRecord {
  return {
    id: RECORD_ID,
    capture_id: CAPTURE_ID,
    schema_id: SCHEMA_ID,
    version: 3,
    changed_fields: ["price"],
    mode: "adhoc",
    complete: false,
    confidence: 0.8,
    fields: { title: recordField({}), price: conflictPrice },
    ...overrides,
  };
}

const page =
  (items: StoredRecord[], next_cursor: string | null = null) =>
  () =>
    Response.json({ items, next_cursor } satisfies RecordPage);
const schemaReply = () => Response.json(schema);
const schemaList = () => Response.json({ items: [schema, otherSchema] });
const replayReply = (result: ReplayResult) => () => Response.json(result);

async function open(path: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
  await screen.findByRole("heading", { level: 1, name: "Records" });
}

async function recordRows() {
  const table = await screen.findByRole("grid", { name: "Records" });
  return within(table).getAllByRole("row").slice(1);
}

// One segment of the changed-since field: month, day, year, hour or minute.
function changedSince(part: string) {
  return screen.getByRole("spinbutton", { name: new RegExp(`^${part}, Changed since`) });
}

function recordQueries(calls: readonly { path: string; query: string }[]) {
  return calls.filter(({ path }) => path === "/v1/records").map(({ query }) => query);
}

async function openInspector() {
  const [row] = await recordRows();
  if (row === undefined) throw new Error("no record row");
  await userEvent.click(row);
  return within(await screen.findByRole("dialog"));
}

describe("records screen: the list", () => {
  it("is in the main navigation", async () => {
    stubApi({ "GET /v1/schemas": schemaList });
    await open("/records");

    expect(
      within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", {
        name: "Records",
      }),
    ).toHaveAttribute("href", "/records");
  });

  it("asks for a schema before it lists anything", async () => {
    const calls = stubApi({ "GET /v1/schemas": schemaList });
    await open("/records");

    expect(await screen.findByText("Choose a schema")).toBeInTheDocument();
    await waitFor(() => {
      expect(calls.map(({ method, path }) => `${method} ${path}`)).toEqual(["GET /v1/schemas"]);
    });
  });

  it("sends the chosen schema, job and site as filters, and leaves an empty one out", async () => {
    const calls = stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
    });
    await open("/records");

    await userEvent.click(screen.getByRole("button", { name: /Schema/ }));
    await userEvent.click(await screen.findByRole("option", { name: "item_detail version 2" }));
    await userEvent.type(screen.getByLabelText("Site"), "shop.example.test");
    await userEvent.click(screen.getByRole("button", { name: "Show records" }));

    await recordRows();
    expect(calls.filter(({ path }) => path === "/v1/records")).toEqual([
      {
        method: "GET",
        path: "/v1/records",
        query: `schema_id=${SCHEMA_ID}&site=shop.example.test&limit=20`,
        authorization: null,
        body: null,
      },
    ]);
  });

  it("shows a column per schema field, then mode, version and confidence", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([
        storedRecord(),
        storedRecord({
          id: SECOND_ID,
          version: 1,
          changed_fields: [],
          confidence: null,
          fields: {
            title: recordField({ value: "Red kettle" }),
            price: recordField({ value: { amount: "19.90", currency: "EUR" } }),
          },
        }),
      ]),
    });
    await open(RECORDS_PATH);

    const table = await screen.findByRole("grid", { name: "Records" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["title", "price", "Mode", "Version", "Changed", "Confidence"]);
    const [, second] = await recordRows();
    expect(second?.textContent).toBe("Red kettle19.90 EURadhoc1——");
  });

  it("renders a conflict field as — with its reason and status, and no value", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
    });
    await open(RECORDS_PATH);

    const [row] = await recordRows();
    // The first column, title, is the row header; price is the first grid cell.
    const [cell] = within(row ?? document.body).getAllByRole("gridcell");
    const price = within(cell ?? document.body);
    expect(price.getByLabelText("No value: disagree")).toHaveTextContent("—");
    expect(price.getByText("conflict")).toBeInTheDocument();
    expect(cell?.textContent).toBe("—conflict");
  });

  it("pages forward with the cursor the API returned, and back to the first page, read again", async () => {
    const calls = stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": () => {
        const last = calls.at(-1);
        return last?.query.includes("cursor=c2") === true
          ? page([
              storedRecord({
                id: SECOND_ID,
                fields: { title: recordField({ value: "Red kettle" }) },
              }),
            ])()
          : page([storedRecord()], "c2")();
      },
    });
    await open(RECORDS_PATH);
    await recordRows();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Red kettle")).toBeInTheDocument();
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("Page 1")).toBeInTheDocument();
    expect(calls.filter(({ path }) => path === "/v1/records").map(({ query }) => query)).toEqual([
      `schema_id=${SCHEMA_ID}&limit=20`,
      `schema_id=${SCHEMA_ID}&cursor=c2&limit=20`,
      `schema_id=${SCHEMA_ID}&limit=20`,
    ]);
  });

  it("names the fields that changed from the version a record supersedes", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([
        storedRecord({ changed_fields: ["title", "price"] }),
        storedRecord({ id: SECOND_ID, version: 1, changed_fields: [] }),
      ]),
    });
    await open(RECORDS_PATH);

    const [changed, first] = await recordRows();
    const changedCells = within(changed ?? document.body).getAllByRole("gridcell");
    expect(changedCells.at(-2)?.textContent).toBe("title, price");
    const firstCells = within(first ?? document.body).getAllByRole("gridcell");
    expect(firstCells.at(-2)?.textContent).toBe("—");
  });

  it("sends the changed-since time, entered in UTC, as an ISO 8601 instant", async () => {
    const calls = stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
    });
    await open(RECORDS_PATH);
    await recordRows();

    await userEvent.type(changedSince("month"), "100120260930");
    await userEvent.click(screen.getByRole("button", { name: "Show records" }));

    await waitFor(() => {
      expect(recordQueries(calls)).toEqual([
        `schema_id=${SCHEMA_ID}&limit=20`,
        `schema_id=${SCHEMA_ID}&changed_since=2026-10-01T09%3A30%3A00.000Z&limit=20`,
      ]);
    });
  });

  it("reads the changed-since time from the address, and clears it", async () => {
    const calls = stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
    });
    await open(`${RECORDS_PATH}&changed_since=2026-10-01T09:30:00.000Z`);
    await recordRows();

    const parts = ["month", "day", "year", "hour", "minute"];
    expect(parts.map((part) => changedSince(part).getAttribute("aria-valuenow"))).toEqual([
      "10",
      "1",
      "2026",
      "9",
      "30",
    ]);

    await userEvent.click(screen.getByRole("button", { name: "Clear changed since" }));
    await userEvent.click(screen.getByRole("button", { name: "Show records" }));

    await waitFor(() => {
      expect(recordQueries(calls)).toEqual([
        `schema_id=${SCHEMA_ID}&changed_since=2026-10-01T09%3A30%3A00.000Z&limit=20`,
        `schema_id=${SCHEMA_ID}&limit=20`,
      ]);
    });
  });

  it("keeps its column widths fixed and truncates long values, so paging moves no column", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
    });
    await open(RECORDS_PATH);

    const table = await screen.findByRole("grid", { name: "Records" });
    expect(table).toHaveClass("table-fixed");
    for (const cell of within(table).getAllByRole("gridcell")) expect(cell).toHaveClass("truncate");
  });

  it("says when no record matches", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([]),
    });
    await open(RECORDS_PATH);

    expect(await screen.findByText("No record matches these filters.")).toBeInTheDocument();
  });

  it("shows the problem when the records can't be listed", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": () =>
        problem(422, { title: "Invalid filter", detail: "job_id is not a UUID." }),
    });
    await open(`${RECORDS_PATH}&job_id=nope`);

    expect(await screen.findByText("Invalid filter")).toBeInTheDocument();
    expect(screen.getByText("job_id is not a UUID.")).toBeInTheDocument();
  });

  it("opens a record from the keyboard", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
    });
    await open(RECORDS_PATH);
    await recordRows();

    // Tab past the form to the table, then move down from the header row to the first record.
    const table = screen.getByRole("grid", { name: "Records" });
    while (!table.contains(document.activeElement)) await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}{Enter}");

    expect(await screen.findByRole("heading", { name: "Record version 3" })).toBeInTheDocument();
  });
});

describe("records screen: the inspector", () => {
  it("shows every field_meta attribute and the capture id", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
    });
    await open(RECORDS_PATH);

    const inspector = await openInspector();
    expect(inspector.getByRole("heading", { name: "Record version 3" })).toBeInTheDocument();
    expect(inspector.getByText("incomplete")).toBeInTheDocument();
    expect(inspector.getByText(CAPTURE_ID)).toBeInTheDocument();
    const fields = within(inspector.getByRole("grid", { name: "Record fields" }));
    expect(fields.getByRole("row", { name: /title/ }).textContent).toBe(
      "titleBlue kettlepublished0.97structuredjsonldjsonld:0:$.name—",
    );
    const price = within(fields.getByRole("row", { name: /price/ }));
    expect(price.getByText("uncalibrated")).toBeInTheDocument();
    expect(price.getAllByText("conflict")).toHaveLength(2);
    expect(price.getByText("0.41")).toBeInTheDocument();
  });

  it.each([
    [storedRecord(), "Changed from version 2: price"],
    [storedRecord({ version: 1, changed_fields: [] }), "The first version of this record."],
    [storedRecord({ changed_fields: [] }), "No published value changed from version 2."],
  ])("says what changed from the version the record supersedes", async (record, text) => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([record]),
    });
    await open(RECORDS_PATH);

    const inspector = await openInspector();
    expect(inspector.getByText(text)).toBeInTheDocument();
  });

  it("offers no replay once the record's capture expired", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord({ capture_id: null })]),
    });
    await open(RECORDS_PATH);

    const inspector = await openInspector();
    expect(inspector.getByText(/capture this record came from has expired/)).toBeInTheDocument();
    expect(inspector.queryByRole("button", { name: "Replay" })).not.toBeInTheDocument();
  });

  it("replays the capture and marks each field changed or same against the stored record", async () => {
    const calls = stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
      [REPLAY]: replayReply({
        records: [
          {
            mode: "adhoc",
            complete: true,
            confidence: 0.9,
            fields: {
              title: recordField({ confidence: 0.5 }),
              price: recordField({ value: { amount: "21.00", currency: "EUR" } }),
            },
          },
        ],
      }),
    });
    await open(RECORDS_PATH);
    const inspector = await openInspector();

    await userEvent.click(inspector.getByRole("button", { name: "Replay" }));

    const diff = within(await inspector.findByRole("grid", { name: "Replay differences" }));
    expect(diff.getByRole("row", { name: /title/ }).textContent).toBe(
      "titleBlue kettleBlue kettlesame",
    );
    expect(diff.getByRole("row", { name: /price/ }).textContent).toBe(
      "price—conflict21.00 EURchanged",
    );
    expect(calls.filter(({ method }) => method === "POST")).toEqual([
      {
        method: "POST",
        path: `/v1/captures/${CAPTURE_ID}/replay`,
        query: "",
        authorization: null,
        body: { allow_llm: false },
      },
    ]);
  });

  it("lists the replay's records without a diff when it made several", async () => {
    const replayed: ExtractedRecord = {
      mode: "adhoc",
      complete: true,
      confidence: 0.9,
      fields: { title: recordField({ value: "Red kettle" }) },
    };
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
      [REPLAY]: replayReply({
        records: [replayed, { ...replayed, complete: false }],
      }),
    });
    await open(RECORDS_PATH);
    const inspector = await openInspector();

    await userEvent.click(inspector.getByRole("button", { name: "Replay" }));

    expect(
      await inspector.findByText(/The replay extracted 2 records from the capture/),
    ).toBeInTheDocument();
    expect(inspector.getByRole("grid", { name: "Record 2 fields" })).toBeInTheDocument();
    expect(inspector.queryByRole("grid", { name: "Replay differences" })).toBeNull();
  });

  it("shows the problem when the replay fails", async () => {
    stubApi({
      "GET /v1/schemas": schemaList,
      [`GET /v1/schemas/${SCHEMA_ID}`]: schemaReply,
      "GET /v1/records": page([storedRecord()]),
      [REPLAY]: () => problem(404, { title: "Capture not found", detail: "Its bytes expired." }),
    });
    await open(RECORDS_PATH);
    const inspector = await openInspector();

    await userEvent.click(inspector.getByRole("button", { name: "Replay" }));

    expect(await inspector.findByText("Capture not found")).toBeInTheDocument();
    expect(inspector.getByText("Its bytes expired.")).toBeInTheDocument();
  });
});
