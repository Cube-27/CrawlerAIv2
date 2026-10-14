import { useParams } from "react-router";
import { useSiteConfigs } from "../../api/hooks/configs";
import { problemOf } from "../../api/hooks/query";
import { EmptyView } from "../../components/EmptyView";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { ConfigVersionsTable, useSchemaLabel } from "./ConfigTables";
import { SiteLearnForm } from "./LearnAction";

/** One site's config versions (SPEC-12 §4.3): status and field status counts per version; a row opens one. "Learn a
 * config" starts learning for a schema chosen here, so a site without a config can get its first. */
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
          A config appears here once learning has run for this site. Learn one below.
        </EmptyView>
      ) : null}
      {configs.isSuccess && configs.data.length > 0 ? (
        <ConfigVersionsTable
          label="Config versions"
          configs={configs.data}
          schemaLabel={schemaLabel}
        />
      ) : null}
      <SiteLearnForm site={host} />
    </section>
  );
}
