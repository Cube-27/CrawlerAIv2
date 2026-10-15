import type { MethodHint, PageKind } from "../../../api/scrape";
import { METHOD_HINTS, PAGE_KINDS } from "../../../components/requestOptions";
import { NumberRow, OptionsPanel, SelectRow, SwitchRow } from "../OptionsPanel";
import { DEFAULT_OPTIONS, type ScrapeOptions as Options } from "./form";

function AdvancedRows({
  options,
  onChange,
}: Readonly<{ options: Options; onChange: (options: Options) => void }>) {
  return (
    <>
      <SelectRow<MethodHint>
        label="Fetch method"
        help="How the page is fetched. Auto starts with HTTP and moves to a browser when the page needs one."
        name="fetch.method_hint"
        options={METHOD_HINTS}
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

/** Scrape's options panel (SPEC-14 §4.2): page kind and Metadata in JSON, then fetch and limits under Advanced. With a
 * schema, the page kind is the one its records can be for, `schemaPageKind`, or none (SPEC-07 §4.4). */
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
      <SelectRow<PageKind>
        label="Page kind"
        help="Whether the page shows one item or a list of items. With a schema, it is the schema's; records of listing pages are not available yet."
        name="page_kind"
        options={PAGE_KINDS}
        value={hasSchema ? schemaPageKind : options.pageKind}
        placeholder="Not set"
        disabled={
          hasSchema
            ? PAGE_KINDS.map(([kind]) => kind).filter((kind) => kind !== schemaPageKind)
            : []
        }
        onChange={(pageKind) => {
          onChange({ ...options, pageKind });
        }}
      />
      <SwitchRow
        label="Metadata in JSON"
        help="Adds the page's metadata (title, description, language, canonical URL) to the output."
        isSelected={options.metadataInJson}
        onChange={(metadataInJson) => {
          onChange({ ...options, metadataInJson });
        }}
      />
    </OptionsPanel>
  );
}
