import { Toast } from "@heroui/react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vite-plus/test";
import type { FieldStatus } from "../api/field";
import { ConfidenceCell } from "./ConfidenceCell";
import { FieldStatusBadge } from "./FieldStatusBadge";
import { FieldValue } from "./FieldValue";
import { LocatorText } from "./LocatorText";
import { RecordFieldsTable, RecordSummary } from "./RecordFields";
import { recordField } from "../test/records";

describe("FieldStatusBadge", () => {
  it.each<FieldStatus>(["published", "missing", "conflict", "abstained"])(
    "shows %s as text with an icon",
    (status) => {
      const { container } = render(<FieldStatusBadge status={status} />);

      expect(screen.getByText(status)).toBeInTheDocument();
      expect(container.querySelector("svg[aria-hidden='true']")).not.toBeNull();
    },
  );
});

describe("FieldValue", () => {
  it.each([
    [["blue", "mug"], '["blue","mug"]'],
    [{ amount: "19.90", currency: "EUR" }, '{"amount":"19.90","currency":"EUR"}'],
    ["Blue mug", "Blue mug"],
  ])("shows a published value of unknown type as the server sent it: %j", (value, text) => {
    render(<FieldValue field={{ status: "published", reason: null, value }} spec={null} />);

    expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.queryByLabelText(/No value/)).not.toBeInTheDocument();
  });

  it("renders a conflict as an em dash with its reason and status, and no value", async () => {
    render(
      <FieldValue
        field={{ status: "conflict", reason: "disagree", value: "a value the server withheld" }}
        spec={{ type: "text" }}
      />,
    );

    const dash = screen.getByRole("button", { name: "No value: disagree" });
    expect(dash).toHaveTextContent("—");
    expect(screen.getByText("conflict")).toBeInTheDocument();
    expect(screen.queryByText("a value the server withheld")).not.toBeInTheDocument();

    await userEvent.tab();
    expect(dash).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("disagree");
  });

  it.each<FieldStatus>(["missing", "abstained"])(
    "renders %s as an em dash with its status",
    (status) => {
      render(<FieldValue field={{ status, reason: null, value: null }} spec={{ type: "money" }} />);

      expect(screen.getByRole("button", { name: "No value" })).toHaveTextContent("—");
      expect(screen.getByText(status)).toBeInTheDocument();
    },
  );

  it("renders a published empty string as an em dash, never as nothing", () => {
    render(
      <FieldValue
        field={{ status: "published", reason: null, value: "" }}
        spec={{ type: "text" }}
      />,
    );

    expect(screen.getByRole("button", { name: "No value" })).toHaveTextContent("—");
  });

  it.each([
    ["money", { type: "money" }, { amount: "19.90", currency: "EUR" }, "19.90 EUR"],
    [
      "location",
      { type: "location" },
      {
        text: "Springfield Central",
        locality: "Springfield",
        region: null,
        country: "ZZ",
        remote_flag: false,
      },
      "Springfield Central",
    ],
    [
      "location without its text",
      { type: "location" },
      { text: null, locality: "Springfield", region: null, country: "ZZ", remote_flag: false },
      "Springfield, ZZ",
    ],
    [
      "remote location",
      { type: "location" },
      { text: "Springfield", locality: null, region: null, country: null, remote_flag: true },
      "Springfield, remote",
    ],
    [
      "remote location without a place",
      { type: "location" },
      { text: null, locality: null, region: null, country: null, remote_flag: true },
      "remote",
    ],
    ["date", { type: "date" }, "2026-03-04", "2026-03-04"],
    ["identifier", { type: "identifier" }, "AB-12", "AB-12"],
    [
      "range",
      { type: "range" },
      { min: "10", max: "20", currency: "EUR", unit: null, period: "HOUR" },
      "10–20 EUR per HOUR",
    ],
    ["count", { type: "count" }, 5, "5"],
    ["decimal number", { type: "number" }, "4.50", "4.50"],
    ["number", { type: "text" }, 42, "42"],
  ] as const)("renders a published %s value", (_name, spec, value, text) => {
    const { container } = render(
      <FieldValue field={{ status: "published", reason: null, value }} spec={spec} />,
    );

    expect(container).toHaveTextContent(text);
  });

  it("renders a list as one chip per item, each by the item type", () => {
    render(
      <FieldValue
        field={{
          status: "published",
          reason: null,
          value: [
            { amount: "1.00", currency: "EUR" },
            { amount: "2.50", currency: "EUR" },
          ],
        }}
        spec={{ type: "list", item: { type: "money" } }}
      />,
    );

    expect(screen.getByText("1.00 EUR")).toBeInTheDocument();
    expect(screen.getByText("2.50 EUR")).toBeInTheDocument();
  });

  it("renders an object as its sub-fields, each by its type", () => {
    const { container } = render(
      <FieldValue
        field={{
          status: "published",
          reason: null,
          value: { name: "Widget", price: { amount: "5", currency: "EUR" } },
        }}
        spec={{ type: "object", fields: { name: { type: "text" }, price: { type: "money" } } }}
      />,
    );

    expect(container).toHaveTextContent("name: Widget; price: 5 EUR");
  });
});

