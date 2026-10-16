import type { PageKind } from "../../../api/scrape";
import { NumberRow, OptionsPanel } from "../OptionsPanel";
import { FetchMethodRow, FieldsRow, MetadataRow, PageKindRow } from "../rows";
import { DEFAULT_OPTIONS, type ScrapeOptions as Options } from "./form";

function AdvancedRows({
  options,
  onChange,
}: Readonly<{ options: Options; onChange: (options: Options) => void }>) {
  return (
    <>
      <FetchMethodRow
        value={options.methodHint}
        onChange={(methodHint) => {
          onChange({ ...options, methodHint });
        }}
      />
      <NumberRow
        label="Max age (seconds)"
        help="Reuse a capture of the page this recent instead of fetching it again. Empty: the server default."
        name="max_age"
        value={options.maxAge}
        minValue={0}
        onChange={(maxAge) => {
          onChange({ ...options, maxAge });
        }}
      />
      {/* SPEC-07 §4.4: the request is bounded by `timeout_s`, at most 120. */}
      <NumberRow
        label="Timeout (seconds)"
        help="How long the scrape may take, at most 120. Empty: the server default."
        name="timeout_s"
        value={options.timeoutS}
        minValue={1}
        maxValue={120}
        onChange={(timeoutS) => {
          onChange({ ...options, timeoutS });
        }}
      />
      <NumberRow
        label="LLM call budget"
        help="The most LLM calls this scrape may make. Empty: the server default."
        name="budget.llm_calls"
        value={options.llmCalls}
        minValue={0}
        onChange={(llmCalls) => {
          onChange({ ...options, llmCalls });
        }}
      />
    </>
  );
}

/** Scrape's options panel (SPEC-14 §4.2): page kind, Metadata in JSON and fields (§4.10), then fetch and limits under
 * Advanced. */
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
      advanced={<AdvancedRows options={options} onChange={onChange} />}
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
