import type {
  ChunkOptions,
  ChunkSource,
  ChunkStrategy,
  FitOptions,
  ScrapeFormat,
  ScreenshotArea,
} from "../../api/scrape";
import type { StoredRequestOf } from "../../api/jobs";
import { optionalNumber } from "./pageRequest";
import { orEmpty } from "./run/storedRequest";

/** The options of the formats that take any, in every mode with a Format select (Scrape, Batch, Crawl):
 * the area of a `screenshot`, `markdown_fit`'s query and block limit, and `chunks`' strategy, size, overlap and source.
 * A setting is sent only with its format; an empty number (NaN) is left out, so the server's default applies. */
export interface FormatSettings {
  screenshot: ScreenshotArea;
  fitQuery: string;
  fitMaxBlocks: number;
  chunkStrategy: ChunkStrategy;
  chunkSize: number;
  chunkOverlap: number;
  chunkSource: ChunkSource;
}

export const DEFAULT_FORMAT_SETTINGS: FormatSettings = {
  screenshot: "viewport",
  fitQuery: "",
  fitMaxBlocks: Number.NaN,
  chunkStrategy: "heading",
  chunkSize: Number.NaN,
  chunkOverlap: Number.NaN,
  chunkSource: "markdown",
};

/** The request members the settings give for `formats`: `fit` with `markdown_fit`, `chunking` with `chunks`. */
export function formatMembers(
  formats: readonly ScrapeFormat[],
  settings: FormatSettings,
): { fit?: FitOptions; chunking?: Partial<ChunkOptions> } {
  const query = settings.fitQuery.trim();
  return {
    ...(formats.includes("markdown_fit")
      ? {
          fit: {
            ...(query === "" ? {} : { query }),
            ...optionalNumber("max_blocks", settings.fitMaxBlocks),
          },
        }
      : {}),
    ...(formats.includes("chunks")
      ? {
          chunking: {
            strategy: settings.chunkStrategy,
            source: settings.chunkSource,
            ...optionalNumber("size", settings.chunkSize),
            ...optionalNumber("overlap", settings.chunkOverlap),
          },
        }
      : {}),
  };
}

/** The settings a stored request shows (`GET /v1/jobs/{id}/request`): what it holds, else the defaults. */
export function storedFormatSettings(
  request: StoredRequestOf<"scrape" | "batch_scrape" | "crawl">,
): FormatSettings {
  const { fit, chunking } = request;
  return {
    screenshot: request.fetch.screenshot,
    fitQuery: fit?.query ?? "",
    fitMaxBlocks: orEmpty(fit?.max_blocks ?? null),
    chunkStrategy: chunking?.strategy ?? DEFAULT_FORMAT_SETTINGS.chunkStrategy,
    chunkSize: orEmpty(chunking?.size ?? null),
    chunkOverlap: orEmpty(chunking?.overlap ?? null),
    chunkSource: chunking?.source ?? DEFAULT_FORMAT_SETTINGS.chunkSource,
  };
}
