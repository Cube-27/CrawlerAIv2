import { Toast } from "@heroui/react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vite-plus/test";
import { catchDownloads } from "../test/downloads";
import { JsonView } from "./JsonView";
import { jsonLines, jsonTokens } from "./jsonTokens";

const ITEM = {
  url: "https://store.test/items/1",
  outcome: "extracted",
  records: [
    { price: { amount: "19.90", currency: "EUR" }, stock: -2.5e3, title: null, sale: true },
  ],
};

const PRETTY = `{
  "url": "https://store.test/items/1",
  "outcome": "extracted",
  "records": [
    {
      "price": {
        "amount": "19.90",
        "currency": "EUR"
      },
      "stock": -2500,
      "title": null,
      "sale": true
    }
  ]
}`;

function renderView() {
  render(
    <>
      <Toast.Provider />
      <JsonView label="Page JSON" value={ITEM} filename="page.json" />
    </>,
  );
  return screen.getByRole("region", { name: "Page JSON" });
}

describe("JsonView", () => {
  it("shows the value pretty-printed with a two-space indent", () => {
    expect(renderView().textContent).toBe(PRETTY);
  });

  it("colors member names, strings, numbers and literals each by their own theme class", () => {
    const view = within(renderView());

    expect(view.getByText('"outcome"')).toHaveClass("json-key");
    expect(view.getByText('"extracted"')).toHaveClass("json-string");
    expect(view.getByText("-2500")).toHaveClass("json-number");
    expect(view.getByText("null")).toHaveClass("json-literal");
    expect(view.getByText("true")).toHaveClass("json-literal");
  });

  it("copies the pretty-printed JSON", async () => {
    // userEvent's setup gives jsdom the clipboard it lacks.
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    renderView();

    await user.click(screen.getByRole("button", { name: "Copy" }));

    expect(writeText).toHaveBeenCalledWith(PRETTY);
    expect(await screen.findByText("Copied the JSON.")).toBeInTheDocument();
  });

  it("downloads the pretty-printed JSON as its file", async () => {
    const saved = catchDownloads();
    renderView();

    await userEvent.click(screen.getByRole("button", { name: "Download" }));

    expect(saved.map(({ name }) => name)).toEqual(["page.json"]);
    expect(await saved[0]?.text).toBe(PRETTY);
  });
});

describe("jsonTokens", () => {
  it("cuts text into tokens that join back into it, a string with quotes, colons and digits staying one string", () => {
    const text = JSON.stringify({ 'say "a: 1"': ['x\\": 2', 3, false] }, null, 2);

    const tokens = jsonTokens(text);

    expect(tokens.map(({ text: part }) => part).join("")).toBe(text);
    expect(tokens.filter(({ kind }) => kind !== "plain")).toEqual([
      { kind: "key", text: '"say \\"a: 1\\""', start: 4 },
      { kind: "string", text: '"x\\\\\\": 2"', start: 26 },
      { kind: "number", text: "3", start: 42 },
      { kind: "literal", text: "false", start: 49 },
    ]);
  });
});

describe("jsonLines", () => {
  it("cuts text into lines of an indent and tokens, each token keeping its place in the text", () => {
    const text = JSON.stringify({ a: [1, "x"] }, null, 2);

    const lines = jsonLines(text);

    expect(lines.map(({ indent }) => indent.length)).toEqual([0, 2, 4, 4, 2, 0]);
    expect(lines.map(({ indent, tokens }) => indent + tokens.map((t) => t.text).join(""))).toEqual(
      text.split("\n"),
    );
    expect(lines[2]?.tokens).toEqual([
      { kind: "number", text: "1", start: 15 },
      { kind: "plain", text: ",", start: 16 },
    ]);
    expect(text.slice(15, 17)).toBe("1,");
  });
});
