import type { PageKind } from "../../../api/scrape";
import { NumberRow, OptionsPanel } from "../OptionsPanel";
import { FetchMethodRow, FieldsRow, MetadataRow, ScopeRows, WebhookRow } from "../rows";
import { DEFAULT_CRAWL_OPTIONS, type CrawlOptions as Options } from "./form";
import { RuleRows } from "./RuleRows";

function AdvancedRows({
  options,
  onChange,
}: Readonly<{ options: Options; onChange: (options: Options) => void }>) {
  return (
    <>
      <NumberRow
        label="Max depth"
        help="How many links away from the start URL the crawl goes. Empty: the server default."
        name="max_depth"
        value={options.maxDepth}
        minValue={0}
        onChange={(maxDepth) => {
          onChange({ ...options, maxDepth });
        }}
      />
      <NumberRow
        label="Page limit"
        help="The most pages the crawl visits. Empty: the server default."
        name="limit"
        value={options.limit}
        minValue={1}
        onChange={(limit) => {
          onChange({ ...options, limit });
        }}
      />
      <FetchMethodRow
        value={options.methodHint}
        onChange={(methodHint) => {
          onChange({ ...options, methodHint });
        }}
      />
      <WebhookRow
        value={options.webhookUrl}
        onChange={(webhookUrl) => {
          onChange({ ...options, webhookUrl });
        }}
      />
    </>
  );
}

/** Crawl's options panel (SPEC-14 §4.2): the scope globs, Metadata in JSON, fields (§4.10) and the page-kind rules,
 * then depth, page limit, fetch method and webhook under Advanced. With a schema, every rule is for its page kind, `schemaPageKind`. */
export function CrawlOptions({
  options,
  schemaPageKind,
  rulesError,
  onChange,
}: Readonly<{
  options: Options;
  schemaPageKind: PageKind | null;
  rulesError: string | undefined;
  onChange: (options: Options) => void;
}>) {
  return (
    <OptionsPanel
      advanced={<AdvancedRows options={options} onChange={onChange} />}
      onReset={() => {
        onChange(DEFAULT_CRAWL_OPTIONS);
      }}
    >
      <ScopeRows
        include={options.include}
        exclude={options.exclude}
        onChange={(scope) => {
          onChange({ ...options, ...scope });
        }}
      />
      <MetadataRow
        isSelected={options.metadataInJson}
        onChange={(metadataInJson) => {
          onChange({ ...options, metadataInJson });
        }}
      />
      <FieldsRow
        values={options.fields}
        onChange={(fields) => {
          onChange({ ...options, fields });
        }}
      />
      <RuleRows
        rules={options.rules}
        fixed={schemaPageKind}
        error={rulesError}
        onChange={(rules) => {
          onChange({ ...options, rules });
        }}
      />
    </OptionsPanel>
  );
}
