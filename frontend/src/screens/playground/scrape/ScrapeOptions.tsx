import type { PageKind } from "../../../api/scrape";
import { NumberRow, OptionsPanel } from "../OptionsPanel";
import { FetchMethodRow, FieldsRow, LlmCallsRow, MetadataRow, PageKindRow } from "../rows";
import { DEFAULT_OPTIONS, type ScrapeOptions as Options } from "./form";

/** Scrape's options (SPEC-14 §4.2): page kind, fetch method, max age, timeout, the LLM call limit, Metadata in JSON
 * and fields (§4.10). */
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
      {/* SPEC-07 §4.4: a scrape's `budget.llm_calls` defaults to 10. */}
      <LlmCallsRow
        value={options.llmCalls}
        whenEmpty="10"
        help="The most LLM calls this scrape may make. Empty: 10, the server default."
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
    </OptionsPanel>
  );
}
