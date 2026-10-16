import type { PageKind } from "../../../api/scrape";
import { NumberRow, OptionsPanel } from "../OptionsPanel";
import { FetchMethodRow, FieldsRow, MetadataRow, ScopeRows, WebhookRow } from "../rows";
import { DEFAULT_CRAWL_OPTIONS, type CrawlOptions as Options } from "./form";
import { RuleRows } from "./RuleRows";

/** Crawl's options (SPEC-14 §4.2): the scope globs; max depth, page limit, fetch method and Metadata in JSON; fields
 * (§4.10) and the webhook; then the page-kind rules. With a schema, every rule is for its page kind,
 * `schemaPageKind`. `CrawlRequest` has no `budget`: the project's LLM call limit (Settings) bounds a crawl. */
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
