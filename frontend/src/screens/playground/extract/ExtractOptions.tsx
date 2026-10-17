import type { PageKind } from "../../../api/scrape";
import { NumberRow, OptionsPanel, TagListRow, TextAreaRow } from "../OptionsPanel";
import {
  FetchMethodRow,
  MaxRowsRow,
  FieldsRow,
  LlmCallsRow,
  PageKindRow,
  WebhookRow,
} from "../rows";
import { DEFAULT_EXTRACT_OPTIONS, type ExtractOptions as Options, type SchemaSource } from "./form";

type Change = (options: Options) => void;

/** The inline schema's JSON, the prompt or the field names, for the source that has one. */
function SourceRow({
  source,
  options,
  onChange,
}: Readonly<{ source: SchemaSource; options: Options; onChange: Change }>) {
  if (source === "fields") return <FieldsRow options={options} onChange={onChange} />;
  if (source === "inline")
    return (
      <TextAreaRow
        label="Schema JSON"
        help="A SchemaDef; the server validates it."
        name="inline_schema"
        value={options.inlineSchema}
        placeholder='{"name": "…", "page_kind": "detail", "fields": {…}}'
        onChange={(inlineSchema) => {
          onChange({ ...options, inlineSchema });
        }}
      />
    );
  if (source === "prompt")
    return (
      <TextAreaRow
        label="Prompt"
        help="Describes the fields to extract; the server drafts a schema from the first pages."
        name="prompt"
        value={options.prompt}
        placeholder="The title, price and availability of each item"
        onChange={(prompt) => {
          onChange({ ...options, prompt });
        }}
      />
    );
  return null;
}

/** Extract's options (SPEC-14 §4.2): more URLs or globs and the page kind; page limit, fetch method, the LLM call
 * limit and the webhook; then the JSON, prompt or field names of the toolbar's schema `source`. A stored schema's page
 * kind is its own, `schemaPageKind`. */
export function ExtractOptions({
  source,
  options,
  schemaPageKind,
  onChange,
}: Readonly<{
  source: SchemaSource;
  options: Options;
  schemaPageKind: PageKind | null;
  onChange: Change;
}>) {
  const stored = source === "id";
  return (
    <OptionsPanel
      onReset={() => {
        onChange(DEFAULT_EXTRACT_OPTIONS);
      }}
    >
      <TagListRow
        label="More URLs"
        help="URLs or globs read after the bar's; a URL with * is a glob over its site's map."
        name="urls"
        values={options.urls}
        placeholder="https://example.com/items/*"
        onChange={(urls) => {
          onChange({ ...options, urls });
        }}
      />
      <PageKindRow
        value={options.pageKind}
        hasSchema={stored}
        schemaPageKind={schemaPageKind}
        onChange={(pageKind) => {
          onChange({ ...options, pageKind });
        }}
      />
      <NumberRow
        label="Page limit"
        help="The most pages the extract reads, globs expanded. Empty: the server default."
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
      <MaxRowsRow
        value={options.maxRows}
        onChange={(maxRows) => {
          onChange({ ...options, maxRows });
        }}
      />
      {/* SPEC-10 §4.6: an extract's `budget.llm_calls` bounds a prompt's draft. */}
      <LlmCallsRow
        value={options.llmCalls}
        help="The most LLM calls drafting a schema from the prompt may make. Empty: the project's limit in Settings."
        onChange={(llmCalls) => {
          onChange({ ...options, llmCalls });
        }}
      />
      <WebhookRow
        value={options.webhookUrl}
        onChange={(webhookUrl) => {
          onChange({ ...options, webhookUrl });
        }}
      />
      <SourceRow source={source} options={options} onChange={onChange} />
    </OptionsPanel>
  );
}
