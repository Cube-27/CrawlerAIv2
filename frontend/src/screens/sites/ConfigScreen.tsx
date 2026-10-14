import { Chip, Link, Tabs } from "@heroui/react";
import { useParams } from "react-router";
import type { ConfigDetail } from "../../api/configs";
import { useConfig, useSiteConfigs } from "../../api/hooks/configs";
import { problemOf } from "../../api/hooks/query";
import { useSchema } from "../../api/hooks/schemas";
import { ConfigStatusLabel } from "../../components/ConfigStatusLabel";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { ConfigFieldsTable, ConfigVersionsTable, useSchemaLabel } from "./ConfigTables";
import { CorrectionForm } from "./CorrectionForm";
import { ExportPanel } from "./ExportPanel";
import { LearnButtons, useLearn } from "./LearnAction";
import { sitePath } from "./paths";
import { ValidationReportView } from "./ValidationReportView";

/** The other versions of this config: the same site, schema version and page kind. */
function SiblingVersions({ config }: Readonly<{ config: ConfigDetail }>) {
  const configs = useSiteConfigs(config.site);
  const schemaLabel = useSchemaLabel();
  const problem = problemOf(configs.error);
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!configs.isSuccess) return <LoadingView label="Loading the versions" />;
  const versions = configs.data.filter(
    (other) => other.schema_id === config.schema_id && other.page_kind === config.page_kind,
  );
  return <ConfigVersionsTable label="Versions" configs={versions} schemaLabel={schemaLabel} />;
}

/** The correction form needs the schema's fields: a correction may give steps to a field the config lacks. */
function Correction({ config }: Readonly<{ config: ConfigDetail }>) {
  const schema = useSchema(config.schema_id);
  const problem = problemOf(schema.error);
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!schema.isSuccess) return <LoadingView label="Loading the schema" />;
  return <CorrectionForm config={config} schemaFields={Object.keys(schema.data.fields)} />;
}

const TABS = ["Fields", "Validation", "Correct", "Export", "Versions"] as const;

function ConfigTabs({ config }: Readonly<{ config: ConfigDetail }>) {
  return (
    <Tabs>
      <Tabs.ListContainer>
        <Tabs.List aria-label="Config">
          {TABS.map((tab) => (
            <Tabs.Tab key={tab} id={tab}>
              {tab}
              <Tabs.Indicator />
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs.ListContainer>
      <Tabs.Panel id="Fields">
        <ConfigFieldsTable config={config} />
      </Tabs.Panel>
      <Tabs.Panel id="Validation">
        <ValidationReportView report={config.validation_report} />
      </Tabs.Panel>
      <Tabs.Panel id="Correct">
        <Correction config={config} />
      </Tabs.Panel>
      <Tabs.Panel id="Export">
        <ExportPanel config={config} />
      </Tabs.Panel>
      <Tabs.Panel id="Versions">
        <SiblingVersions config={config} />
      </Tabs.Panel>
    </Tabs>
  );
}

function ConfigView({ config }: Readonly<{ config: ConfigDetail }>) {
  const learning = useLearn(config);
  const learnProblem = problemOf(learning.learn.error);
  const schemaLabel = useSchemaLabel();
  return (
    <section className="flex flex-col gap-6">
      <PageHeader title={config.site} actions={<LearnButtons {...learning} />}>
        <Chip>v{config.version}</Chip>
        <Chip>{config.origin}</Chip>
        <ConfigStatusLabel status={config.status} />
      </PageHeader>
      {learnProblem === null ? null : <ProblemAlert problem={learnProblem} />}
      <div className="flex flex-wrap gap-4">
        <Link href={sitePath(config.site)}>Every config of {config.site}</Link>
        <span>
          {schemaLabel(config)}, {config.page_kind} pages
        </span>
      </div>
      <ConfigTabs config={config} />
    </section>
  );
}

/** One config version (SPEC-12 §4.3): its fields' steps, status, yield and validity, its validation report, the
 * correction form, export with the release report, and the other versions; "Learn now" in the header. */
export function ConfigScreen() {
  const { id = "" } = useParams();
  const config = useConfig(id);
  const problem = problemOf(config.error);
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!config.isSuccess) return <LoadingView label="Loading the config" />;
  // Keyed by id: a correction's link to the new version starts its form afresh.
  return <ConfigView key={config.data.id} config={config.data} />;
}
