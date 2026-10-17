import type {
  ChunkSource,
  ChunkStrategy,
  MethodHint,
  PageKind,
  ScrapeFormat,
  ScreenshotArea,
} from "../../api/scrape";
import { METHOD_HINTS, PAGE_KINDS } from "../../components/requestOptions";
import type { FormatSettings } from "./formatOptions";
import { NumberRow, SelectRow, SwitchRow, TagListRow, TextRow } from "./OptionsPanel";

/** Options rows more than one mode has (SPEC-14 §4.2), each named after its request member. */

/** `page_kind`. With a schema, the page kind is the one its records can be for, `schemaPageKind`, or none (SPEC-07
 * §4.4), and the others are disabled. */
export function PageKindRow({
  value,
  hasSchema,
  schemaPageKind,
  onChange,
}: Readonly<{
  value: PageKind | null;
  hasSchema: boolean;
  schemaPageKind: PageKind | null;
  onChange: (pageKind: PageKind) => void;
}>) {
  return (
    <SelectRow<PageKind>
      label="Page kind"
      help="Whether the page shows one item or a list of items. With a schema, it is the schema's."
      name="page_kind"
      options={PAGE_KINDS}
      value={hasSchema ? schemaPageKind : value}
      placeholder="Not set"
      disabled={
        hasSchema ? PAGE_KINDS.map(([kind]) => kind).filter((kind) => kind !== schemaPageKind) : []
      }
      onChange={onChange}
    />
  );
}

/** The Metadata in JSON view option: it asks for the `metadata` format, and for a job's `include=metadata`. */
export function MetadataRow({
  isSelected,
  onChange,
}: Readonly<{ isSelected: boolean; onChange: (isSelected: boolean) => void }>) {
  return (
    <SwitchRow
      label="Metadata in JSON"
      help="Adds the page's metadata (title, description, language, canonical URL) to the output."
      isSelected={isSelected}
      onChange={onChange}
    />
  );
}

/** `fetch.method_hint`. */
export function FetchMethodRow({
  value,
  onChange,
}: Readonly<{ value: MethodHint; onChange: (methodHint: MethodHint) => void }>) {
  return (
    <SelectRow<MethodHint>
      label="Fetch method"
      help="How the page is fetched. Auto starts with HTTP and moves to a browser when the page needs one."
      name="fetch.method_hint"
      options={METHOD_HINTS}
      value={value}
      onChange={onChange}
    />
  );
}

/** `fetch.max_rows`: a soft row target for a list a platform adapter reads from its API in pages (D-1395). Empty
 * asks for every page, up to the server's cap. */
export function MaxRowsRow({
  value,
  onChange,
}: Readonly<{ value: number; onChange: (maxRows: number) => void }>) {
  return (
    <NumberRow
      label="Max rows"
      help="For a list read from a platform's API in pages: stop once at least this many rows were read; the last page may pass it. Empty: every page, up to the server's cap."
      name="fetch.max_rows"
      value={value}
      minValue={1}
      onChange={onChange}
    />
  );
}

/** `budget.llm_calls` (SPEC-06 §4.8): the most LLM calls the request may make. Empty leaves `budget` out, and the
 * project's LLM call limit (Settings) applies, or none (D-1121). */
export function LlmCallsRow({
  value,
  help,
  onChange,
}: Readonly<{
  value: number;
  help: string;
  onChange: (llmCalls: number) => void;
}>) {
  return (
    <NumberRow
      label="LLM call limit"
      help={help}
      name="budget.llm_calls"
      value={value}
      minValue={0}
      placeholder="Project setting"
      onChange={onChange}
    />
  );
}

/** `webhook_url`: where the job's end is posted (SPEC-10 §4.2). */
export function WebhookRow({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (webhookUrl: string) => void }>) {
  return (
    <TextRow
      label="Webhook URL"
      help="Where the job's summary is posted when it ends. Empty: no webhook."
      name="webhook_url"
      value={value}
      placeholder="None"
      onChange={onChange}
    />
  );
}

/** `include` and `exclude`: the URL globs that scope a crawl's or a map's URLs (SPEC-10 §4.4). */
export function ScopeRows({
  include,
  exclude,
  onChange,
}: Readonly<{
  include: readonly string[];
  exclude: readonly string[];
  onChange: (scope: { include?: string[]; exclude?: string[] }) => void;
}>) {
  return (
    <>
      <TagListRow
        label="Include"
        help="URL globs a URL must match to be kept. None: the start URL's host."
        name="include"
        values={include}
        placeholder="https://example.com/items/*"
        onChange={(next) => {
          onChange({ include: next });
        }}
      />
      <TagListRow
        label="Exclude"
        help="URL globs whose URLs are left out."
        name="exclude"
        values={exclude}
        placeholder="https://example.com/cart/*"
        onChange={(next) => {
          onChange({ exclude: next });
        }}
      />
    </>
  );
}

