import { AdvancedRows } from "../AdvancedRows";
import type { PageKind, ScrapeFormat } from "../../../api/scrape";
import type { CrawlStrategy } from "../../../api/jobs";
import {
  NumberRow,
  OptionsPanel,
  SelectRow,
  SwitchRow,
  TagListRow,
  TextRow,
} from "../OptionsPanel";
import {
  FetchMethodRow,
  MaxRowsRow,
  MinConfidenceRow,
  FieldsRow,
  FormatRows,
  MetadataRow,
  ScopeRows,
  WebhookRows,
} from "../rows";
import { DEFAULT_CRAWL_OPTIONS, type CrawlOptions as Options } from "./form";
import { RuleRows } from "./RuleRows";

const STRATEGIES: readonly (readonly [CrawlStrategy, string])[] = [
  ["bfs", "Breadth first"],
  ["dfs", "Depth first"],
  ["best_first", "Best first"],
];

/** Crawl's options (frontend spec): the scope globs; max depth, page limit, fetch method and Metadata in JSON; fields
 * (§4.10) and the webhook; then the page-kind rules. With a schema, every rule is for its page kind,
 * `schemaPageKind`. `CrawlRequest` has no `budget`: the project's LLM call limit (Settings) bounds a crawl. */
export function CrawlOptions({
  options,
  formats,
  schemaPageKind,
  rulesError,
  onChange,
}: Readonly<{
  options: Options;
  formats: readonly ScrapeFormat[];
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
      <SelectRow<CrawlStrategy>
        label="Strategy"
        help="The order pages are visited in: breadth first, depth first, or best first, which visits the links that best match the query first."
        name="strategy"
        options={STRATEGIES}
        value={options.strategy}
        onChange={(strategy) => {
          onChange({ ...options, strategy });
        }}
      />
      <TextRow
        label="Query"
        help="Best first only: the words that rank links, by their text and URL path."
        name="query"
        value={options.query}
        placeholder="Words the pages you want are about"
        onChange={(query) => {
          onChange({ ...options, query });
        }}
      />
      <TagListRow
        label="Keywords"
        help="Best first only: more words that rank links, each added on its own."
        name="keywords"
        values={options.keywords}
        placeholder="A word the pages you want contain"
        onChange={(keywords) => {
          onChange({ ...options, keywords });
        }}
      />
      <SwitchRow
        label="Include subdomains"
        help="Also follows links to subdomains of the start host."
        isSelected={options.allowSubdomains}
        onChange={(allowSubdomains) => {
          onChange({ ...options, allowSubdomains });
        }}
      />
      <SwitchRow
        label="Follow external links"
        help="Also follows links to other hosts; the include and exclude globs still apply."
        isSelected={options.allowExternal}
        onChange={(allowExternal) => {
          onChange({ ...options, allowExternal });
        }}
      />
      <FetchMethodRow
        value={options.methodHint}
        onChange={(methodHint) => {
          onChange({ ...options, methodHint });
        }}
      />
      <MaxRowsRow
        value={options.maxRows}
        onChange={(maxRows) => {
          onChange({ ...options, maxRows });
        }}
      />
      <MinConfidenceRow options={options} onChange={onChange} />
      <MetadataRow
        isSelected={options.metadataInJson}
        onChange={(metadataInJson) => {
          onChange({ ...options, metadataInJson });
        }}
      />
      <FieldsRow options={options} onChange={onChange} />
      <FormatRows options={options} formats={formats} onChange={onChange} />
      <WebhookRows
        value={options.webhook}
        onChange={(webhook) => {
          onChange({ ...options, webhook });
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
      <AdvancedRows
        value={options.advanced}
        onChange={(advanced) => {
          onChange({ ...options, advanced });
        }}
      />
    </OptionsPanel>
  );
}
