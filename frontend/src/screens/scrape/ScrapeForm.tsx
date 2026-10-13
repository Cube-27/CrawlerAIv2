import {
  Button,
  Checkbox,
  CheckboxGroup,
  Description,
  FieldError,
  Fieldset,
  Form,
  Input,
  Label,
  NumberField,
  TextArea,
  TextField,
} from "@heroui/react";
import { Choices } from "../../components/Choices";
import { FormActions } from "../../components/FormActions";
import type { MethodHint, PageKind } from "../../api/scrape";
import { FORMATS, parseJsonObject, type SchemaSource, type ScrapeFormState } from "./form";

const SCHEMA_SOURCES: readonly (readonly [SchemaSource, string])[] = [
  ["none", "None"],
  ["id", "Stored schema"],
  ["inline", "Inline JSON"],
  ["prompt", "From a prompt"],
];

const PAGE_KINDS: readonly (readonly [PageKind, string])[] = [
  ["detail", "Detail"],
  ["listing", "Listing"],
];

const METHOD_HINTS: readonly (readonly [MethodHint, string])[] = [
  ["auto", "Auto"],
  ["http", "HTTP"],
  ["browser", "Browser"],
];

function FormatChoices({
  form,
  onChange,
}: Readonly<{ form: ScrapeFormState; onChange: (form: ScrapeFormState) => void }>) {
  return (
    <CheckboxGroup
      value={[...form.formats]}
      onChange={(values) => {
        onChange({ ...form, formats: FORMATS.map(([f]) => f).filter((f) => values.includes(f)) });
      }}
    >
      <Label>Formats</Label>
      {FORMATS.map(([format, text]) => (
        <Checkbox key={format} value={format}>
          <Checkbox.Content>
            <Checkbox.Control>
              <Checkbox.Indicator />
            </Checkbox.Control>
            <Label>{text}</Label>
          </Checkbox.Content>
        </Checkbox>
      ))}
    </CheckboxGroup>
  );
}

/** The input for the chosen schema source: an id, a SchemaDef as JSON, or a prompt for role S. */
function SchemaInput({
  form,
  onChange,
}: Readonly<{ form: ScrapeFormState; onChange: (form: ScrapeFormState) => void }>) {
  switch (form.schemaSource) {
    case "none":
      return null;
    case "id":
      return (
        <TextField
          isRequired
          value={form.schemaId}
          onChange={(schemaId) => {
            onChange({ ...form, schemaId });
          }}
        >
          <Label>Schema ID</Label>
          <Input autoComplete="off" />
          <FieldError />
        </TextField>
      );
    case "inline":
      return (
        <TextField
          isRequired
          value={form.schemaJson}
          validate={(text) => (parseJsonObject(text) === null ? "Enter a JSON object." : null)}
          onChange={(schemaJson) => {
            onChange({ ...form, schemaJson });
          }}
        >
          <Label>Schema JSON</Label>
          <TextArea rows={6} />
          <Description>A SchemaDef; the server validates it.</Description>
          <FieldError />
        </TextField>
      );
    case "prompt":
      return (
        <TextField
          isRequired
          value={form.schemaPrompt}
          onChange={(schemaPrompt) => {
            onChange({ ...form, schemaPrompt });
          }}
        >
          <Label>Prompt</Label>
          <TextArea rows={3} />
          <Description>
            Describes the fields to extract; the server drafts a schema from it.
          </Description>
          <FieldError />
        </TextField>
      );
    default: {
      const exhaustive: never = form.schemaSource;
      return exhaustive;
    }
  }
}

/** A whole number of at least `minValue`; empty leaves the value to the server. */
function LimitField({
  label,
  name,
  value,
  minValue,
  maxValue,
  onChange,
}: Readonly<{
  label: string;
  name: string;
  value: number;
  minValue: number;
  maxValue?: number;
  onChange: (value: number) => void;
}>) {
  return (
    <NumberField
      name={name}
      value={value}
      minValue={minValue}
      {...(maxValue === undefined ? {} : { maxValue })}
      formatOptions={{ maximumFractionDigits: 0, useGrouping: false }}
      onChange={onChange}
    >
      <Label>{label}</Label>
      <NumberField.Group>
        <NumberField.DecrementButton />
        <NumberField.Input />
        <NumberField.IncrementButton />
      </NumberField.Group>
      <Description>Empty: the server default.</Description>
      <FieldError />
    </NumberField>
  );
}

function LimitFields({
  form,
  onChange,
}: Readonly<{ form: ScrapeFormState; onChange: (form: ScrapeFormState) => void }>) {
  return (
    <Fieldset>
      <Fieldset.Legend>Fetch and limits</Fieldset.Legend>
      <Choices
        label="Fetch method"
        options={METHOD_HINTS}
        value={form.methodHint}
        onChange={(methodHint) => {
          onChange({ ...form, methodHint });
        }}
      />
      <LimitField
        label="Max age (seconds)"
        name="max_age"
        value={form.maxAge}
        minValue={0}
        onChange={(maxAge) => {
          onChange({ ...form, maxAge });
        }}
      />
      {/* SPEC-07 §4.4: the request is bounded by `timeout_s`, at most 120. */}
      <LimitField
        label="Timeout (seconds)"
        name="timeout_s"
        value={form.timeoutS}
        minValue={1}
        maxValue={120}
        onChange={(timeoutS) => {
          onChange({ ...form, timeoutS });
        }}
      />
      <LimitField
        label="LLM call budget"
        name="budget"
        value={form.llmCalls}
        minValue={0}
        onChange={(llmCalls) => {
          onChange({ ...form, llmCalls });
        }}
      />
    </Fieldset>
  );
}

/** The `POST /v1/scrape` request (SPEC-07 §4.4). The server validates it; the form checks only what it must hold to
 * be sent. `serverErrors` are the last problem's per-field errors, keyed by input name. */
export function ScrapeForm({
  form,
  isPending,
  serverErrors,
  onChange,
  onSubmit,
}: Readonly<{
  form: ScrapeFormState;
  isPending: boolean;
  serverErrors: Readonly<Record<string, string>>;
  onChange: (form: ScrapeFormState) => void;
  onSubmit: () => void;
}>) {
  return (
    <Form
      className="flex flex-col gap-4"
      validationErrors={serverErrors}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <TextField
        isRequired
        type="url"
        name="url"
        value={form.url}
        onChange={(url) => {
          onChange({ ...form, url });
        }}
      >
        <Label>URL</Label>
        <Input autoComplete="off" />
        <FieldError />
      </TextField>
      <FormatChoices form={form} onChange={onChange} />
      <Fieldset>
        <Fieldset.Legend>Extraction</Fieldset.Legend>
        <Choices
          label="Schema"
          options={SCHEMA_SOURCES}
          value={form.schemaSource}
          onChange={(schemaSource) => {
            onChange({ ...form, schemaSource });
          }}
        />
        <SchemaInput form={form} onChange={onChange} />
        {/* SPEC-07 §4.4: `page_kind` is required when the formats include records. */}
        <Choices
          label="Page kind"
          options={PAGE_KINDS}
          value={form.pageKind}
          isRequired={form.formats.includes("records")}
          onChange={(pageKind) => {
            onChange({ ...form, pageKind });
          }}
        />
      </Fieldset>
      <LimitFields form={form} onChange={onChange} />
      <FormActions>
        <Button type="submit" isPending={isPending}>
          Scrape
        </Button>
      </FormActions>
    </Form>
  );
}
