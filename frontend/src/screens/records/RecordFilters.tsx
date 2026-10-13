import {
  Button,
  Description,
  FieldError,
  Form,
  Input,
  Label,
  ListBox,
  Select,
  TextField,
} from "@heroui/react";
import { useState, type Key } from "react";
import { problemOf } from "../../api/hooks/query";
import { useSchemas } from "../../api/hooks/schemas";
import type { RecordFilters } from "../../api/records";
import { FormActions } from "../../components/FormActions";
import { ProblemAlert } from "../../components/ProblemAlert";

function SchemaSelect({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (schemaId: string) => void }>) {
  const query = useSchemas();
  const problem = problemOf(query.error);
  return (
    <>
      {problem === null ? null : <ProblemAlert problem={problem} />}
      <Select
        isRequired
        value={value === "" ? null : value}
        onChange={(key: Key | null) => {
          if (typeof key === "string") onChange(key);
        }}
      >
        <Label>Schema</Label>
        <Select.Trigger>
          <Select.Value />
          <Select.Indicator />
        </Select.Trigger>
        <Description>The table has a column for each of its fields.</Description>
        <Select.Popover>
          <ListBox items={query.data ?? []}>
            {({ id, name, version }) => {
              const text = `${name} version ${String(version)}`;
              return (
                <ListBox.Item id={id} textValue={text}>
                  {text}
                  <ListBox.ItemIndicator />
                </ListBox.Item>
              );
            }}
          </ListBox>
        </Select.Popover>
        <FieldError />
      </Select>
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
  return (
    <Form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(draft);
      }}
    >
      <SchemaSelect
        value={draft.schema_id}
        onChange={(schema_id) => {
          setDraft({ ...draft, schema_id });
        }}
      />
      <OptionalText
        label="Job ID"
        description="Only the records this job extracted."
        value={draft.job_id}
        onChange={(job_id) => {
          setDraft({ ...draft, job_id });
        }}
      />
      <OptionalText
        label="Site"
        description="Only the records of this host."
        value={draft.site}
        onChange={(site) => {
          setDraft({ ...draft, site });
        }}
      />
      <FormActions>
        <Button type="submit">Show records</Button>
      </FormActions>
    </Form>
  );
}
