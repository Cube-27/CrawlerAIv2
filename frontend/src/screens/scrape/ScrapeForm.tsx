import {
  Button,
  Description,
  FieldError,
  Fieldset,
  Form,
  Input,
  Label,
  TextArea,
  TextField,
} from "@heroui/react";
import { Choices } from "../../components/Choices";
import { SchemaSelect } from "../../components/SchemaSelect";
import { FormActions } from "../../components/FormActions";
import { FormatChoices } from "../../components/FormatChoices";
import { LimitField } from "../../components/LimitField";
import { METHOD_HINTS, PAGE_KINDS } from "../../components/requestOptions";
import {
  NO_RECORDS_PAGE_KINDS,
  parseJsonObject,
  withFormats,
  type SchemaSource,
  type ScrapeFormState,
} from "./form";

const SCHEMA_SOURCES: readonly (readonly [SchemaSource, string])[] = [
  ["none", "None"],
  ["id", "Stored schema"],
  ["inline", "Inline JSON"],
  ["prompt", "From a prompt"],
];

/** The input for the chosen schema source: a stored schema, a SchemaDef as JSON, or a prompt for role S. */
function SchemaInput({
  form,
  onChange,
}: Readonly<{ form: ScrapeFormState; onChange: (form: ScrapeFormState) => void }>) {
  switch (form.schemaSource) {
    case "none":
      return null;
    case "id":
      return (
        <SchemaSelect
          label="Stored schema"
          value={form.schemaId}
          onChange={(schemaId) => {
            onChange({ ...form, schemaId });
          }}
        />
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
  const records = form.formats.includes("records");
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
      <FormatChoices
        value={form.formats}
        onChange={(formats) => {
          onChange(withFormats(form, formats));
        }}
      />
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
          isRequired={records}
          {...(records
            ? {
                disabled: NO_RECORDS_PAGE_KINDS,
                description: "Records of listing pages are not available yet.",
              }
            : {})}
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
