import type { PageKind } from "../../../api/scrape";
import { OptionsPanel } from "../OptionsPanel";
import { FetchMethodRow, FieldsRow, MetadataRow, PageKindRow, WebhookRow } from "../rows";
import { DEFAULT_BATCH_OPTIONS, type BatchOptions as Options } from "./form";

/** Batch's options panel (SPEC-14 §4.2): page kind, Metadata in JSON, fields (§4.10) and the webhook, then the fetch method under
 * Advanced. */
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
      advanced={
        <FetchMethodRow
          value={options.methodHint}
          onChange={(methodHint) => {
            onChange({ ...options, methodHint });
          }}
        />
      }
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