// SPEC-04 §4.2: a schema's field names are lowercase snake case, `[a-z][a-z0-9_]{0,63}` (`NAME_PATTERN`); the server
// refuses any other, so a name is checked as it is added.
const FIELD_NAME = /^[a-z][a-z0-9_]{0,63}$/;

/** `schema.fields`: the names the server drafts a schema from (SPEC-14 §4.10), as chips, held in a mode's options. */
export function FieldsRow<O extends { fields: readonly string[] }>({
  options,
  onChange,
}: Readonly<{ options: O; onChange: (options: O) => void }>) {
  return (
    <TagListRow
      label="Fields"
      help="Names of the fields to extract. The server drafts a schema with these fields; you review it before the run."
      name="fields"
      values={options.fields}
      placeholder="price"
      refuse={(entry) =>
        FIELD_NAME.test(entry)
          ? null
          : "Use lowercase letters, digits and _, starting with a letter."
      }
      onChange={(fields) => {
        onChange({ ...options, fields });
      }}
    />
  );
}

const AREAS: readonly (readonly [ScreenshotArea, string])[] = [
  ["viewport", "Viewport"],
  ["full_page", "Full page"],
];
const STRATEGIES: readonly (readonly [ChunkStrategy, string])[] = [
  ["heading", "By heading"],
  ["sentence", "By sentence"],
  ["token", "By words"],
];
const SOURCES: readonly (readonly [ChunkSource, string])[] = [
  ["markdown", "Markdown"],
  ["markdown_fit", "Markdown (fit)"],
];

/** The options of the formats that take any (`formatOptions`): `fetch.screenshot`, `fit` and `chunking`. A row stays
 * in place, disabled, while its format is not chosen, so the layout never moves when the Format changes. */
export function FormatRows<O extends FormatSettings>({
  options,
  formats,
  onChange,
}: Readonly<{
  options: O;
  formats: readonly ScrapeFormat[];
  onChange: (options: O) => void;
}>) {
  const screenshot = !formats.includes("screenshot");
  const fit = !formats.includes("markdown_fit");
  const chunks = !formats.includes("chunks");
  return (
    <>
      <SelectRow<ScreenshotArea>
        label="Screenshot of"
        help="What the screenshot shows: the browser's window, or the whole page."
        name="fetch.screenshot"
        options={AREAS}
        value={options.screenshot}
        isDisabled={screenshot}
        onChange={(area) => {
          onChange({ ...options, screenshot: area });
        }}
      />
      <TextRow
        label="Fit query"
        help="Markdown (fit) keeps only the blocks of the page's content that match these words. Empty: all its content."
        name="fit.query"
        value={options.fitQuery}
        placeholder="None"
        isDisabled={fit}
        onChange={(fitQuery) => {
          onChange({ ...options, fitQuery });
        }}
      />
      <NumberRow
        label="Fit max blocks"
        help="With a query, keep at most this many of the best matching blocks. Empty: every matching block."
        name="fit.max_blocks"
        value={options.fitMaxBlocks}
        minValue={1}
        placeholder="All"
        isDisabled={fit}
        onChange={(fitMaxBlocks) => {
          onChange({ ...options, fitMaxBlocks });
        }}
      />
      <SelectRow<ChunkStrategy>
        label="Chunk by"
        help="How the markdown is split: a chunk per section, whole sentences packed up to the size, or windows of words."
        name="chunking.strategy"
        options={STRATEGIES}
        value={options.chunkStrategy}
        isDisabled={chunks}
        onChange={(chunkStrategy) => {
          onChange({ ...options, chunkStrategy });
        }}
      />
      <NumberRow
        label="Chunk size"
        help="The most words in a chunk. Empty: 400."
        name="chunking.size"
        value={options.chunkSize}
        minValue={1}
        placeholder="400"
        isDisabled={chunks}
        onChange={(chunkSize) => {
          onChange({ ...options, chunkSize });
        }}
      />
      <NumberRow
        label="Chunk overlap"
        help="Words a chunk repeats from the one before it; less than the size. Empty: none."
        name="chunking.overlap"
        value={options.chunkOverlap}
        minValue={0}
        placeholder="0"
        isDisabled={chunks}
        onChange={(chunkOverlap) => {
          onChange({ ...options, chunkOverlap });
        }}
      />
      <SelectRow<ChunkSource>
        label="Chunk source"
        help="The markdown the chunks are cut from: the page's content, or the same pruned of boilerplate."
        name="chunking.source"
        options={SOURCES}
        value={options.chunkSource}
        isDisabled={chunks}
        onChange={(chunkSource) => {
          onChange({ ...options, chunkSource });
        }}
      />
    </>
  );
}
