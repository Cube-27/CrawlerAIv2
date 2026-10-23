import { Link, Typography } from "@heroui/react";
import { useParams } from "react-router";
import { configVersionLabel, type ConfigDetail } from "../../api/configs";
import { useConfig } from "../../api/hooks/configs";
import { problemOf } from "../../api/hooks/query";
import { ConfigStatusLabel } from "../../components/ConfigStatusLabel";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { Section } from "../../components/Section";
import { ConfigFieldsTable, useSchemaLabel } from "../sites/ConfigTables";
import { configPath } from "../sites/paths";
import { recipesPath } from "./paths";

/** What the recipe serves and how: its patterns, schema and page kind, its main call, drifting fields and a repair
 * waiting for review. */
function RecipeFacts({ recipe }: Readonly<{ recipe: ConfigDetail }>) {
  const schemaLabel = useSchemaLabel();
  const main = recipe.ir.api_recipe;
  return (
    <div className="flex flex-col gap-2">
      <Typography.Paragraph>
        {schemaLabel(recipe)}, {recipe.page_kind} pages, sent by {recipe.sent_by}
      </Typography.Paragraph>
      <ul aria-label="Patterns" className="flex flex-col gap-1 font-mono text-sm">
        {recipe.patterns.map((pattern) => (
          <li key={pattern}>{pattern}</li>
        ))}
      </ul>
      {main == null ? null : (
        <Typography.Paragraph className="font-mono text-sm break-all">
          Main call: {main.method} {main.url}
        </Typography.Paragraph>
      )}
      <Typography.Paragraph>
        Drifting: {recipe.drifting.length === 0 ? "none" : recipe.drifting.join(", ")}
      </Typography.Paragraph>
      {recipe.pending_repair === null ? null : (
        <Link href={configPath(recipe.pending_repair)}>Review the pending repair</Link>
      )}
    </div>
  );
}

function recipeTitle(recipe: ConfigDetail): string {
  const { site } = recipe;
  return `Recipe of ${site}, ${configVersionLabel(recipe)}`;
}

/** One custom recipe: what it serves, its main call and its fields; the config screen corrects or exports it. */
export function RecipeScreen() {
  const { id = "" } = useParams();
  const recipe = useConfig(id);
  const problem = problemOf(recipe.error);
  return (
    <section className="flex flex-col gap-stack">
      {recipe.isPending ? <LoadingView label="Loading the recipe" /> : null}
      {problem === null ? null : <ProblemAlert problem={problem} />}
      {recipe.isSuccess ? (
        <>
          <PageHeader
            title={recipeTitle(recipe.data)}
            actions={
              <>
                <Link href={recipesPath(recipe.data.site)}>All recipes</Link>
                <Link href={configPath(recipe.data.id)}>Open as a config</Link>
              </>
            }
          >
            <ConfigStatusLabel status={recipe.data.status} />
          </PageHeader>
          <RecipeFacts recipe={recipe.data} />
          <Section title="Fields">
            <ConfigFieldsTable config={recipe.data} />
          </Section>
        </>
      ) : null}
    </section>
  );
}
