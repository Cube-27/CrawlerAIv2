import { toast } from "@heroui/react";
import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { problemOf } from "../../api/hooks/query";
import { useCreateSchema, useSchema, useUpdateSchema } from "../../api/hooks/schemas";
import type { Problem } from "../../api/problem";
import type { SchemaDef } from "../../api/schemas";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { SchemaForm } from "../../components/SchemaForm";
import {
  contentOf,
  EMPTY_FORM,
  formOf,
  newSchemaOf,
  type FormMode,
  type SchemaFormState,
} from "../../components/schemaDocument";
import { schemaPath } from "./paths";

/** Opens the version the server stored, with a confirmation. */
function useOpenSaved() {
  const navigate = useNavigate();
  return ({ id, name, version }: SchemaDef) => {
    toast.success(`Saved ${name} version ${String(version)}.`);
    void navigate(schemaPath(id));
  };
}

/** A schema form whose submit goes to `onSave`, with the save's state shown. */
function SchemaEditor({
  title,
  mode,
  initial,
  isPending,
  problem,
  onSave,
  cancelTo,
}: Readonly<{
  title: string;
  mode: FormMode;
  /** The schema the form starts from; null for a blank one. */
  initial: SchemaDef | null;
  isPending: boolean;
  problem: Problem | null;
  onSave: (form: SchemaFormState) => void;
  cancelTo: string;
}>) {
  const navigate = useNavigate();
  const [form, setForm] = useState(() => (initial === null ? EMPTY_FORM : formOf(initial)));
  return (
    <section className="flex flex-col gap-6">
      <PageHeader title={title} />
      <SchemaForm
        form={form}
        mode={mode}
        problem={problem}
        isPending={isPending}
        onChange={setForm}
        onSubmit={onSave}
        onCancel={() => void navigate(cancelTo)}
      />
    </section>
  );
}

/** A new `user` schema (SPEC-12 §4.3), blank or, with `?from=<id>`, prefilled from that schema: adopting a prompt
 * draft creates a user schema from its document. */
export function NewSchemaScreen() {
  const from = useSearchParams()[0].get("from");
  const source = useSchema(from);
  const create = useCreateSchema();
  const openSaved = useOpenSaved();
  const loadProblem = problemOf(source.error);

  if (loadProblem !== null) return <ProblemAlert problem={loadProblem} />;
  if (from !== null && source.data === undefined) {
    return <LoadingView label="Loading the schema" />;
  }
  const initial = source.data ?? null;
  return (
    <SchemaEditor
      title="New schema"
      mode="create"
      initial={initial}
      isPending={create.isPending}
      problem={problemOf(create.error)}
      onSave={(form) => {
        const body = newSchemaOf(form);
        if (body !== null) create.mutate(body, { onSuccess: openSaved });
      }}
      cancelTo={initial === null ? "/schemas" : schemaPath(initial.id)}
    />
  );
}

/** The next version of a schema: its whole document, edited; the name stays (SPEC-07 §4.6). */
export function EditSchemaScreen() {
  const { id = "" } = useParams();
  const schema = useSchema(id);
  const update = useUpdateSchema(id);
  const openSaved = useOpenSaved();
  const loadProblem = problemOf(schema.error);

  if (loadProblem !== null) return <ProblemAlert problem={loadProblem} />;
  if (schema.data === undefined) return <LoadingView label="Loading the schema" />;
  const { name } = schema.data;
  return (
    <SchemaEditor
      title={`Edit ${name}`}
      mode="edit"
      initial={schema.data}
      isPending={update.isPending}
      problem={problemOf(update.error)}
      onSave={(form) => {
        const body = contentOf(form);
        if (body !== null) update.mutate(body, { onSuccess: openSaved });
      }}
      cancelTo={schemaPath(id)}
    />
  );
}
