import { problemOf } from "../api/hooks/query";
import { useSchemas } from "../api/hooks/schemas";
import { schemaVersionLabel } from "../api/schemas";
import { OptionSelect } from "./OptionSelect";
import { ProblemAlert } from "./ProblemAlert";

/** A required choice of one stored schema version, by id. */
export function SchemaSelect({
  label = "Schema",
  value,
  onChange,
}: Readonly<{ label?: string; value: string; onChange: (schemaId: string) => void }>) {
  const query = useSchemas();
  const problem = problemOf(query.error);
  const options = Object.fromEntries(
    (query.data ?? []).map((schema) => [schema.id, schemaVersionLabel(schema)]),
  );
  return (
    <>
      {problem === null ? null : <ProblemAlert problem={problem} />}
      <OptionSelect
        label={label}
        options={options}
        value={value === "" ? null : value}
        isRequired
        accepts={(key): key is string => typeof key === "string" && key in options}
        onChange={onChange}
      />
    </>
  );
}
