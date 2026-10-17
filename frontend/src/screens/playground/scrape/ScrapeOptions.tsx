import type { PageKind, PagingHint } from "../../../api/scrape";
import { NumberRow, OptionsPanel, SelectRow, SwitchRow } from "../OptionsPanel";
import { FetchMethodRow, FieldsRow, LlmCallsRow, MetadataRow, PageKindRow } from "../rows";
import { DEFAULT_OPTIONS, type ScrapeOptions as Options } from "./form";

/** Scrape's options (SPEC-14 §4.2): page kind, fetch method, max age, timeout, the LLM call limit, Metadata in JSON,
 * fields (§4.10) and a listing's browser actions (owner #52). */
export function ScrapeOptions({
  options,
  hasSchema,
  schemaPageKind,
  onChange,
}: Readonly<{
  options: Options;
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
      <PageKindRow
        value={options.pageKind}
        hasSchema={hasSchema}
        schemaPageKind={schemaPageKind}
        onChange={(pageKind) => {
          onChange({ ...options, pageKind });
        }}
      />
      <FetchMethodRow
        value={options.methodHint}
        onChange={(methodHint) => {
          onChange({ ...options, methodHint });
        }}
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
      {/* SPEC-07 §4.4: the request is bounded by `timeout_s`, at most 120. */}
      <NumberRow
        label="Timeout (s)"
        help="How long the scrape may take, in seconds, at most 120. Empty: the server default."
        name="timeout_s"
        value={options.timeoutS}
        minValue={1}
        maxValue={120}
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
      <MetadataRow
        isSelected={options.metadataInJson}
        onChange={(metadataInJson) => {
          onChange({ ...options, metadataInJson });
        }}
      />
      <FieldsRow options={options} onChange={onChange} />
      <BrowserActionsRows
        options={options}
        isListing={(hasSchema ? schemaPageKind : options.pageKind) === "listing"}
        onChange={onChange}
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

/** `browser_actions` (owner #52): only a listing's, so for another page kind the rows stay in place, disabled, and
 * nothing is sent (the layout never moves when the page kind changes). */
function BrowserActionsRows({
  options,
  isListing,
  onChange,
}: Readonly<{ options: Options; isListing: boolean; onChange: (options: Options) => void }>) {
  const off = !isListing || !options.browserActions;
  return (
    <>
      <SwitchRow
        label="Browser actions"
        help="For a listing: scroll and click its paging controls in a browser to collect more rows."
        isSelected={options.browserActions}
        isDisabled={!isListing}
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
