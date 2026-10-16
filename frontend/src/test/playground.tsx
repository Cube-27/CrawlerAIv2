import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { expect } from "vite-plus/test";
import { routes } from "../app/router";
import type { Call } from "./api";

/** Steps the playground tests share: open a mode, set its toolbar and options, read what it posted. */

/** Renders the app at `path` (a playground mode's route) and waits for the playground. */
export async function openPlayground(path: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
  await screen.findByRole("heading", { level: 1, name: "Playground" });
}

/** The trigger of the Select named by `name`; its help icon has the name too. */
export function selectTrigger(name: RegExp): HTMLElement {
  const trigger = screen
    .getAllByRole("button", { name })
    .find((button) => button.getAttribute("aria-haspopup") === "listbox");
  if (trigger === undefined) throw new Error(`no select named ${String(name)}`);
  return trigger;
}

/** Picks `option` in the Select named by `name`. */
export async function pick(name: RegExp, option: string) {
  await userEvent.click(selectTrigger(name));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

/** Toggles each of `formats` in the toolbar's Format select, then closes it. */
export async function toggleFormats(...formats: string[]) {
  await userEvent.click(selectTrigger(/Format/));
  for (const format of formats) {
    await userEvent.click(await screen.findByRole("option", { name: format }));
  }
  await userEvent.keyboard("{Escape}");
}

/** Enters `text` into `field` at once (a paste), then presses Enter when `enter` is set: typing a long URL key by key
 * is slow in jsdom. */
export async function fill(field: HTMLElement, text: string, enter = false) {
  await userEvent.click(field);
  await userEvent.paste(text);
  if (enter) await userEvent.keyboard("{Enter}");
}

export function optionsButton(): HTMLElement {
  // While the popover is open, the page under it is hidden from assistive technology, the button too.
  return screen.getByRole("button", { name: "Options", hidden: true });
}

/** The open options popover, once it shows. */
export async function findOptions() {
  return within(await screen.findByRole("dialog", { name: "Options" }));
}

/** Opens the options popover and returns it. */
export async function openOptions() {
  await userEvent.click(optionsButton());
  return findOptions();
}

/** Closes the options popover with Escape, so the page under it can be used again. */
export async function closeOptions() {
  // A browser returns focus to a Select's trigger when its list closes; jsdom can leave it on the body, where Escape
  // reaches no overlay. The popover gets it back first, as a user's Escape always starts inside it.
  const dialog = screen.getByRole("dialog", { name: "Options" });
  if (!dialog.contains(document.activeElement)) {
    act(() => {
      dialog.focus();
    });
  }
  await userEvent.keyboard("{Escape}");
  await waitFor(() => {
    expect(screen.queryByRole("dialog", { name: "Options" })).not.toBeInTheDocument();
  });
}

/** The body of the one POST the page sent. */
export function posted(calls: readonly Call[]): unknown {
  const posts = calls.filter(({ method }) => method === "POST");
  expect(posts).toHaveLength(1);
  return posts[0]?.body;
}
