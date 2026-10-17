import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vite-plus/test";
import { problem, stubApi, type Call } from "../../../test/api";
import {
  closeOptions,
  fill,
  openOptions,
  openPlayground,
  pick,
  posted,
} from "../../../test/playground";
import { runApi, schemaList } from "../../../test/runs";
import { curlBody } from "../../../test/shell";

// Every mode's Get code (SPEC-14 §4.7) against what its primary action posts. `fetch` answers each submit with the
// shapes SPEC-07 §4.3 and SPEC-10 §4.2–4.6 define; the scrape is refused, as only its body matters here.

const JOB_ID = "0192a000-0000-7000-8000-0000000000g1";

/** A value that breaks code built by concatenation: both quotes, a newline, a backslash and `$`. */
const AWKWARD = `it's "x"\nback\\slash $HOME`;

interface ModeCase {
  route: string;
  action: string;
  stub: () => Call[];
  /** Fills the bar and options with values whose quoting matters. */
  fillForm: () => Promise<void>;
}

async function typeUrl(url: string) {
  await fill(screen.getByRole("textbox", { name: "URL" }), url);
}

const CASES: Readonly<Record<string, ModeCase>> = {
  scrape: {
    route: "/",
    action: "Scrape",
    stub: () =>
      stubApi({
        "GET /v1/schemas": schemaList,
        "POST /v1/scrape": () => problem(503, { title: "Busy" }),
      }),
    fillForm: () => typeUrl(`shop.test/it's?q="a b"`),
  },
  batch: {
    route: "/batch",
    action: "Start batch",
    stub: () => runApi({ submit: "POST /v1/batch/scrape", jobId: JOB_ID, kind: "batch_scrape" }),
    fillForm: () =>
      fill(
        screen.getByRole("textbox", { name: "URLs" }),
        `https://shop.test/a\nhttps://shop.test/it's`,
      ),
  },
  crawl: {
    route: "/crawl",
    action: "Start crawl",
    stub: () => runApi({ submit: "POST /v1/crawl", jobId: JOB_ID, kind: "crawl" }),
    fillForm: async () => {
      await typeUrl("https://shop.test/");
      const options = await openOptions();
      await fill(
        options.getByRole("textbox", { name: "Include" }),
        `https://shop.test/it's/*`,
        true,
      );
      await closeOptions();
    },
  },
  map: {
    route: "/map",
    action: "Map",
    stub: () =>
      stubApi({
        "POST /v1/map": () =>
          Response.json({ urls: [], sources: { sitemap: 0, links: 0 }, truncated: false }),
      }),
    fillForm: () => typeUrl(`https://shop.test/it's`),
  },
  extract: {
    route: "/extract",
    action: "Extract",
    stub: () => runApi({ submit: "POST /v1/extract", jobId: JOB_ID, kind: "extract" }),
    fillForm: async () => {
      await typeUrl("https://shop.test/items/1");
      await pick(/Schema$/, "From a prompt");
      const options = await openOptions();
      await fill(options.getByRole("textbox", { name: "Prompt" }), AWKWARD);
      await pick(/Page kind/, "Detail");
      await closeOptions();
    },
  },
};

/** Opens Get code and returns the drawer's queries. */
async function openGetCode() {
  await userEvent.click(screen.getByRole("button", { name: "Get code" }));
  return within(await screen.findByRole("dialog"));
}

type Drawer = Awaited<ReturnType<typeof openGetCode>>;

/** The code shown under `language`'s tab. */
async function shownCode(drawer: Drawer, language: string): Promise<string> {
  await userEvent.click(drawer.getByRole("tab", { name: language }));
  return drawer.getByRole("region", { name: `${language} code` }).textContent;
}

function mcpArguments(code: string): unknown {
  return (JSON.parse(code) as { params: { arguments: unknown } }).params.arguments;
}

describe("get code", () => {
  it.each(Object.keys(CASES))(
    "%s: cURL and MCP send the body the primary action posts",
    async (name) => {
      const mode = CASES[name];
      if (mode === undefined) throw new Error(name);
      const calls = mode.stub();
      await openPlayground(mode.route);
      await mode.fillForm();

      const drawer = await openGetCode();
      const curl = curlBody(await shownCode(drawer, "cURL"));
      const mcp = await shownCode(drawer, "MCP");
      await userEvent.keyboard("{Escape}");
      await userEvent.click(screen.getByRole("button", { name: mode.action }));

      const body = posted(calls);
      expect(curl).toEqual(body);
      if (name === "batch") expect(mcp).toContain("no tool for this endpoint");
      else expect(mcpArguments(mcp)).toEqual({ request: body });
    },
  );

  it("keeps an awkward value intact in the cURL body", async () => {
    CASES["extract"]?.stub();
    await openPlayground("/extract");
    await CASES["extract"]?.fillForm();

    const drawer = await openGetCode();

    expect(curlBody(await shownCode(drawer, "cURL"))).toMatchObject({
      schema: { prompt: AWKWARD },
    });
  });

  it("shows the endpoint and where the key comes from, the prompts collapsed, and no key", async () => {
    stubApi({ "GET /v1/schemas": schemaList });
    await openPlayground("/");

    const drawer = await openGetCode();
    expect(
      drawer.queryByRole("button", { name: "Copy Use it with coding agents" }),
    ).not.toBeInTheDocument();
    await userEvent.click(drawer.getByRole("button", { name: "Prompts for coding agents" }));

    expect(
      drawer.getByRole("button", { name: "Copy Use it with coding agents" }),
    ).toBeInTheDocument();
    expect(drawer.getByRole("button", { name: "Copy Build on top of it" })).toBeInTheDocument();
    expect(drawer.getByRole("region", { name: "API key" })).toHaveTextContent(
      "crawlerai apikey create",
    );
    expect(drawer.getByRole("region", { name: "Endpoint" })).toHaveTextContent("POST /v1/scrape");
    expect(await shownCode(drawer, "cURL")).toContain("$CRAWLERAI_API_KEY");
  });

  it("says the batch endpoint has no MCP tool, with Copy code off", async () => {
    stubApi({ "GET /v1/schemas": schemaList });
    await openPlayground("/batch");

    const drawer = await openGetCode();
    await userEvent.click(drawer.getByRole("tab", { name: "MCP" }));

    expect(drawer.getByText(/has no tool for this endpoint/)).toBeInTheDocument();
    expect(drawer.getByRole("button", { name: "Copy code" })).toBeDisabled();
  });

  it("copies the shown code", async () => {
    // userEvent's setup gives jsdom the clipboard it lacks.
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    stubApi({ "GET /v1/schemas": schemaList });
    await openPlayground("/");
    await typeUrl("https://shop.test/a");
    const drawer = await openGetCode();
    const code = await shownCode(drawer, "Python");

    await user.click(drawer.getByRole("button", { name: "Copy code" }));

    // Each shown line ends in a newline; the copied code has none after its last line.
    expect(writeText).toHaveBeenCalledWith(code.slice(0, -1));
    expect(code).toContain('"url": "https://shop.test/a",');
    expect(await screen.findByText("Copied the code.")).toBeInTheDocument();
  });
});
