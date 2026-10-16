import { today } from "@internationalized/date";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { routes } from "../../app/router";
import type { CostReport, LlmUsage } from "../../api/usage";
import { problem, stubApi } from "../../test/api";

const JOB_ID = "0192a000-0000-7000-8000-000000000901";
const REPORT = "GET /v1/usage/llm";
const SETTINGS = "GET /v1/project/settings";
const NO_CAP = { [SETTINGS]: () => Response.json({ llm_call_cap: null }) };

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

function rowsOf(name: string): (string | null)[] {
  return within(screen.getByRole("grid", { name }))
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.textContent);
}

/** The first UTC day of a range of `days` days through today. */
function startOf(days: number): string {
  return today("UTC")
    .subtract({ days: days - 1 })
    .toString();
}

describe("Settings screen", () => {
  it("shows the LLM cost of the last 30 days by total, model and role, job and day", async () => {
    const calls = stubApi({ ...NO_CAP, [REPORT]: () => Response.json(report) });
    await openSettings();

    await screen.findByRole("grid", { name: "Total" });
    expect(calls.find(({ path }) => path === "/v1/usage/llm")?.query).toBe(`start=${startOf(30)}`);
    expect(rowsOf("Total")).toEqual(["Total34,500450Unknown: 550 tokens have no price"]);
    expect(rowsOf("By model and role")).toEqual([
      "unlisted-modelfakeaiExtraction, detail page150050Unknown: 550 tokens have no price",
      "listed-modelfakeaiConfig synthesis24,000400$0.0048",
    ]);
    expect(rowsOf("Per day")).toEqual([
      "2031-01-0313,000300$0.0036",
      "2031-01-0221,500150Unknown: 550 tokens have no price",
    ]);
    expect(rowsOf("Top jobs by cost")).toEqual(["ExtractJan 2, 2031, 09:0024,000400$0.0048"]);
  });

  it("opens a job from the top jobs", async () => {
    stubApi({
      ...NO_CAP,
      [REPORT]: () => Response.json(report),
      [`GET /v1/jobs/${JOB_ID}`]: () =>
        problem(404, { title: "Not found", detail: `no job ${JOB_ID}` }),
    });
    await openSettings();

    const jobs = await screen.findByRole("grid", { name: "Top jobs by cost" });
    await userEvent.click(within(jobs).getByText("Extract"));

    expect(await screen.findByText(`no job ${JOB_ID}`)).toBeInTheDocument();
  });

  it("asks for the range chosen", async () => {
    const calls = stubApi({ ...NO_CAP, [REPORT]: () => Response.json(report) });
    await openSettings();
    await screen.findByRole("grid", { name: "Total" });

    await userEvent.click(screen.getByRole("button", { name: /Range/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Last 7 days" }));

    await screen.findByRole("grid", { name: "Total" });
    const starts = calls.filter(({ path }) => path === "/v1/usage/llm").map(({ query }) => query);
    expect(starts).toEqual([`start=${startOf(30)}`, `start=${startOf(7)}`]);
  });

  it("says so when the range has no LLM calls", async () => {
    stubApi({ ...NO_CAP, [REPORT]: () => Response.json(empty) });
    await openSettings();

    expect(await screen.findByText("No LLM calls in this range")).toBeInTheDocument();
    expect(screen.queryByRole("grid", { name: "Total" })).toBeNull();
  });

  it("shows the problem of a refused report", async () => {
    stubApi({
      ...NO_CAP,
      [REPORT]: () =>
        problem(422, { title: "Invalid request", detail: "the range spans more than 366 days" }),
    });
    await openSettings();

    expect(await screen.findByText("the range spans more than 366 days")).toBeInTheDocument();
  });

  it("shows the project's LLM call limit and saves a new one", async () => {
    const calls = stubApi({
      [SETTINGS]: () => Response.json({ llm_call_cap: 25 }),
      [REPORT]: () => Response.json(empty),
      "PATCH /v1/project/settings": ({ body }) => Response.json(body),
    });
    await openSettings();
    const field = await savedLimit("25");

    await userEvent.clear(field);
    await userEvent.type(field, "40");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved the LLM call limit.")).toBeInTheDocument();
    const saves = calls.filter(({ method }) => method === "PATCH").map(({ body }) => body);
    expect(saves).toEqual([{ llm_call_cap: 40 }]);
  });

  it("saves an empty LLM call limit as no limit", async () => {
    const calls = stubApi({
      [SETTINGS]: () => Response.json({ llm_call_cap: 25 }),
      [REPORT]: () => Response.json(empty),
      "PATCH /v1/project/settings": ({ body }) => Response.json(body),
    });
    await openSettings();
    const field = await savedLimit("25");

    await userEvent.clear(field);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByText("Saved the LLM call limit.");
    expect(calls.filter(({ method }) => method === "PATCH").map(({ body }) => body)).toEqual([
      { llm_call_cap: null },
    ]);
  });
});
