import { render, screen, within } from "@testing-library/react";
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

export function optionsButton(): HTMLElement {
  return screen.getByRole("button", { name: "Options" });
}

/** Opens the options panel and returns it. */
export async function openOptions() {
  await userEvent.click(optionsButton());
  return within(screen.getByRole("region", { name: "Options" }));
}

/** The body of the one POST the page sent. */
export function posted(calls: readonly Call[]): unknown {
  const posts = calls.filter(({ method }) => method === "POST");
  expect(posts).toHaveLength(1);
  return posts[0]?.body;
}
