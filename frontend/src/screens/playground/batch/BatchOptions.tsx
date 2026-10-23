import { AdvancedRows } from "../AdvancedRows";
import type { PageKind, ScrapeFormat } from "../../../api/scrape";
import { OptionsPanel } from "../OptionsPanel";
import { LlmCallsRow, PageFetchRows, PageOutputRows, WebhookRows } from "../rows";
import { DEFAULT_BATCH_OPTIONS, type BatchOptions as Options } from "./form";

/** Batch's options: page kind, fetch method, the LLM call limit, Metadata in JSON, fields and
 * the webhook. */
export function BatchOptions({
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
        onChange(DEFAULT_BATCH_OPTIONS);
      }}
    >
      <PageFetchRows
        options={options}
        hasSchema={hasSchema}
        schemaPageKind={schemaPageKind}
        onChange={onChange}
      />
      <LlmCallsRow
        value={options.llmCalls}
        help="The most LLM calls the whole batch may make. Empty: the project's limit in Settings."
        onChange={(llmCalls) => {
          onChange({ ...options, llmCalls });
        }}
      />
      <PageOutputRows options={options} formats={formats} onChange={onChange} />
      <WebhookRows
        value={options.webhook}
        onChange={(webhook) => {
          onChange({ ...options, webhook });
        }}
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
