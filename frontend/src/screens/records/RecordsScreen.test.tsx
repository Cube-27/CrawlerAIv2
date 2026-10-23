import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { routes } from "../../app/router";
import type { RecordPage, ReplayResult, StoredRecord } from "../../api/records";
import type { SchemaDef } from "../../api/schemas";
import { stubApi } from "../../test/api";
import { recordField } from "../../test/records";
import { fieldSpec } from "../../test/schemas";

const SCHEMA_ID = "0192a000-0000-7000-8000-000000000101";
const OTHER_SCHEMA_ID = "0192a000-0000-7000-8000-000000000102";
const CAPTURE_ID = "0192a000-0000-7000-8000-000000000501";
const RECORD_ID = "0192a000-0000-7000-8000-000000000601";
const RECORDS_PATH = `/records?schema_id=${SCHEMA_ID}`;
const REPLAY = `POST /v1/captures/${CAPTURE_ID}/replay`;

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

const otherSchema: SchemaDef = { ...schema, id: OTHER_SCHEMA_ID, name: "event_detail" };

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
    egress_country: null,
    egress_basis: "unknown",
    fields: { title: recordField({}), price: conflictPrice },
    ...overrides,
  };
}

const page =
  (items: StoredRecord[], next_cursor: string | null = null) =>
  () =>
    Response.json({ items, next_cursor, total: items.length } satisfies RecordPage);
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

async function openInspector() {
  const [row] = await recordRows();
  if (row === undefined) throw new Error("no record row");
  await userEvent.click(row);
  return within(await screen.findByRole("dialog"));
}

describe("records screen: the inspector", () => {
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
});
