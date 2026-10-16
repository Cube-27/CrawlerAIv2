import type { PageKind } from "../../../api/scrape";
import { NumberRow, OptionsPanel, SelectRow, TagListRow, TextAreaRow } from "../OptionsPanel";
import { FetchMethodRow, FieldsRow, PageKindRow, WebhookRow } from "../rows";
import { DEFAULT_EXTRACT_OPTIONS, type ExtractOptions as Options, type SchemaSource } from "./form";

const SCHEMA_SOURCES: readonly (readonly [SchemaSource, string])[] = [
  ["id", "Stored schema"],
  ["inline", "Inline JSON"],
  ["prompt", "From a prompt"],
  ["fields", "From field names"],
];

type Change = (options: Options) => void;

function AdvancedRows({ options, onChange }: Readonly<{ options: Options; onChange: Change }>) {
  return (
    <>
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
      <NumberRow
        label="LLM call budget"
        help="The most LLM calls drafting a schema from the prompt may make. Empty: the server default."
        name="budget.llm_calls"
        value={options.llmCalls}
        minValue={0}
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
    </>
  );
}

/** The inline schema's JSON, the prompt or the field names, for the source that has one. */
function SourceRow({ options, onChange }: Readonly<{ options: Options; onChange: Change }>) {
  if (options.schemaSource === "fields") return <FieldsRow options={options} onChange={onChange} />;
  if (options.schemaSource === "inline")
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
  if (options.schemaSource === "prompt")
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

/** Extract's options panel (SPEC-14 §4.2): more URLs or globs, the schema's source and page kind, then page limit,
 * fetch method, LLM budget and webhook under Advanced. A stored schema's page kind is its own, `schemaPageKind`. */
export function ExtractOptions({
  options,
  schemaPageKind,
  onChange,
}: Readonly<{
  options: Options;
  schemaPageKind: PageKind | null;
  onChange: Change;
}>) {
  const stored = options.schemaSource === "id";
  return (
    <OptionsPanel
      advanced={<AdvancedRows options={options} onChange={onChange} />}
      onReset={() => {
        onChange(DEFAULT_EXTRACT_OPTIONS);
      }}
    >
      <TagListRow
        label="More URLs or globs"
        help="URLs read after the bar's; a URL with * is a glob over its site's map."
        name="urls"
        values={options.urls}
        placeholder="https://example.com/items/*"
        onChange={(urls) => {
          onChange({ ...options, urls });
        }}
      />
      <SelectRow<SchemaSource>
        label="Schema source"
        help="A stored schema (the toolbar's Schema), a SchemaDef as JSON, or a schema drafted from a prompt or from field names."
        name="schema"
        options={SCHEMA_SOURCES}
        value={options.schemaSource}
        onChange={(schemaSource) => {
          onChange({ ...options, schemaSource });
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
      <SourceRow options={options} onChange={onChange} />
    </OptionsPanel>
  );
}
