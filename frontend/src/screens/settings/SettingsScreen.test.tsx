import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { routes } from "../../app/router";
import type { CostReport, LlmUsage } from "../../api/usage";
import { stubApi } from "../../test/api";

const JOB_ID = "0192a000-0000-7000-8000-000000000901";
const REPORT = "GET /v1/usage/llm";
const SETTINGS = "GET /v1/project/settings";

function usage(overrides: Partial<LlmUsage> = {}): LlmUsage {
  return {
    calls: 0,
    tokens_in: 0,
    tokens_out: 0,
    unpriced_tokens: 0,
    estimated_usd: 0,
    ...overrides,
  };
}

const report: CostReport = {
  start: "2031-01-02",
  end: "2031-01-03",
  currency: "USD",
  total: usage({
    calls: 3,
    tokens_in: 4500,
    tokens_out: 450,
    unpriced_tokens: 550,
    estimated_usd: null,
  }),
  days: [
    {
      day: "2031-01-02",
      ...usage({
        calls: 2,
        tokens_in: 1500,
        tokens_out: 150,
        unpriced_tokens: 550,
        estimated_usd: null,
      }),
    },
    {
      day: "2031-01-03",
      ...usage({ calls: 1, tokens_in: 3000, tokens_out: 300, estimated_usd: 0.0036 }),
    },
  ],
  breakdown: [
    {
      provider: "fakeai",
      model: "unlisted-model",
      prompt_kind: "c_extract_detail",
      ...usage({
        calls: 1,
        tokens_in: 500,
        tokens_out: 50,
        unpriced_tokens: 550,
        estimated_usd: null,
      }),
    },
    {
      provider: "fakeai",
      model: "listed-model",
      prompt_kind: "a_synth",
      ...usage({ calls: 2, tokens_in: 4000, tokens_out: 400, estimated_usd: 0.0048 }),
    },
  ],
  top_jobs: [
    {
      job_id: JOB_ID,
      kind: "extract",
      created_at: "2031-01-02T09:00:00Z",
      ...usage({ calls: 2, tokens_in: 4000, tokens_out: 400, estimated_usd: 0.0048 }),
    },
  ],
};

const empty: CostReport = {
  ...report,
  total: usage(),
  days: [{ day: "2031-01-02", ...usage() }],
  breakdown: [],
  top_jobs: [],
};

async function openSettings() {
  // Opened by its address: the shell's tests cover the navigation.
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/settings"] })} />);
  await screen.findByRole("heading", { level: 1, name: "Settings" });
}

/** The LLM call limit field, once it shows the saved `value`: the form mounts again when the settings arrive. */
async function savedLimit(value: string): Promise<HTMLElement> {
  const name = "LLM call limit per run";
  await waitFor(() => {
    expect(screen.getByRole("textbox", { name })).toHaveValue(value);
  });
  return screen.getByRole("textbox", { name });
}

describe("Settings screen", () => {
  it("shows the project's LLM call limit and saves a new one", async () => {
    const calls = stubApi({
      [SETTINGS]: () =>
        Response.json({ llm_call_cap: 25, draft_call_cap: 4, require_config_approval: false }),
      [REPORT]: () => Response.json(empty),
      "PATCH /v1/project/settings": ({ body }) => Response.json(body),
    });
    await openSettings();
    const field = await savedLimit("25");

    await userEvent.clear(field);
    await userEvent.type(field, "40");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved the limits.")).toBeInTheDocument();
    const saves = calls.filter(({ method }) => method === "PATCH").map(({ body }) => body);
    expect(saves).toEqual([
      { llm_call_cap: 40, draft_call_cap: 4, require_config_approval: false },
    ]);
  });
});
