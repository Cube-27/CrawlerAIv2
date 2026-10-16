import type { PageKind } from "../../../api/scrape";
import { OptionsPanel } from "../OptionsPanel";
import {
  FetchMethodRow,
  FieldsRow,
  LlmCallsRow,
  MetadataRow,
  PageKindRow,
  WebhookRow,
} from "../rows";
import { DEFAULT_BATCH_OPTIONS, type BatchOptions as Options } from "./form";

/** Batch's options (SPEC-14 §4.2): page kind, fetch method, the LLM call limit, Metadata in JSON, fields (§4.10) and
 * the webhook. */
export function BatchOptions({
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
        onChange(DEFAULT_BATCH_OPTIONS);
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
      {/* D-1006: a batch without a `budget` makes as many LLM calls as its pages need. */}
      <LlmCallsRow
        value={options.llmCalls}
        whenEmpty="No limit"
        help="The most LLM calls the whole batch may make. Empty: no limit."
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
      <WebhookRow
        value={options.webhookUrl}
        onChange={(webhookUrl) => {
          onChange({ ...options, webhookUrl });
        }}
      />
    </OptionsPanel>
  );
}
