import {
  Description,
  FieldError,
  Fieldset,
  Input,
  Label,
  TextArea,
  TextField,
} from "@heroui/react";
import { Choices } from "../../components/Choices";
import { SchemaSelect } from "../../components/SchemaSelect";
import { parseJsonObject } from "../scrape/form";
import type { JobSchemaSource, JobSchemaState } from "./form";

/** Inputs the job forms share. */

const SCHEMA_SOURCES: readonly (readonly [JobSchemaSource, string])[] = [
  ["none", "None"],
  ["id", "Stored schema"],
  ["inline", "Inline JSON"],
];

/** The job's schema: none, a stored version, or a SchemaDef as JSON (the server validates it). */
export function JobSchemaFields({
  value,
  onChange,
}: Readonly<{ value: JobSchemaState; onChange: (schema: JobSchemaState) => void }>) {
  return (
    <Fieldset>
      <Fieldset.Legend>Extraction</Fieldset.Legend>
      <Choices
        label="Schema"
        options={SCHEMA_SOURCES}
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
