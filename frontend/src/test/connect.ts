import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/** Connects the shell with `apiKey`, pasted rather than typed key by key: typing is slow in jsdom, and a test that
 * spends its time connecting times out under load (UAT F25, F35). `app/auth.test.tsx` covers typing a key. */
export async function connect(apiKey = "ck_first"): Promise<void> {
  await userEvent.click(screen.getByLabelText(/API key/));
  await userEvent.paste(apiKey);
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
}
