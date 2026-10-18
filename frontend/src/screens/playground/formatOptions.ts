import type {
  ChunkOptions,
  ChunkSource,
  ChunkStrategy,
  FitOptions,
  ScrapeFormat,
  ScreenshotArea,
} from "../../api/scrape";
import { optionalNumber } from "./pageRequest";
import { count, member, text, type StoredRequest } from "./run/storedRequest";

/** The options of the formats that take any (frontend spec), in every mode with a Format select (Scrape, Batch, Crawl):
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

const AREAS: readonly ScreenshotArea[] = ["viewport", "full_page"];
const STRATEGIES: readonly ChunkStrategy[] = ["heading", "sentence", "token"];
const SOURCES: readonly ChunkSource[] = ["markdown", "markdown_fit"];

function choice<T extends string>(options: readonly T[], value: unknown, empty: T): T {
  return options.find((option) => option === value) ?? empty;
}

/** The settings a stored request shows (`GET /v1/jobs/{id}/request`): what it holds, else the defaults. */
export function storedFormatSettings(request: StoredRequest): FormatSettings {
  const fit = member(request, "fit");
  const chunking = member(request, "chunking");
  return {
    screenshot: choice(
      AREAS,
      member(request, "fetch")["screenshot"],
      DEFAULT_FORMAT_SETTINGS.screenshot,
    ),
    fitQuery: text(fit, "query"),
    fitMaxBlocks: count(fit, "max_blocks"),
    chunkStrategy: choice(STRATEGIES, chunking["strategy"], DEFAULT_FORMAT_SETTINGS.chunkStrategy),
    chunkSize: count(chunking, "size"),
    chunkOverlap: count(chunking, "overlap"),
    chunkSource: choice(SOURCES, chunking["source"], DEFAULT_FORMAT_SETTINGS.chunkSource),
  };
}
