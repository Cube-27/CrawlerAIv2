import { Button, Chip, Tabs, toast } from "@heroui/react";
import { useNavigate, useParams } from "react-router";
import { problemOf } from "../../api/hooks/query";
import { useRetireSchema, useSchema, useSchemaVersions } from "../../api/hooks/schemas";
import type { SchemaDef } from "../../api/schemas";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { SchemaStatusLabel } from "../../components/SchemaStatusLabel";
import { adoptSchemaPath, editSchemaPath } from "./paths";
import { FieldsTable, SchemaJson, VersionsTable } from "./SchemaViews";

interface SchemaDetail {
  schema: SchemaDef;
  /** Every version of the schema's name. */
  versions: SchemaDef[];
}

function versionLabel({ name, version }: SchemaDef): string {
  return `${name} version ${String(version)}`;
}

/** The changes the server accepts for this version (SPEC-07 §4.6): a preset changes only through its files, an edit
 * goes on the latest version, and only an active version is edited or retired. A refusal is still shown (409). */
function allowedActions({ schema, versions }: SchemaDetail) {
  const changeable = schema.origin !== "preset" && schema.status === "active";
  const latest = Math.max(schema.version, ...versions.map((version) => version.version));
  return {
    edit: changeable && schema.version === latest,
    retire: changeable,
    adopt: schema.origin === "prompt_draft",
  };
}

function DetailActions({
  detail,
  onRetire,
}: Readonly<{ detail: SchemaDetail; onRetire: () => void }>) {
  const navigate = useNavigate();
  const { schema } = detail;
  const allowed = allowedActions(detail);
  return (
    <>
      {allowed.retire ? (
        <ConfirmDialog
          trigger={<Button variant="danger-soft">Retire</Button>}
          title={`Retire ${versionLabel(schema)}?`}
          confirmLabel="Retire"
          onConfirm={onRetire}
        >
          A retired version stays readable, since records and configs refer to it, but it can no
          longer be edited.
        </ConfirmDialog>
      ) : null}
      {allowed.edit ? (
        <Button variant="secondary" onPress={() => void navigate(editSchemaPath(schema.id))}>
          Edit
        </Button>
      ) : null}
      {allowed.adopt ? (
        <Button onPress={() => void navigate(adoptSchemaPath(schema.id))}>
          Adopt as user schema
        </Button>
      ) : null}
    </>
  );
}

const TABS = ["Fields", "JSON", "Versions"] as const;

function SchemaDetailView({
  detail,
  onRetire,
}: Readonly<{ detail: SchemaDetail; onRetire: () => void }>) {
  const { schema, versions } = detail;
  return (
    <>
      <PageHeader
        title={schema.name}
        actions={<DetailActions detail={detail} onRetire={onRetire} />}
      >
        <Chip>v{schema.version}</Chip>
        <Chip>{schema.origin}</Chip>
        <SchemaStatusLabel status={schema.status} />
      </PageHeader>
      <Tabs>
        <Tabs.ListContainer>
          <Tabs.List aria-label="Schema">
            {TABS.map((tab) => (
              <Tabs.Tab key={tab} id={tab}>
                {tab}
                <Tabs.Indicator />
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs.ListContainer>
        <Tabs.Panel id="Fields">
          <FieldsTable schema={schema} />
        </Tabs.Panel>
        <Tabs.Panel id="JSON">
          <SchemaJson schema={schema} />
        </Tabs.Panel>
        <Tabs.Panel id="Versions">
          <VersionsTable versions={versions} />
        </Tabs.Panel>
      </Tabs>
    </>
  );
}

/** One schema version: its fields, its document as JSON and its other versions, with the changes the server allows
 * for it (SPEC-12 §4.3). */
export function SchemaScreen() {
  const { id = "" } = useParams();
  const schema = useSchema(id);
  const versions = useSchemaVersions(schema.data?.name);
  const retire = useRetireSchema();
  const loadProblem = problemOf(schema.error ?? versions.error);
  const retireProblem = problemOf(retire.error);

  const onRetire = (version: SchemaDef) => {
    retire.mutate(version.id, {
      onSuccess: () => {
        toast.success(`Retired ${versionLabel(version)}.`);
      },
    });
  };

  if (loadProblem !== null) return <ProblemAlert problem={loadProblem} />;
  if (schema.data === undefined || versions.data === undefined) {
    return <LoadingView label="Loading the schema" />;
  }
  const detail = { schema: schema.data, versions: versions.data };
  return (
    <section className="flex flex-col gap-6">
      {retireProblem === null ? null : <ProblemAlert problem={retireProblem} />}
      <SchemaDetailView
        detail={detail}
        onRetire={() => {
          onRetire(detail.schema);
        }}
      />
    </section>
  );
}
