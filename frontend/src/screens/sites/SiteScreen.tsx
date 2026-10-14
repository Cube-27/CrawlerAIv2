import { useParams } from "react-router";
import type { ConfigSummary } from "../../api/configs";
import { useSiteConfigs } from "../../api/hooks/configs";
import { problemOf } from "../../api/hooks/query";
import { useSchemas } from "../../api/hooks/schemas";
import { schemaVersionLabel } from "../../api/schemas";
import { EmptyView } from "../../components/EmptyView";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { ConfigVersionsTable } from "./ConfigTables";

/** Names a config's schema version by the schemas the API lists; by its version number until they are read. */
export function useSchemaLabel(): (config: ConfigSummary) => string {
  const schemas = useSchemas();
  const labels = new Map(
    (schemas.data ?? []).map((schema) => [schema.id, schemaVersionLabel(schema)]),
  );
  return (config) =>
    labels.get(config.schema_id) ?? `schema version ${String(config.schema_version)}`;
}

/** One site's config versions (SPEC-12 §4.3): status and field status counts per version; a row opens one. */
export function SiteScreen() {
  const { host = "" } = useParams();
  const configs = useSiteConfigs(host);
  const schemaLabel = useSchemaLabel();
  const problem = problemOf(configs.error);

  return (
    <section className="flex flex-col gap-6">
      <PageHeader title={host} />
      {configs.isPending ? <LoadingView label="Loading the site's configs" /> : null}
      {problem === null ? null : <ProblemAlert problem={problem} />}
      {configs.isSuccess && configs.data.length === 0 ? (
        <EmptyView title="No configs yet">
          A config appears here once learning has run for this site.
        </EmptyView>
      ) : null}
      {configs.isSuccess && configs.data.length > 0 ? (
        <ConfigVersionsTable
          label="Config versions"
          configs={configs.data}
          schemaLabel={schemaLabel}
        />
      ) : null}
    </section>
  );
}
