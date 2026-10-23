import type { ModeId } from "../modes";

/** The endpoint a mode's primary action posts to. */
export interface Endpoint {
  /** The OpenAPI path; every mode sends a `POST`. */
  path: string;
  /** The operation's OpenAPI summary. */
  title: string;
  /** The first sentence of the operation's OpenAPI description. */
  sentence: string;
  /** The MCP tool that takes the same request; null when no tool does. */
  mcpTool: string | null;
}

/** One entry per mode, copied from `openapi.json` (a test keeps them equal). */
export const ENDPOINTS: Readonly<Record<ModeId, Endpoint>> = {
  scrape: {
    path: "/v1/scrape",
    title: "Scrape",
    sentence:
      "Fetch `url`, or read a capture of it fetched within `max_age` seconds, and return the requested formats; only those are members of the answer.",
    mcpTool: "scrape",
  },
  batch: {
    path: "/v1/batch/scrape",
    title: "Batch Scrape",
    sentence:
      "Queue a job that scrapes each of `urls` with the same formats, schema and fetch options; a URL given twice is scraped once.",
    // §13.3 lists no batch tool: an agent calls `scrape` per URL.
    mcpTool: null,
  },
  extract: {
    path: "/v1/extract",
    title: "Extract Records",
    sentence:
      "Queue a job that extracts a record of `page_kind` from each of `urls`; a URL with a `*` is a glob, expanded through a map of its host.",
    mcpTool: "extract",
  },
  map: {
    path: "/v1/map",
    title: "Map Urls",
    sentence:
      "The URLs of `url`'s site from its sitemaps and the start page's links, canonical and in scope: the exact host of `url`, or the `include` globs, less the `exclude` globs.",
    mcpTool: "map",
  },
  crawl: {
    path: "/v1/crawl",
    title: "Crawl Site",
    sentence:
      "Queue a job that crawls from `url`: its sitemaps and the links of each page, within `include` and `exclude`, `max_depth` and `limit`, on its host (and the subdomains an `include` names).",
    mcpTool: "crawl_start",
  },
  search: {
    path: "/v1/search",
    title: "Search",
    sentence:
      "The web results of `query` from the configured provider: `url`, `title` and `snippet`, in its order, at most `limit`.",
    mcpTool: "search",
  },
};
