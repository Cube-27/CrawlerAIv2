import { Button, Description, Form, Input, Label, TextField } from "@heroui/react";
import { useState } from "react";
import { problemOf } from "../../api/hooks/query";
import { useSchemas } from "../../api/hooks/schemas";
import type { RecordFilters } from "../../api/records";
import { schemaVersionLabel } from "../../api/schemas";
import { FormActions } from "../../components/FormActions";
import { OptionSelect } from "../../components/OptionSelect";
import { ProblemAlert } from "../../components/ProblemAlert";

function SchemaSelect({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (schemaId: string) => void }>) {
  const query = useSchemas();
  const problem = problemOf(query.error);
  const options = Object.fromEntries(
    (query.data ?? []).map((schema) => [schema.id, schemaVersionLabel(schema)]),
  );
  return (
    <>
      {problem === null ? null : <ProblemAlert problem={problem} />}
      <OptionSelect
        label="Schema"
        options={options}
        value={value === "" ? null : value}
        isRequired
        accepts={(key): key is string => typeof key === "string" && key in options}
        onChange={onChange}
      />
    </>
  );
}

function OptionalText({
  label,
  description,
  value,
  onChange,
}: Readonly<{
  label: string;
  description: string;
  value: string;
  onChange: (value: string) => void;
}>) {
  return (
    <TextField value={value} onChange={onChange}>
      <Label>{label}</Label>
      <Input autoComplete="off" />
      <Description>{description}</Description>
    </TextField>
  );
}

/** The `GET /v1/records` filters (SPEC-07 §4.6). The schema is required; the others narrow the list when given. */
export function RecordFiltersForm({
  filters,
  onSubmit,
}: Readonly<{ filters: RecordFilters; onSubmit: (filters: RecordFilters) => void }>) {
  const [draft, setDraft] = useState(filters);
  const set = (name: keyof RecordFilters) => (value: string) => {
    setDraft({ ...draft, [name]: value });
  };
  return (
    <Form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(draft);
      }}
    >
      <SchemaSelect value={draft.schema_id} onChange={set("schema_id")} />
      <OptionalText
        label="Job ID"
        description="Only the records this job extracted."
        value={draft.job_id}
        onChange={set("job_id")}
      />
      <OptionalText
        label="Site"
        description="Only the records of this host."
        value={draft.site}
        onChange={set("site")}
      />
      <FormActions>
        <Button type="submit">Show records</Button>
      </FormActions>
    </Form>
  );
}
