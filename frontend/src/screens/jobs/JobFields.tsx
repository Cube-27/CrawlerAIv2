import {
  Description,
  FieldError,
  Fieldset,
  Input,
  Label,
  TextArea,
  TextField,
} from "@heroui/react";
import type { MethodHint } from "../../api/scrape";
import { Choices } from "../../components/Choices";
import { METHOD_HINTS } from "../../components/requestOptions";
import { SchemaSelect } from "../../components/SchemaSelect";
import { parseJsonObject } from "../scrape/form";
import type { SchemaSource } from "../scrape/form";
import type { JobSchemaState } from "./form";

/** Inputs the job forms share. */

type SchemaSources = readonly (readonly [SchemaSource, string])[];

/** A batch's or crawl's schema sources: they take no prompt. */
const JOB_SCHEMA_SOURCES: SchemaSources = [
  ["none", "None"],
  ["id", "Stored schema"],
  ["inline", "Inline JSON"],
];

/** An extract's: it needs a schema, and may have one drafted from a prompt (SPEC-10 §4.6). */
export const EXTRACT_SCHEMA_SOURCES: SchemaSources = [
  ["id", "Stored schema"],
  ["inline", "Inline JSON"],
  ["prompt", "From a prompt"],
];

/** The job's schema from one of `sources`: a stored version, a SchemaDef as JSON (the server validates it), or a
 * prompt the server drafts one from. */
export function JobSchemaFields({
  sources = JOB_SCHEMA_SOURCES,
  value,
  onChange,
}: Readonly<{
  sources?: SchemaSources;
  value: JobSchemaState;
  onChange: (schema: JobSchemaState) => void;
}>) {
  return (
    <Fieldset>
      <Fieldset.Legend>Extraction</Fieldset.Legend>
      <Choices
        label="Schema"
        options={sources}
        value={value.source}
        onChange={(source) => {
          onChange({ ...value, source });
        }}
      />
      {value.source === "id" ? (
        <SchemaSelect
          value={value.id}
          onChange={(id) => {
            onChange({ ...value, id });
          }}
        />
      ) : null}
      {value.source === "inline" ? (
        <TextField
          isRequired
          value={value.json}
          validate={(text) => (parseJsonObject(text) === null ? "Enter a JSON object." : null)}
          onChange={(json) => {
            onChange({ ...value, json });
          }}
        >
          <Label>Schema JSON</Label>
          <TextArea rows={6} />
          <Description>A SchemaDef; the server validates it.</Description>
          <FieldError />
        </TextField>
      ) : null}
      {value.source === "prompt" ? (
        <TextField
          isRequired
          value={value.prompt}
          onChange={(prompt) => {
            onChange({ ...value, prompt });
          }}
        >
          <Label>Prompt</Label>
          <TextArea rows={3} />
          <Description>
            Describes the fields to extract; the server drafts a schema from the first pages.
          </Description>
          <FieldError />
        </TextField>
      ) : null}
    </Fieldset>
  );
}

/** A list entered one entry per line; `name` is the request member a server error names. */
export function LinesField({
  label,
  name,
  description,
  value,
  isRequired = false,
  onChange,
}: Readonly<{
  label: string;
  name: string;
  description: string;
  value: string;
  isRequired?: boolean;
  onChange: (value: string) => void;
}>) {
  return (
    <TextField name={name} isRequired={isRequired} value={value} onChange={onChange}>
      <Label>{label}</Label>
      <TextArea rows={4} spellCheck={false} />
      <Description>{description}</Description>
      <FieldError />
    </TextField>
  );
}

/** A required absolute URL. */
export function UrlField({
  label = "URL",
  name,
  value,
  isRequired = true,
  onChange,
}: Readonly<{
  label?: string;
  name: string;
  value: string;
  isRequired?: boolean;
  onChange: (value: string) => void;
}>) {
  return (
    <TextField isRequired={isRequired} type="url" name={name} value={value} onChange={onChange}>
      <Label>{label}</Label>
      <Input autoComplete="off" />
      <FieldError />
    </TextField>
  );
}

/** How a job's pages are fetched, and where its end is sent (`webhook_url`, optional). */
export function FetchFields({
  methodHint,
  webhookUrl,
  onChange,
}: Readonly<{
  methodHint: MethodHint;
  webhookUrl: string;
  onChange: (change: { methodHint?: MethodHint; webhookUrl?: string }) => void;
}>) {
  return (
    <Fieldset>
      <Fieldset.Legend>Fetch and notification</Fieldset.Legend>
      <Choices
        label="Fetch method"
        options={METHOD_HINTS}
        value={methodHint}
        onChange={(next) => {
          onChange({ methodHint: next });
        }}
      />
      <UrlField
        label="Webhook URL"
        name="webhook_url"
        isRequired={false}
        value={webhookUrl}
        onChange={(next) => {
          onChange({ webhookUrl: next });
        }}
      />
    </Fieldset>
  );
}
