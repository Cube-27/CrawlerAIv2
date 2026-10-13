import { toast } from "@heroui/react";
import { useCallback, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import type { Problem } from "../../api/problem";
import type { ApiResult } from "../../api/result";
import { createSchema, getSchema, updateSchema, type SchemaDef } from "../../api/schemas";
import { useApiQuery } from "../../api/useApiQuery";
import { useApiClient } from "../../app/auth";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { schemaPath } from "./paths";
import { SchemaForm } from "../../components/SchemaForm";
import {
  contentOf,
  EMPTY_FORM,
  formOf,
  newSchemaOf,
  type FormMode,
  type SchemaFormState,
} from "../../components/schemaDocument";

/** Sends `form`, or returns null when it has no request yet (no page kind). */
type Save = (form: SchemaFormState) => Promise<ApiResult<SchemaDef>> | null;

/** A schema form that saves through `save` and then opens the version the server stored. */
function SchemaEditor({
  title,
  mode,
  initial,
  save,
  cancelTo,
}: Readonly<{
  title: string;
  mode: FormMode;
  /** The schema the form starts from; null for a blank one. */
  initial: SchemaDef | null;
  save: Save;
  cancelTo: string;
}>) {
  const navigate = useNavigate();
  const [form, setForm] = useState(() => (initial === null ? EMPTY_FORM : formOf(initial)));
  const [isPending, setPending] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);

  const submit = (current: SchemaFormState) => {
    const saving = save(current);
    if (saving === null) return;
    setProblem(null);
    setPending(true);
    void saving.then((result) => {
      setPending(false);
      if (result.kind === "failed") {
        setProblem(result.problem);
        return;
      }
      const { id, name, version } = result.value;
      toast.success(`Saved ${name} version ${String(version)}.`);
      void navigate(schemaPath(id));
    });
  };

  return (
    <section className="flex flex-col gap-6">
      <PageHeader title={title} />
      <SchemaForm
        form={form}
        mode={mode}
        problem={problem}
        isPending={isPending}
        onChange={setForm}
        onSubmit={submit}
        onCancel={() => void navigate(cancelTo)}
      />
    </section>
  );
}

const NO_DRAFT: ApiResult<null> = { kind: "done", value: null };

/** A new `user` schema (SPEC-12 §4.3), blank or, with `?from=<id>`, prefilled from that schema: adopting a prompt
 * draft creates a user schema from its document. */
export function NewSchemaScreen() {
  const client = useApiClient();
  const from = useSearchParams()[0].get("from");
  const [query] = useApiQuery(
    useCallback(
      (): Promise<ApiResult<SchemaDef | null>> =>
        from === null ? Promise.resolve(NO_DRAFT) : getSchema(client, from),
      [client, from],
    ),
  );
  const save: Save = (form) => {
    const body = newSchemaOf(form);
    return body === null ? null : createSchema(client, body);
  };

  if (query.kind === "loading") return <LoadingView label="Loading the schema" />;
  if (query.kind === "failed") return <ProblemAlert problem={query.problem} />;
  const source = query.value;
  return (
    <SchemaEditor
      title="New schema"
      mode="create"
      initial={source}
      save={save}
      cancelTo={source === null ? "/schemas" : schemaPath(source.id)}
    />
  );
}

/** The next version of a schema: its whole document, edited; the name stays (SPEC-07 §4.6). */
export function EditSchemaScreen() {
  const client = useApiClient();
  const { id = "" } = useParams();
  const [query] = useApiQuery(useCallback(() => getSchema(client, id), [client, id]));
  const save: Save = (form) => {
    const body = contentOf(form);
    return body === null ? null : updateSchema(client, id, body);
  };

  if (query.kind === "loading") return <LoadingView label="Loading the schema" />;
  if (query.kind === "failed") return <ProblemAlert problem={query.problem} />;
  const { name } = query.value;
  return (
    <SchemaEditor
      title={`Edit ${name}`}
      mode="edit"
      initial={query.value}
      save={save}
      cancelTo={schemaPath(id)}
    />
  );
}