describe("RecordFieldsTable", () => {
  it("shows a missing field's status once, in its Status column", () => {
    render(
      <RecordFieldsTable
        label="Fields"
        record={{
          complete: false,
          mode: "adhoc",
          confidence: null,
          fields: { price: recordField({ status: "missing", value: null }) },
        }}
        fieldTypes={{ price: { type: "money" } }}
      />,
    );

    expect(screen.getAllByText("missing")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "No value" })).toHaveTextContent("—");
  });
});

describe("ConfidenceCell", () => {
  it("shows the confidence with two decimals, never a bar or a badge", () => {
    const { container } = render(<ConfidenceCell confidence={0.456} />);

    expect(container).toHaveTextContent("0.46");
    expect(screen.queryByText("uncalibrated")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("shows an em dash when there is no confidence", () => {
    const { container } = render(<ConfidenceCell confidence={null} />);

    expect(container).toHaveTextContent("—");
  });
});

describe("one uncalibrated badge per record", () => {
  const uncalibrated = { calibrated: false, confidence: 0.4 };

  it("shows it once for a record with several uncalibrated published fields", () => {
    const record = {
      complete: true,
      mode: "adhoc" as const,
      confidence: null,
      fields: {
        title: recordField(uncalibrated),
        price: recordField(uncalibrated),
        brand: recordField(uncalibrated),
      },
    };
    render(
      <>
        <RecordSummary record={record} />
        <RecordFieldsTable label="Fields" record={record} fieldTypes={{}} />
      </>,
    );

    expect(screen.getAllByText("uncalibrated")).toHaveLength(1);
    expect(screen.getAllByText("0.40")).toHaveLength(3);
  });

  it("shows none when every published field is calibrated, even if an unpublished one is not", () => {
    const record = {
      complete: false,
      mode: "adhoc" as const,
      confidence: 0.97,
      fields: {
        title: recordField({}),
        brand: recordField({ status: "abstained", value: null, ...uncalibrated }),
      },
    };
    render(<RecordSummary record={record} />);

    expect(screen.queryByText("uncalibrated")).not.toBeInTheDocument();
  });
});

describe("evidence and source kind", () => {
  it.each([
    ["network", "xhr", "Page network call", "Network call"],
    ["adapter", "adapter", "Platform API", "Platform API"],
    ["structured", "jsonld", "Structured data", "JSON-LD"],
  ] as const)(
    "reads %s evidence from %s in words, the codes on hover",
    (evidence, kind, words, source) => {
      render(
        <RecordFieldsTable
          label="Fields"
          record={{
            complete: true,
            mode: "adhoc",
            confidence: 0.9,
            fields: { title: recordField({ evidence, source_kind: kind }) },
          }}
          fieldTypes={{}}
        />,
      );

      const cells = within(screen.getByRole("row", { name: /title/ })).getAllByRole("gridcell");
      // Value, status, confidence, evidence, source.
      const [evidenceCell, sourceCell] = [cells[3], cells[4]];
      expect(evidenceCell).toHaveTextContent(words);
      expect(within(evidenceCell as HTMLElement).getByTitle(evidence)).toBeInTheDocument();
      expect(sourceCell).toHaveTextContent(source);
      expect(within(sourceCell as HTMLElement).getByTitle(kind)).toBeInTheDocument();
    },
  );

  it("shows a dash for a field with neither", () => {
    render(
      <RecordFieldsTable
        label="Fields"
        record={{
          complete: false,
          mode: "adhoc",
          confidence: null,
          fields: {
            price: recordField({
              status: "missing",
              value: null,
              confidence: null,
              evidence: null,
              source_kind: null,
              locator: null,
            }),
          },
        }}
        fieldTypes={{}}
      />,
    );

    expect(screen.getByRole("row", { name: /price/ }).textContent).toBe("price—missing—————");
  });
});

describe("LocatorText", () => {
  it("copies the locator and says so", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(
      <>
        <Toast.Provider />
        <LocatorText locator="jsonld:0:$.offers.price" />
      </>,
    );

    expect(screen.getByText("jsonld:0:$.offers.price")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy locator" }));

    expect(writeText).toHaveBeenCalledWith("jsonld:0:$.offers.price");
    expect(await screen.findByText("Locator copied")).toBeInTheDocument();
  });

  it("shows an em dash and no copy button without a locator", () => {
    const { container } = render(<LocatorText locator={null} />);

    expect(container).toHaveTextContent("—");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
