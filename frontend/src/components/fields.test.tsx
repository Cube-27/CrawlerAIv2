import { Toast } from "@heroui/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vite-plus/test";
import type { FieldStatus } from "../api/field";
import { ConfidenceCell } from "./ConfidenceCell";
import { FieldStatusBadge } from "./FieldStatusBadge";
import { FieldValue } from "./FieldValue";
import { LocatorText } from "./LocatorText";

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
      { locality: "Springfield", region: null, country: "ZZ", remote_flag: false },
      "Springfield, ZZ",
    ],
    [
      "remote location",
      { type: "location" },
      { locality: null, region: null, country: null, remote_flag: true },
      "remote",
    ],
    ["date", { type: "date" }, "2026-03-04", "2026-03-04"],
    ["identifier", { type: "identifier" }, { scheme: "sku", value: "AB-12" }, "AB-12"],
    [
      "range",
      { type: "range" },
      { min: "10", max: "20", currency: "EUR", unit: null, period: "HOUR" },
      "10–20 EUR per HOUR",
    ],
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

describe("ConfidenceCell", () => {
  it("shows the confidence with two decimals and no badge when calibrated", () => {
    const { container } = render(<ConfidenceCell confidence={0.9} calibrated={true} />);

    expect(container).toHaveTextContent("0.90");
    expect(screen.queryByText("uncalibrated")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("shows a visible uncalibrated badge", () => {
    const { container } = render(<ConfidenceCell confidence={0.456} calibrated={false} />);

    expect(container).toHaveTextContent("0.46");
    expect(screen.getByText("uncalibrated")).toBeInTheDocument();
  });

  it("shows an em dash when there is no confidence", () => {
    const { container } = render(<ConfidenceCell confidence={null} calibrated={true} />);

    expect(container).toHaveTextContent("—");
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
