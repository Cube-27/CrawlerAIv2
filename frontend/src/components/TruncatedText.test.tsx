import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vite-plus/test";
import { stubTextLayout } from "../test/layout";
import { TruncatedText } from "./TruncatedText";

// Text of more than ten characters is cut off.
beforeEach(() => {
  stubTextLayout(100, 10);
});

function renderCells(...texts: string[]) {
  render(
    <>
      <button type="button">Before</button>
      {texts.map((text) => (
        <TruncatedText key={text} text={text} />
      ))}
    </>,
  );
}

describe("TruncatedText", () => {
  it("leaves text that fits out of the tab order, with no tooltip", async () => {
    renderCells("short");

    expect(screen.getByText("short")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "short" })).toBeNull();
    await userEvent.tab();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Before" })).not.toHaveFocus();
    expect(document.body).toHaveFocus();
  });

  it("makes only cut-off text a tab stop, its full text in a tooltip on focus", async () => {
    const long = "a much longer value";
    renderCells("short", long);

    await userEvent.tab();
    await userEvent.tab();

    expect(screen.getByRole("button", { name: long })).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent(long);
  });
});
