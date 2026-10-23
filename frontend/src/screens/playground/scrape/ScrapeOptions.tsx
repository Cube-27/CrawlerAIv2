import { AdvancedRows } from "../AdvancedRows";
import type { PageKind, PagingHint, ScrapeFormat } from "../../../api/scrape";
import { NumberRow, OptionsPanel, SelectRow, SwitchRow } from "../OptionsPanel";
import { LlmCallsRow, PageFetchRows, PageOutputRows } from "../rows";
import { LIMITS } from "../../../api/limits";
import { browserActionsApply, DEFAULT_OPTIONS, type ScrapeOptions as Options } from "./form";

const MAX_TIMEOUT_S = LIMITS["ScrapeRequest-Input"].timeout_s.maximum;

/** Scrape's options: page kind, fetch method, max age, timeout, the LLM call limit, Metadata in JSON,
 * fields and a listing's browser actions. */
export function ScrapeOptions({
  options,
  formats,
  hasSchema,
  schemaPageKind,
  onChange,
}: Readonly<{
  options: Options;
  formats: readonly ScrapeFormat[];
  hasSchema: boolean;
  schemaPageKind: PageKind | null;
  onChange: (options: Options) => void;
}>) {
  return (
    <OptionsPanel
      onReset={() => {
        onChange(DEFAULT_OPTIONS);
      }}
    >
      <PageFetchRows
        options={options}
        hasSchema={hasSchema}
        schemaPageKind={schemaPageKind}
        onChange={onChange}
      />
      <NumberRow
        label="Max age (s)"
        help="Reuse a capture of the page this many seconds old or newer instead of fetching it again. Empty: the server default."
        name="max_age"
        value={options.maxAge}
        minValue={0}
        onChange={(maxAge) => {
          onChange({ ...options, maxAge });
        }}
      />
      <NumberRow
        label="Timeout (s)"
        help={`How long the scrape may take, in seconds, at most ${String(MAX_TIMEOUT_S)}. Empty: the server default.`}
        name="timeout_s"
        value={options.timeoutS}
        minValue={1}
        maxValue={MAX_TIMEOUT_S}
        onChange={(timeoutS) => {
          onChange({ ...options, timeoutS });
        }}
      />
      <LlmCallsRow
        value={options.llmCalls}
        help="The most LLM calls this scrape may make. Empty: the project's limit in Settings."
        onChange={(llmCalls) => {
          onChange({ ...options, llmCalls });
        }}
      />
      <PageOutputRows options={options} formats={formats} onChange={onChange} />
      <BrowserActionsRows
        options={options}
        applies={browserActionsApply(options, hasSchema ? schemaPageKind : options.pageKind)}
        onChange={onChange}
      />
      <AdvancedRows
        value={options.advanced}
        onChange={(advanced) => {
          onChange({ ...options, advanced });
        }}
      />
    </OptionsPanel>
  );
}

// "Detect" stands for no hint: the server finds the mechanism.
type HintChoice = PagingHint | "detect";
const HINTS: readonly (readonly [HintChoice, string])[] = [
  ["detect", "Detect"],
  ["load_more", "Load more"],
  ["show_more", "Show more"],
  ["pagination", "Page numbers"],
  ["next", "Next page"],
  ["scroll", "Scroll"],
];

/** `browser_actions`: where they do not apply (`browserActionsApply`) the rows stay in place, disabled,
 * and nothing is sent (the layout never moves when another option changes). */
function BrowserActionsRows({
  options,
  applies,
  onChange,
}: Readonly<{ options: Options; applies: boolean; onChange: (options: Options) => void }>) {
  const off = !applies || !options.browserActions;
  return (
    <>
      <SwitchRow
        label="Browser actions"
        help="For a listing fetched now in a browser (not HTTP, max age empty or 0): scroll and click its paging controls to collect more rows."
        isSelected={options.browserActions}
        isDisabled={!applies}
        onChange={(browserActions) => {
          onChange({ ...options, browserActions });
        }}
      />
      <NumberRow
        label="Records"
        help="Stop once at least this many rows were seen; the last page or batch may pass it. Empty: 100."
        name="browser_actions.records"
        value={options.records}
        minValue={1}
        placeholder="100"
        isDisabled={off}
        onChange={(records) => {
          onChange({ ...options, records });
        }}
      />
      <SelectRow<HintChoice>
        label="Paging hint"
        help="How the listing loads more rows. Detect: the server finds out."
        name="browser_actions.hint"
        options={HINTS}
        value={options.pagingHint ?? "detect"}
        isDisabled={off}
        onChange={(choice) => {
          onChange({ ...options, pagingHint: choice === "detect" ? null : choice });
        }}
      />
    </>
  );
}
